# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The hard-question eval fixture (RAG-13.01), selected from published benchmarks.

Each category comes from a benchmark whose licence allows redistribution with attribution:

    multi_hop, unanswerable  MuSiQue v1.0 dev (Stony Brook NLP, TACL 2022), CC BY 4.0
    comparison               2WikiMultihopQA dev (NII, COLING 2020), Apache-2.0
    synthesis                FRAMES test (Google, 2024), Apache-2.0; articles fetched from
                             Wikipedia at the last revision before 2024-09-01
    follow_up                MTRAG human, ClapNQ domain (IBM, TACL 2025), Apache-2.0
    vocabulary_mismatch      ClapNQ dev answerable (IBM), Apache-2.0

The passages are Wikipedia text (CC BY-SA 4.0). The selection uses a fixed seed, so the same
downloads give the same cases. Download the sources once, then build:

    python3 scripts/build_hard_eval.py fetch DIR   # downloads, checked against SOURCES' sha256
    python3 scripts/build_hard_eval.py build DIR   # writes tests/fixtures/knowledge/hard/
"""

from __future__ import annotations

import ast
import collections
import gzip
import hashlib
import html.parser
import io
import json
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests/fixtures/knowledge/hard"
SEED = 20261127
WIKI_BEFORE = "2024-09-01T00:00:00Z"
USER_AGENT = "neuron-eval-fixture-builder/1.0 (research; Wikipedia API)"
WIKI_TEXT = "CC BY-SA 4.0"

# name -> (url, sha256 of the download, file to keep)
SOURCES = {
    "musique": (
        "https://drive.usercontent.google.com/download?id=1tGdADlNjWFaHLeZZGShh2IRcpO6Lv24h"
        "&export=download&confirm=t",
        "98f839bf2fd5319f5c688aed77901a6d5c30b3b9f9f691ab9a8ecafb045ee0cd",
        "musique.zip",
    ),
    "2wiki": (
        "https://www.dropbox.com/s/ms2m13252h6xubs/data_ids_april7.zip?dl=1",
        "95df2bf56fdabe034e27aebc580e02264232203cf52552f9efe8a919e5529eef",
        "2wiki.zip",
    ),
    "frames": (
        "https://huggingface.co/datasets/google/frames-benchmark/resolve/main/test.tsv",
        "4255093c93b595b5b04c7c8dde290b48ec87d72ca0fb0b760d9dd02740d669ff",
        "frames.tsv",
    ),
}

# GitHub refuses archive downloads through some proxies, so these are cloned at a pinned commit
# (git checks the content) and only the paths used are archived.
# name -> (repository, commit, file to keep, paths)
GIT_SOURCES = {
    "mtrag": (
        "https://github.com/IBM/mt-rag-benchmark.git",
        "e0970de1b1207c2a9506adf238e6e1a22037e38a",
        "mtrag.zip",
        ("LICENSE", "mtrag-human", "corpora/passage_level/clapnq.jsonl.zip"),
    ),
    "clapnq": (
        "https://github.com/primeqa/clapnq.git",
        "c508d78d8c5c2eecbf172fcf5f789004206e11fb",
        "clapnq.zip",
        ("LICENSE", "annotated_data"),
    ),
}

COUNTS = {
    "multi_hop": 15,
    "comparison": 12,
    "synthesis": 10,
    "follow_up": 15,
    "vocabulary_mismatch": 10,
    "unanswerable": 10,
}

BENCHMARKS = {
    "musique": {
        "name": "MuSiQue v1.0",
        "url": "https://github.com/StonyBrookNLP/musique",
        "licence": "CC BY 4.0",
    },
    "2wiki": {
        "name": "2WikiMultihopQA",
        "url": "https://github.com/Alab-NII/2wikimultihop",
        "licence": "Apache-2.0",
    },
    "frames": {
        "name": "FRAMES",
        "url": "https://huggingface.co/datasets/google/frames-benchmark",
        "licence": "Apache-2.0",
    },
    "mtrag": {
        "name": "MTRAG (human), ClapNQ domain",
        "url": "https://github.com/IBM/mt-rag-benchmark",
        "licence": "Apache-2.0",
    },
    "clapnq": {
        "name": "ClapNQ",
        "url": "https://github.com/primeqa/clapnq",
        "licence": "Apache-2.0",
    },
}

STOP = set(
    "a an the of in on at to for from by with and or but is are was were be been being do does "
    "did what which who whom whose when where why how that this these those it its as into than "
    "then there their they he she his her him we you your i me my our not no yes can could will "
    "would should may might has have had about after before during between over under up down "
    "out off so such if also any all each other some most more many much one two first new".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 2}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "untitled"


def _evidence(text: str) -> str:
    """A short quote that identifies a passage: its first sentence, at most 160 characters."""
    sentence = re.split(r"(?<=[.!?])\s", " ".join(text.split()), maxsplit=1)[0]
    return sentence[:160]


class Corpus:
    """Documents keyed by id; a document is a title and its passages, in order."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def add(self, source: str, title: str, passages: list[str], **meta: Any) -> str:
        doc_id = f"{source}-{_slug(title)}"
        doc = self.docs.setdefault(
            doc_id, {"id": doc_id, "title": title, "source": source, "passages": [], **meta}
        )
        for p in passages:
            p = " ".join(p.split())
            if p and p not in doc["passages"]:
                doc["passages"].append(p)
        return doc_id

    def contains(self, text: str) -> bool:
        text = " ".join(text.split())
        return any(text in p for d in self.docs.values() for p in d["passages"])


