#!/usr/bin/env bash
# Rebuilds the generated corpus files from sources/. Needs pandoc, LibreOffice, poppler-utils and
# Python with Pillow (none of them are Neuron dependencies). The output is not byte-reproducible:
# after a rebuild, update the sha256 and size_bytes of the changed documents in
# tests/fixtures/knowledge_cases.json.
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

pandoc sources/larkspur-handbook.md -o larkspur-handbook.docx

soffice --headless --convert-to pdf --outdir "$tmp" sources/hidden-text.html sources/greenhouse-log.html >/dev/null
cp "$tmp/hidden-text.pdf" injection/hidden-text.pdf

# "Scanned": each page becomes a greyscale image, so the PDF has no text layer and needs OCR.
pdftoppm -r 110 -gray -png "$tmp/greenhouse-log.pdf" "$tmp/page"
python3 - "$tmp" <<'PY'
import sys, pathlib
from PIL import Image
pages = sorted(pathlib.Path(sys.argv[1]).glob("page-*.png"))
images = [Image.open(p).convert("L") for p in pages]
images[0].save("greenhouse-log-scanned.pdf", save_all=True, append_images=images[1:], resolution=110)
PY
