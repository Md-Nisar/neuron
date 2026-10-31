#!/usr/bin/env bash
# risk_signals.sh: grep for risky patterns to seed an omni-review audit.
#
# Usage: risk_signals.sh <target_path> [--max <lines-per-signal>]
#
# Output is a list of LEADS, not findings. Every lead must be confirmed or dismissed by
# reading the code and tracing it from an entry point. Expect false positives.
# Lines that may contain secrets are printed as file:line only (values are never shown).
# Read-only: this script never modifies the repository.

set -uo pipefail

TARGET="."
MAX=8
while [[ $# -gt 0 ]]; do
  case "$1" in
    --max) MAX="${2:-8}"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) TARGET="$1"; shift ;;
  esac
done
[[ -e "$TARGET" ]] || { echo "error: target '$TARGET' does not exist" >&2; exit 1; }

EXCLUDE_DIRS=(node_modules vendor target build dist out .git .venv venv __pycache__ .next
  .gradle coverage .terraform .tox site-packages bin obj)
CODE_EXT=(java kt kts scala groovy py ts tsx js jsx mjs cjs go rs rb php cs swift sql rego vue
  svelte yaml yml properties env tf)

if command -v rg >/dev/null 2>&1; then
  ARGS=(-n --with-filename --no-heading --color never --hidden)
  for d in "${EXCLUDE_DIRS[@]}"; do ARGS+=(-g "!$d/"); done
  for e in "${CODE_EXT[@]}"; do ARGS+=(-g "*.$e"); done
  run() { local flags="$1" p="$2"; if [[ "$flags" == *i* ]]; then rg "${ARGS[@]}" -i -e "$p" -- "$TARGET"; else rg "${ARGS[@]}" -e "$p" -- "$TARGET"; fi 2>/dev/null; }
else
  ARGS=(-rnH -I)
  for d in "${EXCLUDE_DIRS[@]}"; do ARGS+=("--exclude-dir=$d"); done
  for e in "${CODE_EXT[@]}"; do ARGS+=("--include=*.$e"); done
  run() { local flags="$1" p="$2"; if [[ "$flags" == *i* ]]; then grep "${ARGS[@]}" -iE -e "$p" -- "$TARGET"; else grep "${ARGS[@]}" -E -e "$p" -- "$TARGET"; fi 2>/dev/null; }
fi

TOTAL=0
# lead <pass> <label> <flags: i=case-insensitive, r=redact> <pattern> [filter]
#   filter: a regex the hit line must also match, or "!regex" to drop lines matching it
lead() {
  local pass="$1" label="$2" flags="$3" pat="$4" filt="${5:-}" hits n
  hits=$(run "$flags" "$pat" | sed 's#^\./##')
  if [[ -n "$filt" && -n "$hits" ]]; then
    if [[ "$filt" == !* ]]; then hits=$(echo "$hits" | grep -viE -- "${filt#!}" || true)
    else hits=$(echo "$hits" | grep -E -- "$filt" || true); fi
  fi
  # skip obvious test fixtures for secret detection
  [[ "$flags" == *r* && -n "$hits" ]] && hits=$(echo "$hits" | grep -viE '(^|/)(test|tests|spec|__tests__|fixtures?)/|example|sample|dummy|changeme|placeholder|xxxx' || true)
  n=$(printf '%s' "$hits" | grep -c . || true)
  [[ "$n" -eq 0 ]] && return
  TOTAL=$((TOTAL + n))
  printf '\n[%s] %s (%s)\n' "$pass" "$label" "$n"
  if [[ "$flags" == *r* ]]; then
    echo "$hits" | cut -d: -f1,2 | head -n "$MAX" | sed 's/^/    /; s/$/  (value redacted)/'
  else
    echo "$hits" | head -n "$MAX" | cut -c1-180 | sed 's/^/    /'
  fi
  [[ "$n" -gt "$MAX" ]] && echo "    ... $((n - MAX)) more"
}

echo "=== RISK SIGNALS for $TARGET ==="
echo "LEADS ONLY: confirm each with an execution trace before reporting. Expect false positives."

# --- Pass 2: Security ---
lead P2 "SQL built by concatenation/interpolation" i \
  '(select|insert|update|delete)[[:space:]].*(from|into|set|where)' \
  '("[[:space:]]*\+|\+[[:space:]]*"|'"'"'[[:space:]]*\+|\$\{|%s|\.format\(|f"|f'"'"'|Sprintf|String\.format|#\{)'
lead P2 "Raw-query escape hatches" "" \
  '\.raw\(|RawSQL|\.extra\(|text\(f|queryRawUnsafe|executeRawUnsafe|createNativeQuery\([^)]*\+|FromSqlRaw|\.query\(`'
