"""Record Docling's reply for one file, as docling-serve's `/v1/convert/file` returns it.

Usage (Docling is not a Neuron dependency; install it in a separate environment):
    python -I record.py nist-cswp-29.pdf nist-cswp-29.docling.json.gz

The options are the ones `DoclingServeParser` posts: OCR on, accurate tables, JSON output.
"""

import gzip
import json
import sys
import time
from importlib.metadata import version

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption

options = PdfPipelineOptions(do_ocr=True, do_table_structure=True)
options.table_structure_options.mode = TableFormerMode.ACCURATE
converter = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
)
started = time.monotonic()
result = converter.convert(sys.argv[1])
reply = {
    "status": result.status.value,
    "document": {"json_content": result.document.export_to_dict()},
    "errors": [],
    "processing_time": time.monotonic() - started,
    "_recorded_with": {"docling": version("docling"), "docling-core": version("docling-core")},
}
with gzip.open(sys.argv[2], "wt", encoding="utf-8") as out:
    json.dump(reply, out, separators=(",", ":"))