# ---------------------------------------------------------------- MuSiQue


def _musique(src: Path, rng: random.Random, corpus: Corpus) -> list[dict[str, Any]]:
    with zipfile.ZipFile(src / "musique.zip") as z:
        name = next(n for n in z.namelist() if n.endswith("musique_full_v1.0_dev.jsonl"))
        rows = [json.loads(line) for line in z.read(name).decode().splitlines()]
    pairs: dict[str, dict[bool, dict[str, Any]]] = collections.defaultdict(dict)
    for r in rows:
        pairs[r["id"]][r["answerable"]] = r
    ids = sorted(i for i, p in pairs.items() if True in p and False in p)
    rng.shuffle(ids)

    def add(r: dict[str, Any]) -> dict[str, str]:
        where = {}
        for p in r["paragraphs"]:
            where[p["idx"]] = corpus.add("musique", p["title"], [p["paragraph_text"]])
        return where

    cases, used = [], set()
    for hops in ("2hop", "3hop", "4hop"):
        for i in [x for x in ids if x.startswith(hops)][: COUNTS["multi_hop"] // 3]:
            r = pairs[i][True]
            where = add(r)
            used.add(i)
            sources = [
                {"document": where[p["idx"]], "evidence": _evidence(p["paragraph_text"])}
                for p in r["paragraphs"]
                if p["is_supporting"]
            ]
            cases.append(
                {
                    "category": "multi_hop",
                    "benchmark": {"source": "musique", "id": i},
                    "question": r["question"],
                    "required_sources": sources,
                    "answer": {"text": r["answer"], "aliases": r["answer_aliases"]},
                    "hops": int(hops[0]),
                }
            )
    unanswerable = []
    for i in ids:
        if i in used:
            continue
        r, twin = pairs[i][False], pairs[i][True]
        own = {" ".join(p["paragraph_text"].split()) for p in r["paragraphs"]}
        withheld = [
            p["paragraph_text"]
            for p in twin["paragraphs"]
            if p["is_supporting"] and " ".join(p["paragraph_text"].split()) not in own
        ]
        if not withheld:
            continue
        unanswerable.append((i, r, withheld))
        if len(unanswerable) == COUNTS["unanswerable"]:
            break
    for i, r, withheld in unanswerable:
        add(r)
        cases.append(
            {
                "category": "unanswerable",
                "benchmark": {"source": "musique", "id": i},
                "question": r["question"],
                "required_sources": [],
                "withheld_evidence": [_evidence(w) for w in withheld],
                "answer": None,
            }
        )
    return cases


# ---------------------------------------------------------- 2WikiMultihopQA


def _two_wiki(src: Path, rng: random.Random, corpus: Corpus) -> list[dict[str, Any]]:
    with zipfile.ZipFile(src / "2wiki.zip") as z:
        name = next(n for n in z.namelist() if n.endswith("dev.json"))
        rows = json.loads(z.read(name))
    rows.sort(key=lambda r: r["_id"])
    rng.shuffle(rows)
    cases = []
    for kind in ("comparison", "bridge_comparison"):
        for r in [x for x in rows if x["type"] == kind][: COUNTS["comparison"] // 2]:
            where = {t: corpus.add("2wiki", t, [" ".join(s)]) for t, s in r["context"]}
            sentences = {t: s for t, s in r["context"]}
            sources = []
            for title, idx in r["supporting_facts"]:
                entry = {"document": where[title], "evidence": _evidence(sentences[title][idx])}
                if entry not in sources:
                    sources.append(entry)
            cases.append(
                {
                    "category": "comparison",
                    "benchmark": {"source": "2wiki", "id": r["_id"], "type": kind},
                    "question": r["question"],
                    "required_sources": sources,
                    "answer": {"text": r["answer"], "aliases": []},
                }
            )
    return cases


# ------------------------------------------------------------------ FRAMES


class _Text(html.parser.HTMLParser):
    """Paragraphs of a Wikipedia article's HTML, with section headings, no tables or references."""

    SKIP_TAGS = {"table", "style", "script", "sup", "figure", "math"}
    SKIP_CLASSES = ("mw-editsection", "navbox", "reflist", "infobox", "hatnote", "thumb")
    VOID = {"br", "img", "meta", "link", "hr", "wbr", "input", "source", "area", "col"}
    BLOCKS = {"p", "li", "h2", "h3"}

    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.stack: list[tuple[str, bool]] = []  # (tag, skipped)
        self.buf: list[str] = []

    def _skipped(self) -> bool:
        return bool(self.stack) and self.stack[-1][1]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.VOID:
            return
        cls = dict(attrs).get("class") or ""
        skip = self._skipped() or tag in self.SKIP_TAGS or any(c in cls for c in self.SKIP_CLASSES)
        if tag in self.BLOCKS and not skip:
            self.buf = []
        self.stack.append((tag, skip))

    def handle_endtag(self, tag: str) -> None:
        if not any(t == tag for t, _ in self.stack):
            return
        while self.stack:
            open_tag, skip = self.stack.pop()
            if open_tag == tag:
                break
        if tag in self.BLOCKS and not skip:
            text = " ".join("".join(self.buf).split())
            if text:
                self.out.append(("## " if tag in ("h2", "h3") else "") + text)
            self.buf = []

    def handle_data(self, data: str) -> None:
        if not self._skipped():
            self.buf.append(data)


def _wiki(title: str, cache: Path) -> tuple[int, str]:
    """The last revision of `title` before WIKI_BEFORE: its id and its paragraphs as text."""
    cached = cache / f"{hashlib.sha256(title.encode()).hexdigest()[:24]}.json"
    if cached.exists():
        rev, text = json.loads(cached.read_text(encoding="utf-8"))
        return int(rev), str(text)
    api = "https://en.wikipedia.org/w/api.php?"

    def fetch(url: str) -> bytes:
        for attempt in range(8):
            time.sleep(1.0)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                    body: bytes = resp.read()
                return body
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == 7:
                    raise
                time.sleep(min(60.0, float(exc.headers.get("Retry-After") or 10 * (attempt + 1))))
        raise AssertionError("unreachable")

    def get(params: dict[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
        data: dict[str, Any] = json.loads(fetch(api + query))
        return data

    page = get(
        {
            "action": "query",
            "prop": "revisions",
            "titles": title,
            "redirects": "1",
            "rvlimit": "1",
            "rvdir": "older",
            "rvstart": WIKI_BEFORE,
            "rvprop": "ids",
        }
    )["query"]["pages"][0]
    rev = page["revisions"][0]["revid"]
    # The rendered article at that revision (index.php's render action, lighter than the API's).
    render = "https://en.wikipedia.org/w/index.php?"
    parsed = fetch(
        render + urllib.parse.urlencode({"oldid": str(rev), "action": "render"})
    ).decode()
    p = _Text()
    p.feed(parsed)
    cache.mkdir(exist_ok=True)
    cached.write_text(json.dumps([rev, "\n\n".join(p.out)]), encoding="utf-8")
    return rev, "\n\n".join(p.out)


def _frames(src: Path, rng: random.Random, corpus: Corpus) -> list[dict[str, Any]]:
    import csv

    with open(src / "frames.tsv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    pool = []
    for r in rows:
        links = ast.literal_eval(r["wiki_links"])
        if not all("en.wikipedia.org/wiki/" in link for link in links):
            continue
        kinds = r["reasoning_types"]
        if 3 <= len(links) <= 4 and "Temporal" not in kinds and "Tabular" not in kinds:
            pool.append((r, links))
    pool.sort(key=lambda x: int(x[0][""]))
    rng.shuffle(pool)
    cases = []
    for r, links in pool:
        sources, ok = [], True
        for link in links:
            title = urllib.parse.unquote(link.rsplit("/wiki/", 1)[1]).replace("_", " ")
            try:
                rev, text = _wiki(title, src / "wikipedia")
            except (KeyError, IndexError, OSError):
                ok = False
                break
            if len(text) > 120_000:  # very long articles would dominate the corpus
                ok = False
                break
            paragraphs = [p for p in text.split("\n\n") if p]
            doc = corpus.add("frames", title, paragraphs, url=link, revision=rev)
            sources.append({"document": doc, "evidence": None})
        if not ok:
            continue
        cases.append(
            {
                "category": "synthesis",
                "benchmark": {"source": "frames", "id": r[""], "reasoning": r["reasoning_types"]},
                "question": r["Prompt"].strip(),
                "required_sources": sources,
                "answer": {"text": r["Answer"].strip(), "aliases": []},
            }
        )
        if len(cases) == COUNTS["synthesis"]:
            break
    return cases


# ------------------------------------------------------- MTRAG and ClapNQ


def _clapnq_corpus(src: Path) -> dict[str, list[tuple[str, str]]]:
    """ClapNQ passages by article title: (passage id, text), from MTRAG's passage-level corpus."""
    with zipfile.ZipFile(src / "mtrag.zip") as z:
        name = next(n for n in z.namelist() if n.endswith("corpora/passage_level/clapnq.jsonl.zip"))
        with zipfile.ZipFile(io.BytesIO(z.read(name))) as inner:
            lines = inner.read(inner.namelist()[0]).decode().splitlines()
    by_title: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for line in lines:
        r = json.loads(line)
        title, _, body = r["text"].partition("\n")
        by_title[title].append((r["_id"], body))
    return by_title


def _article(corpus: Corpus, source: str, title: str, passages: list[tuple[str, str]]) -> str:
    return corpus.add(source, title, [body for _, body in passages])


def _mtrag(
    src: Path, rng: random.Random, corpus: Corpus, articles: dict[str, list[tuple[str, str]]]
) -> list[dict[str, Any]]:
    with zipfile.ZipFile(src / "mtrag.zip") as z:

        def lines(suffix: str) -> list[str]:
            name = next(n for n in z.namelist() if n.endswith(suffix))
            return z.read(name).decode().splitlines()

        tasks = [json.loads(x) for x in lines("mtrag-human/generation_tasks/reference.jsonl")]
        last = {}
        for x in lines("retrieval_tasks/clapnq/clapnq_lastturn.jsonl"):
            r = json.loads(x)
            last[r["_id"]] = r["text"]
        rewrite = {}
        for x in lines("retrieval_tasks/clapnq/clapnq_rewrite.jsonl"):
            r = json.loads(x)
            rewrite[r["_id"]] = r["text"].removeprefix("|user|: ").strip()
        qrels: dict[str, list[str]] = collections.defaultdict(list)
        for line in lines("retrieval_tasks/clapnq/qrels/dev.tsv")[1:]:
            qid, pid, score = line.split("\t")
            if int(score) > 0:
                qrels[qid].append(pid)
    title_of = {pid: t for t, ps in articles.items() for pid, _ in ps}
    text_of = {pid: body for ps in articles.values() for pid, body in ps}
    by_conv: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for t in tasks:
        key = t["task_id"]
        if (
            "clapnq" in t["Collection"]
            and int(t["turn"]) >= 2
            and _value(t["Multi-Turn"]) == ["Follow-up"]
            and _value(t["Answerability"]) == ["ANSWERABLE"]
            and qrels.get(key)
            and key in rewrite
            and all(p in title_of for p in qrels[key])
            and len(_words(rewrite[key]) - _words(last.get(key, ""))) >= 2
        ):
            by_conv[t["conversation_id"]].append(t)
    conversations = sorted(by_conv)
    rng.shuffle(conversations)
    cases = []
    for conv in conversations[: COUNTS["follow_up"]]:
        options = sorted(by_conv[conv], key=lambda t: int(t["turn"]))
        t = options[rng.randrange(len(options))]
        key = t["task_id"]
        history = _value(t["input"])
        sources = []
        for pid in qrels[key]:
            doc = _article(corpus, "clapnq", title_of[pid], articles[title_of[pid]])
            sources.append({"document": doc, "evidence": _evidence(text_of[pid])})
        cases.append(
            {
                "category": "follow_up",
                "benchmark": {"source": "mtrag", "id": key},
                "question": history[-1]["text"],
                "turns": [
                    {"role": "user" if m["speaker"] == "user" else "assistant", "text": m["text"]}
                    for m in history[:-1]
                ],
                "standalone": rewrite[key],
                "required_sources": sources,
                "answer": None,
                "reference_answer": _value(t["targets"])[0]["text"],
            }
        )
    return cases


def _value(v: Any) -> Any:
    """MTRAG stores some fields as Python literals in strings, others as JSON values."""
    return ast.literal_eval(v) if isinstance(v, str) else v


def _clapnq(
    src: Path, rng: random.Random, corpus: Corpus, articles: dict[str, list[tuple[str, str]]]
) -> list[dict[str, Any]]:
    with zipfile.ZipFile(src / "clapnq.zip") as z:
        name = next(n for n in z.namelist() if n.endswith("dev/clapnq_dev_answerable.jsonl"))
        rows = [json.loads(line) for line in z.read(name).decode().splitlines()]
    scored = []
    for r in rows:
        p = r["passages"][0]
        q = _words(r["input"])
        found = [
            pid for pid, body in articles.get(p["title"], []) if p["text"].strip()[:80] in body
        ]
        if (
            len(q) < 3
            or not found
            or not r["output"]
            or not r["output"][0].get("selected_sentences")
        ):
            continue
        overlap = len(q & _words(p["text"])) / len(q)
        scored.append((overlap, r["id"], r))
    scored.sort(key=lambda x: (x[0], x[1]))
    cases = []
    for overlap, _, r in scored[: COUNTS["vocabulary_mismatch"]]:
        title = r["passages"][0]["title"]
        doc = _article(corpus, "clapnq", title, articles[title])
        evidence = _evidence(r["output"][0]["selected_sentences"][0])
        cases.append(
            {
                "category": "vocabulary_mismatch",
                "benchmark": {"source": "clapnq", "id": r["id"]},
                "question": r["input"],
                "required_sources": [{"document": doc, "evidence": evidence}],
                "answer": None,
                "reference_answer": r["output"][0]["answer"],
                "word_overlap": round(overlap, 3),
            }
        )
    return cases


# ------------------------------------------------------------------- main


def fetch(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name, (url, sha, file) in SOURCES.items():
        path = dest / file
        if not path.exists():
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
            with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310
                path.write_bytes(resp.read())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha and digest != sha:
            raise SystemExit(f"{name}: sha256 {digest} is not the pinned {sha}")
        print(name, digest)
    for name, (repo, commit, file, paths) in GIT_SOURCES.items():
        path = dest / file
        if not path.exists():
            clone = dest / f"{name}.git"
            if not clone.exists():
                _git("clone", "--quiet", "--filter=blob:none", "--no-checkout", repo, str(clone))
            _git("-C", str(clone), "archive", "--format=zip", "-o", str(path), commit, "--", *paths)
        print(name, commit)


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True)  # noqa: S603, S607 - fixed arguments


def build(src: Path) -> None:
    rng = random.Random(SEED)  # noqa: S311 - a fixed seed for a reproducible fixture
    corpus = Corpus()
    articles = _clapnq_corpus(src)
    cases = (
        _musique(src, rng, corpus)
        + _two_wiki(src, rng, corpus)
        + _frames(src, rng, corpus)
        + _mtrag(src, rng, corpus, articles)
        + _clapnq(src, rng, corpus, articles)
    )
    for case in cases:
        if case["category"] == "unanswerable":
            leaked = [w for w in case["withheld_evidence"] if corpus.contains(w)]
            if leaked:
                raise SystemExit(f"{case['benchmark']['id']}: withheld evidence is in the corpus")
    counts = collections.Counter(c["category"] for c in cases)
    if counts != collections.Counter(COUNTS):
        raise SystemExit(f"counts {dict(counts)} are not {COUNTS}")
    for n, case in enumerate(sorted(cases, key=lambda c: list(COUNTS).index(c["category"]))):
        case["id"] = f"hard-{n + 1:03d}"
    cases.sort(key=lambda c: c["id"])
    documents = []
    for doc in sorted(corpus.docs.values(), key=lambda d: d["id"]):
        documents.append(
            {
                **{k: v for k, v in doc.items() if k != "passages"},
                "licence": WIKI_TEXT,
                "text": f"# {doc['title']}\n\n" + "\n\n".join(doc["passages"]) + "\n",
            }
        )
    OUT.mkdir(parents=True, exist_ok=True)
    blob = json.dumps({"documents": documents}, ensure_ascii=False, indent=0, sort_keys=True)
    with gzip.GzipFile(OUT / "documents.json.gz", "wb", mtime=0) as f:
        f.write(blob.encode())
    (OUT / "cases.json").write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "description": "RAG-13.01: hard questions selected from published benchmarks "
                f"by scripts/build_hard_eval.py (seed {SEED}).",
                "benchmarks": BENCHMARKS,
                "documents_file": "documents.json.gz",
                "documents_sha256": hashlib.sha256(blob.encode()).hexdigest(),
                "cases": [
                    {k: case[k] for k in ["id", *sorted(set(case) - {"id"})]} for case in cases
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    size = sum(len(d["text"]) for d in documents)
    print(f"{len(cases)} cases, {len(documents)} documents, {size:,} characters", dict(counts))


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("fetch", "build"):
        raise SystemExit(__doc__)
    {"fetch": fetch, "build": build}[sys.argv[1]](Path(sys.argv[2]))