lead P2 "Dynamic ORDER BY / column names" i 'order[[:space:]]+by[^"'"'"'`]*(\+|\$\{|%s|\{)'
lead P2 "Dynamic code / command execution" "" \
  'eval\(|new Function\(|exec\(|os\.system\(|shell[[:space:]]*=[[:space:]]*True|Runtime\.getRuntime\(\)\.exec|ProcessBuilder\(|child_process|exec\.Command\('
lead P2 "Unsafe deserialization" "" \
  'pickle\.loads?\(|yaml\.load\([^)]*\)|yaml\.unsafe_load|ObjectInputStream|enableDefaultTyping|activateDefaultTyping|TypeNameHandling\.(All|Auto)|BinaryFormatter|unserialize\(|Marshal\.load'
lead P2 "Unescaped HTML rendering (XSS)" "" \
  'dangerouslySetInnerHTML|v-html|\.innerHTML[[:space:]]*=|\|[[:space:]]*safe|mark_safe\(|th:utext|html_safe|raw\(|bypassSecurityTrust'
lead P2 "TLS verification disabled" i \
  'verify[[:space:]]*=[[:space:]]*false|InsecureSkipVerify:[[:space:]]*true|rejectUnauthorized:[[:space:]]*false|NoopHostnameVerifier|TrustAllCerts|trustAll|CERT_NONE|NODE_TLS_REJECT_UNAUTHORIZED'
lead P2 "Weak hashing / crypto" "" \
  '\bMD5\b|md5\(|MessageDigest\.getInstance\("(MD5|SHA-?1)"|hashlib\.(md5|sha1)\(|createHash\(.(md5|sha1)|DES/|/ECB/|AES/ECB|Cipher\.getInstance\("AES"\)'
lead P2 "Non-cryptographic RNG (check if used for tokens/IDs)" "" \
  'Math\.random\(|new Random\(|java\.util\.Random|random\.(random|randint|choice)\(|math/rand'
lead P2 "Possible hardcoded secrets" ir \
  '(password|passwd|pwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|private[_-]?key|client[_-]?secret)["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"'][^"'"'"'[:space:]]{8,}["'"'"']'
lead P2 "Credential-shaped literals" r \
  'AKIA[0-9A-Z]{16}|-----BEGIN ([A-Z]+ )?PRIVATE KEY|xox[baprs]-[0-9A-Za-z-]{10,}|gh[pousr]_[0-9A-Za-z]{30,}|sk_live_[0-9A-Za-z]{20,}|AIza[0-9A-Za-z_-]{35}'
lead P2 "Sensitive values near logging" i \
  '(log|logger|console|print|fmt\.Print|slog)[^;]*(password|passwd|token|secret|authorization|cookie|ssn|credit|card[_]?number|cvv)'
lead P2 "Permissive CORS" i \
  'Access-Control-Allow-Origin["'"'"']?[,:[:space:]]+["'"'"']?\*|allowedOrigins\("\*"\)|origin:[[:space:]]*(true|["'"'"']\*)|CORS_ORIGIN_ALLOW_ALL[[:space:]]*=[[:space:]]*True'
lead P2 "Auth explicitly bypassed / public" "" \
  'permitAll\(\)|@PermitAll|AllowAnonymous|@csrf_exempt|csrf\(\)\.disable|skip_before_action :authenticate|authentication_classes[[:space:]]*=[[:space:]]*\[\]'
lead P2 "Possible SSRF (outbound URL from variable)" "" \
  '(requests\.(get|post)|httpx\.(get|post)|urlopen|fetch|axios\.(get|post)|http\.Get|getForObject|getForEntity|exchange)\([[:space:]]*(f["'"'"']|`[^`]*\$\{|[a-z_]*(url|uri|link|host|endpoint|target|callback|webhook)[a-z_]*[[:space:]]*[,)]|(request|req|params|query|body)\.|request\.(args|GET|POST|json))'

# --- Pass 1: Correctness / concurrency ---
lead P1 "Empty or swallowing catch blocks" "" \
  'catch[[:space:]]*(\([^)]*\))?[[:space:]]*\{[[:space:]]*\}|except[^:]*:[[:space:]]*pass|except:[[:space:]]*$|\.catch\([[:space:]]*\(\)[[:space:]]*=>[[:space:]]*(\{[[:space:]]*\}|null|undefined)\)'
