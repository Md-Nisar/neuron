#!/usr/bin/env bash
# Validate the hand-written Ossie models (DG-00.02) with one command.
#   OSSIE_SRC=/path/to/apache/ossie D3_DSN="host=... port=..." ./validate.sh
# OSSIE_SRC is a checkout of github.com/apache/ossie at the pinned commit (spec 0.3.0.dev0).
# Python needs jsonschema 4.26.0, pyyaml 6.0.3, sqlglot 30.33.0 and psycopg 3.
# Databases d3 (../d3/load.sh) and d1 (../d1/load.sh) must be loaded.
set -euo pipefail
cd "$(dirname "$0")"
PIN=91689e626213f3213ae206d9d408b452de5f40dd
: "${OSSIE_SRC:?set OSSIE_SRC to an apache/ossie checkout at $PIN}"
: "${D3_DSN:?set D3_DSN to the spike server, without dbname}"
PY="${PYTHON:-python}"
[ "$(git -C "$OSSIE_SRC" rev-parse HEAD)" = "$PIN" ] || { echo "OSSIE_SRC is not at $PIN" >&2; exit 1; }
validate() { "$PY" -I "$OSSIE_SRC/validation/validate.py" --schema "$OSSIE_SRC/core-spec/ossie-schema.json" "$@"; }

# 1. The pinned Ossie validator: schema plus its semantic checks.
validate d3_sales.ossie.yaml d3_skills.ossie.yaml d1_wwi.ossie.yaml

# 2. Negative control: a model with a dangling relationship must fail, or step 1 proves nothing.
bad=$(mktemp --suffix=.ossie.yaml); trap 'rm -f "$bad"' EXIT
sed 's/from_columns: \[customer_id\], to_columns: \[customer_id\]}/from_columns: [customer_id], to_columns: [no_such_field]}/' \
  d3_sales.ossie.yaml > "$bad"
if validate "$bad" > /dev/null 2>&1; then echo "FAIL negative control passed validation" >&2; exit 1; fi
echo "PASS negative control rejected"

# 3. Every field, metric and relationship runs against the live database.
"$PY" check_models.py d3_sales.ossie.yaml d3 | tail -1
"$PY" check_models.py d3_skills.ossie.yaml d3 | tail -1
"$PY" check_models.py d1_wwi.ossie.yaml d1 | tail -1
echo "all models valid"
