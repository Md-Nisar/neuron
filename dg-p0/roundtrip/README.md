# DG-00.05: Ossie round trip (spike S4)

| File | Purpose |
| --- | --- |
| `convert_ossie.py` | Converts between the pinned Ossie (0.3.0.dev0) and the 0.2.0.dev0 shape Auto Ontology 1.3.0 reads and writes (F10) |
| `roundtrip.py` | Both directions against a running Auto Ontology; writes `out/report.md` and `out/report.json` |
| `out/` | Inputs and outputs of the last run: the merged hand model, what came back, the report |

Run it last: the second direction imports into database d3 and replaces its semantic layer.

    AO_LOCAL_ENV=... AUTO_ONTOLOGY_ADMIN_EMAIL=... OSSIE_SRC=<apache/ossie at 91689e6> \
      PYTHONPATH=../auto-ontology python roundtrip.py http://127.0.0.1:3000 out