lead P1 "Go errors discarded" "" '(,[[:space:]]*_[[:space:]]*:?=[[:space:]]*[A-Za-z_.]+\(|^[[:space:]]*_[[:space:]]*=[[:space:]]*[A-Za-z_.]+\()' '\.go:'
lead P1 "Mutable static collections" "" 'static[[:space:]]+[A-Za-z<>, ]*(Map|List|Set)<' '!final'
lead P1 "Mutable static counters/flags" "" 'static[[:space:]]+(int|long|Integer|Long|boolean|Boolean)[[:space:]]+[a-z]' '!final'
lead P1 "Module-level mutable containers (Python/JS)" "" '^(let|var)?[[:space:]]*[A-Za-z_]+[[:space:]]*(:[^=]*)?=[[:space:]]*(\{\}|\[\]|dict\(\)|list\(\)|set\(\)|new Map\(\))[[:space:]]*;?[[:space:]]*$'
lead P1 "Thread-unsafe types / patterns" "" 'SimpleDateFormat|new HashMap<.*static|ThreadLocal<|DateFormat\.getInstance'
lead P1 "Blocking sleep (check for async/event-loop context)" "" 'time\.sleep\(|Thread\.sleep\(|\.block\(\)|\.Result\b|\.Wait\(\)|runBlocking|readFileSync|execSync'
lead P1 "Fire-and-forget async work" "" 'asyncio\.create_task\(|ensure_future\(|^[[:space:]]*go[[:space:]]+func|GlobalScope\.launch|CompletableFuture\.runAsync\(|new Thread\('
lead P1 "Naive / local time" "" 'datetime\.now\(\)|datetime\.utcnow\(\)|new Date\(\)|LocalDateTime\.now\(\)|time\.Now\(\)\.Local|DateTime\.Now\b'
lead P1 "Floating point for money" i '(double|float|Number|f64|f32)[[:space:]]+[a-z_]*(price|amount|total|balance|cost|fee|salary|payment)'
lead P1 "Check-then-act candidates" i \
  'if[[:space:]]*\(?[[:space:]]*!?[[:space:]]*[a-z_.]*(exists|isPresent|isEmpty|count|find)[A-Za-z_]*\(|get_or_create|update_or_create|findOrCreate|upsert'

# --- Pass 3: Performance ---
lead P3 "Unbounded reads" "" 'findAll\(\)|\.objects\.all\(\)|\.all\(\)[[:space:]]*$|SELECT \* FROM|\.find\(\{\}\)|\.findMany\(\)'
lead P3 "Regex/serializer construction (check for loops)" "" 'Pattern\.compile\(|re\.compile\(|new RegExp\(|regexp\.MustCompile\(|new ObjectMapper\(\)|new Gson\(\)'
lead P3 "Deep OFFSET pagination" i 'offset[[:space:]]+[?:$%{]|\.offset\(|\.skip\(|setFirstResult\('
lead P3 "Eager fetch / lazy-load hints" "" 'FetchType\.EAGER|FetchType\.LAZY|lazy=["'"'"'](select|dynamic)|\.lazy\b'

# --- Pass 4: Resilience / observability ---
lead P4 "HTTP calls possibly missing timeouts" "" \
  'requests\.(get|post|put|delete|patch)\(|http\.DefaultClient|http\.(Get|Post)\(|new RestTemplate\(\)|HttpClient\.newHttpClient\(\)|new OkHttpClient\(\)|axios\.(get|post|create)\(|urlopen\(' \
  '!timeout'
lead P4 "Broad catch-alls (check cause is preserved/reported)" "" \
  'catch[[:space:]]*\((Exception|Throwable|RuntimeException|e: Exception|Exception e|error)\b|except[[:space:]]+(Exception|BaseException)\b|rescue[[:space:]]*(=>|$)|recover\(\)'
lead P4 "Retry loops (check backoff, jitter, bound, idempotency)" i '@Retryable|retry|backoff|max_?attempts|maxRetries'

# --- Pass 5: Change safety ---
lead P5 "Disabled / skipped tests" "" '@Disabled|@Ignore\b|\bxit\(|\bxdescribe\(|it\.skip\(|describe\.skip\(|test\.skip\(|pytest\.mark\.skip|unittest\.skip|t\.Skip\('
lead P5 "CREATE INDEX without CONCURRENTLY (Postgres)" i 'create[[:space:]]+(unique[[:space:]]+)?index' '!concurrently'
lead P5 "Table-rewriting / validating DDL" i 'alter[[:space:]]+table.*(not[[:space:]]+null|alter[[:space:]]+column.*type|add[[:space:]]+constraint.*foreign[[:space:]]+key|drop[[:space:]]+column|rename)'
lead P5 "TODO / FIXME / HACK markers" "" '\b(TODO|FIXME|HACK|XXX)\b'

printf '\n=== %s lead(s) total. Verify before reporting; most will be benign. ===\n' "$TOTAL"
