"""Recall@5 at 2,048 vs 1,024 dimensions (question 2) on the RAG-00.03 answerable cases.

Usage: embed_recall.py CORPUS_DIR MODEL. Needs LLM_API_KEY (NVIDIA API catalog). Sends only the
public and fictional corpus text. Embeddings are cached in emb_*.npy.
"""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

import numpy as np

CORPUS, MODEL = pathlib.Path(sys.argv[1]), sys.argv[2]
FIX = pathlib.Path("../tests/fixtures")
data = json.loads((FIX / "knowledge_cases.json").read_text())
norm = lambda s: re.sub(r"\s+", " ", s.replace("­", "").replace("ﬁ", "fi").replace("’", "'")).lower().strip()
by_sha = {hashlib.sha256(p.read_bytes()).hexdigest(): p
          for p in list(CORPUS.glob("*")) + list((FIX / "knowledge").rglob("*")) if p.is_file()}
SIZE, STEP = 1200, 1000


def units(doc: dict, path: pathlib.Path) -> list[tuple[str, str]]:
    """(locator, text): a page number for paginated documents, else the nearest heading."""
    if path.suffix == ".pdf":
        text = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True).stdout
        return [(str(i + 1), t) for i, t in enumerate(text.split("\f"))]
    text = (subprocess.run(["pandoc", str(path), "-t", "markdown"], capture_output=True, text=True).stdout
            if path.suffix == ".docx" else path.read_text(encoding="utf-8"))
    if "page_count" in doc:
        return [(str(i + 1), t) for i, t in enumerate(text.split("\f"))]
    out, head, buf = [], "", []
    for line in text.splitlines():
        if re.match(r"^(#{1,6} |\d+(\.\d+)*\.  \S)", line):
            out.append((head, "\n".join(buf))); head, buf = line.strip(), [line]
        else:
            buf.append(line)
    return out + [(head, "\n".join(buf))]


chunks = []  # (doc_id, locator, text)
for d in data["documents"]:
    path = by_sha.get(d["sha256"])
    if path is None or "scanned" in d["classes"]:
        continue
    for loc, text in units(d, path):
        text = re.sub(r"[ \t]+", " ", text).strip()
        for i in range(0, max(1, len(text) - (SIZE - STEP)), STEP):
            if text[i:i + SIZE].strip():
                chunks.append((d["id"], loc, text[i:i + SIZE]))
cases = [c for c in data["cases"] if c["category"] == "answerable"
         and not any("scanned" in next(x for x in data["documents"] if x["id"] == s["document"])["classes"]
                     for s in c["expected_sources"])]
print(f"{len(chunks)} chunks from {len({c[0] for c in chunks})} documents; {len(cases)} answerable cases")


def _post(texts: list[str], input_type: str, dims: int) -> list[list[float]]:
    body = {"model": MODEL, "input": texts, "input_type": input_type,
            "encoding_format": "float", "truncate": "END", "dimensions": dims}
    for attempt in range(5):
        req = urllib.request.Request("https://integrate.api.nvidia.com/v1/embeddings", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return [x["embedding"] for x in json.load(r)["data"]]
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503) or attempt == 4:
                if len(texts) > 1:  # isolate a bad input by halving the batch
                    h = len(texts) // 2
                    return _post(texts[:h], input_type, dims) + _post(texts[h:], input_type, dims)
                raise RuntimeError(f"HTTP {e.code} on input of {len(texts[0])} chars: {texts[0][:80]!r}") from e
            time.sleep(2 ** attempt)
    raise AssertionError


def embed(texts: list[str], input_type: str, dims: int) -> np.ndarray:
    out = []
    for i in range(0, len(texts), 32):
        out += _post(texts[i:i + 32], input_type, dims)
    v = np.array(out, dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def cached(name: str, fn) -> np.ndarray:
    p = pathlib.Path(f"emb_{MODEL.split('/')[-1]}_{name}.npy")
    if not p.exists():
        np.save(p, fn())
    return np.load(p)


def hit(case: dict, chunk: tuple[str, str, str]) -> bool:
    for s in case["expected_sources"]:
        if s["document"] != chunk[0]:
            continue
        if "pages" in s and chunk[1] in {str(p) for p in s["pages"]}:
            return True
        if "sections" in s and (any(norm(x) in norm(chunk[1]) for x in s["sections"]) or norm(case["evidence"]) in norm(chunk[2])):
            return True
    return False


questions = [c["question"] for c in cases]
results = {}
for dims in (2048, 1024):
    t = time.monotonic()
    P = cached(f"passages_{dims}", lambda: embed([c[2] for c in chunks], "passage", dims))
    Q = cached(f"queries_{dims}", lambda: embed(questions, "query", dims))
    results[dims] = (P, Q, time.monotonic() - t)
P2, Q2, _ = results[2048]
results["2048→1024 truncated"] = (P2[:, :1024] / np.linalg.norm(P2[:, :1024], axis=1, keepdims=True),
                                   Q2[:, :1024] / np.linalg.norm(Q2[:, :1024], axis=1, keepdims=True), 0)
for name, (P, Q, secs) in results.items():
    top = np.argsort(-(Q @ P.T), axis=1)
    for k in (1, 5, 10):
        r = np.mean([any(hit(c, chunks[j]) for j in top[i, :k]) for i, c in enumerate(cases)])
        print(f"{name}: recall@{k} = {r:.3f}", end="  ")
    rr = [next((1 / (rank + 1) for rank, j in enumerate(top[i, :10]) if hit(c, chunks[j])), 0) for i, c in enumerate(cases)]
    print(f"MRR@10 = {np.mean(rr):.3f}")
    misses = [c["id"] for i, c in enumerate(cases) if not any(hit(c, chunks[j]) for j in top[i, :5])]
    print(f"  misses@5: {misses}")
