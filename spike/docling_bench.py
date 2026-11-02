"""Docling (docling-serve CPU) quality and speed on the RAG-00.03 corpus (question 1).

Runs inside the docling-serve container, which has no network (`--network none`), and posts each
file to the local API. Writes docling_results.json for docling_score.py.
"""
import json
import pathlib
import sys
import time
import urllib.request
import uuid

API = "http://127.0.0.1:5001/v1/convert/file"
OUT = pathlib.Path("/spike/docling_results.json")


def convert(path: pathlib.Path) -> dict:
    boundary = uuid.uuid4().hex
    fields = {"to_formats": "json", "do_ocr": "true", "table_mode": "accurate", "image_export_mode": "placeholder"}
    body = b""
    for k, v in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{path.name}"\r\n'
             f"Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.load(r)


results = {}
for name in sys.argv[1:]:
    p = pathlib.Path(name)
    t = time.monotonic()
    try:
        doc = convert(p)
        results[p.name] = {"seconds": time.monotonic() - t, "status": doc.get("status"),
                           "document": doc["document"]["json_content"]}
    except Exception as e:  # noqa: BLE001 - spike: record and continue
        results[p.name] = {"seconds": time.monotonic() - t, "error": repr(e)[:300]}
    print(f"{p.name}: {results[p.name]['seconds']:.1f}s {results[p.name].get('status', results[p.name].get('error'))}", flush=True)
    OUT.write_text(json.dumps(results))
