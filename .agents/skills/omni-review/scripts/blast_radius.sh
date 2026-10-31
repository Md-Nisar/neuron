#!/usr/bin/env bash
# blast_radius.sh: build the context map for an omni-review audit.
#
# Usage: blast_radius.sh <target_path> [--base <git-ref>] [--max <lines-per-section>]
#
#   target_path   File or directory under review (default: .)
#   --base REF    Git ref to diff against (e.g. origin/main). If omitted, the script
#                 auto-detects origin/main, origin/master, main, or master.
#   --max N       Cap on output lines per section (default: 40).
#
# Read-only: this script never modifies the repository.

set -uo pipefail   # no -e: grep exits 1 on "no match", which is normal here

TARGET="."
BASE=""
MAX=40
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="${2:-}"; shift 2 ;;
    --max)  MAX="${2:-40}"; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) TARGET="$1"; shift ;;
  esac
done

if [[ ! -e "$TARGET" ]]; then
  echo "error: target '$TARGET' does not exist" >&2
  exit 1
fi

# ---------- paths ----------
if [[ -d "$TARGET" ]]; then
  TARGET_ABS="$(cd "$TARGET" && pwd)"
  TARGET_DIR="$TARGET_ABS"
else
  TARGET_DIR="$(cd "$(dirname "$TARGET")" && pwd)"
  TARGET_ABS="$TARGET_DIR/$(basename "$TARGET")"
fi
ROOT="$(git -C "$TARGET_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
IN_GIT=1
if [[ -z "$ROOT" ]]; then ROOT="$TARGET_DIR"; IN_GIT=0; fi
TARGET_REL="${TARGET_ABS#"$ROOT"}"; TARGET_REL="${TARGET_REL#/}"
[[ -z "$TARGET_REL" ]] && TARGET_REL="."
MODNAME="$(basename "$TARGET_ABS")"; MODNAME="${MODNAME%.*}"

EXCLUDE_DIRS=(node_modules vendor target build dist out .git .hg .svn .venv venv env
  __pycache__ .next .nuxt .gradle .idea .vscode coverage .terraform .tox site-packages
  .mypy_cache .pytest_cache bin obj)
CODE_EXT=(java kt kts scala groovy py ts tsx js jsx mjs cjs go rs rb php cs swift c cc cpp h hpp
  sql rego vue svelte)
CONF_EXT=(yaml yml json toml ini properties env tf hcl xml gradle)

cd "$ROOT" || exit 1

# ---------- search helpers (ripgrep if available, grep otherwise) ----------
if command -v rg >/dev/null 2>&1; then
  RG_ARGS=(-n --with-filename --no-heading --color never --hidden)
  for d in "${EXCLUDE_DIRS[@]}"; do RG_ARGS+=(-g "!$d/"); done
  RG_CODE=(); for e in "${CODE_EXT[@]}"; do RG_CODE+=(-g "*.$e"); done
  s_regex() { local p="$1"; shift; rg "${RG_ARGS[@]}" "${RG_CODE[@]}" -e "$p" -- "$@" 2>/dev/null; }
  s_regex_i() { local p="$1"; shift; rg "${RG_ARGS[@]}" "${RG_CODE[@]}" -i -e "$p" -- "$@" 2>/dev/null; }
  s_word() { local w="$1"; shift; rg "${RG_ARGS[@]}" "${RG_CODE[@]}" -w -F -e "$w" -- "$@" 2>/dev/null; }
  s_files() { local p="$1"; shift; rg "${RG_ARGS[@]}" "${RG_CODE[@]}" -l -e "$p" -- "$@" 2>/dev/null; }
else
  GREP_ARGS=(-rnH -I)
  for d in "${EXCLUDE_DIRS[@]}"; do GREP_ARGS+=("--exclude-dir=$d"); done
  GREP_CODE=(); for e in "${CODE_EXT[@]}"; do GREP_CODE+=("--include=*.$e"); done
  s_regex() { local p="$1"; shift; grep "${GREP_ARGS[@]}" "${GREP_CODE[@]}" -E -e "$p" -- "$@" 2>/dev/null; }
  s_regex_i() { local p="$1"; shift; grep "${GREP_ARGS[@]}" "${GREP_CODE[@]}" -iE -e "$p" -- "$@" 2>/dev/null; }
  s_word() { local w="$1"; shift; grep "${GREP_ARGS[@]}" "${GREP_CODE[@]}" -wF -e "$w" -- "$@" 2>/dev/null; }
  s_files() { local p="$1"; shift; grep "${GREP_ARGS[@]}" "${GREP_CODE[@]}" -lE -e "$p" -- "$@" 2>/dev/null; }
fi

norm() { sed -e 's#^\./##'; }
cap()  { head -n "$1"; }
# Drop lines whose path is inside the target (for "external caller" searches).
outside_target() {
  if [[ "$TARGET_REL" == "." ]]; then cat; return; fi
  awk -v t="$TARGET_REL" 'index($0, t":") != 1 && index($0, t"/") != 1'
}
section() { printf '\n=== %s ===\n' "$1"; }

# ---------- 0. repository and stack ----------
section "0. REPOSITORY & STACK"
echo "Repo root:   $ROOT$( [[ $IN_GIT -eq 1 ]] || echo ' (not a git repo)')"
echo "Target:      $TARGET_REL ($( [[ -d "$TARGET_ABS" ]] && echo directory || echo file))"
MANIFESTS=$(find . -maxdepth 3 \( -name node_modules -o -name vendor -o -name .git \) -prune -o -type f \
  \( -name pom.xml -o -name 'build.gradle*' -o -name package.json -o -name requirements*.txt \
     -o -name pyproject.toml -o -name Pipfile -o -name go.mod -o -name Cargo.toml -o -name Gemfile \
     -o -name composer.json -o -name '*.csproj' -o -name Dockerfile -o -name 'docker-compose*.y*ml' \) \
  -print 2>/dev/null | norm | sort | cap "$MAX")
echo "Manifests:"; [[ -n "$MANIFESTS" ]] && echo "$MANIFESTS" | sed 's/^/  /' || echo "  (none found)"
if [[ -n "$MANIFESTS" ]]; then
  FW=$(echo "$MANIFESTS" | grep -v -i docker | xargs cat 2>/dev/null | grep -ioE \
    'spring-boot|spring-security|hibernate|quarkus|micronaut|django|fastapi|flask|sqlalchemy|celery|express|@nestjs|"next"|react|vue|prisma|typeorm|sequelize|mongoose|gin-gonic|labstack/echo|gorm|sqlx|actix|axum|tokio|diesel|rails|laravel|kafka|redis|grpc|graphql' \
    | tr 'A-Z' 'a-z' | tr -d '"' | sort -u | tr '\n' ' ')
  echo "Frameworks/libs detected: ${FW:-(none recognized)}"
  echo "-> Read the matching sections of references/stack_pitfalls.md"
fi

# ---------- 1. target files ----------
section "1. TARGET FILES (lines  path)"
PRUNE=()
for d in "${EXCLUDE_DIRS[@]}"; do PRUNE+=(-name "$d" -o); done
if [[ "$(basename "$TARGET_ABS")" != .* ]]; then PRUNE+=(-name '.?*' -o); fi
unset 'PRUNE[${#PRUNE[@]}-1]'
NAMES=()
for e in "${CODE_EXT[@]}" "${CONF_EXT[@]}"; do NAMES+=(-name "*.$e" -o); done
unset 'NAMES[${#NAMES[@]}-1]'
FILES=$(find "$TARGET_REL" \( -type d \( "${PRUNE[@]}" \) -prune \) -o \( -type f \( "${NAMES[@]}" \) -print \) 2>/dev/null | norm | sort)
FILE_COUNT=$(printf '%s\n' "$FILES" | grep -c . || true)
if [[ "$FILE_COUNT" -gt 0 ]]; then
  printf '%s\n' "$FILES" | while IFS= read -r f; do printf '%6s  %s\n' "$(wc -l < "$f" | tr -d ' ')" "$f"; done | cap "$MAX"
  [[ "$FILE_COUNT" -gt "$MAX" ]] && echo "  ... ($FILE_COUNT files total, showing $MAX)"
else
  echo "  (no source files found)"
fi
echo "Total files: $FILE_COUNT"

# ---------- 2. changes ----------
section "2. CHANGES IN TARGET"
if [[ $IN_GIT -eq 1 ]]; then
  if [[ -z "$BASE" ]]; then
    CUR=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)
    for cand in origin/main origin/master main master; do
      if git rev-parse --verify -q "$cand" >/dev/null && [[ "$cand" != "$CUR" && "origin/$CUR" != "$cand" ]]; then
        BASE="$cand"; echo "(auto-detected base: $BASE; pass --base to override)"; break
      fi
    done
  fi
  hunks() { awk '/^\+\+\+ /{f=($2=="/dev/null")?"(deleted)":substr($0,7); next}
    /^@@/{split($3,a,","); s=substr(a[1],2)+0; n=(a[2]=="")?1:a[2]+0;
          if(n>0) printf "  %s:L%d-L%d\n", f, s, s+n-1}'; }
  if [[ -n "$BASE" ]]; then
    MB=$(git merge-base "$BASE" HEAD 2>/dev/null || echo "$BASE")
    echo "Committed changes vs $BASE (merge-base ${MB:0:10}):"
    git diff --stat "$MB" HEAD -- "$TARGET_REL" 2>/dev/null | cap "$MAX"
    echo "Changed line ranges (review these first):"
    git diff -U0 "$MB" HEAD -- "$TARGET_REL" 2>/dev/null | hunks | cap $((MAX * 2))
  else
    echo "No base branch found; showing only uncommitted changes."
  fi
  UNC=$(git status --porcelain -- "$TARGET_REL" 2>/dev/null)
  if [[ -n "$UNC" ]]; then
    echo "Uncommitted/staged changes:"; echo "$UNC" | sed 's/^/  /' | cap "$MAX"
    git diff -U0 HEAD -- "$TARGET_REL" 2>/dev/null | hunks | cap "$MAX"
  fi
  echo "Recent commits touching target:"
  git log -n 8 --date=short --format='  %h %ad %an: %s' -- "$TARGET_REL" 2>/dev/null
else
  echo "  (not a git repository; diff mode unavailable)"
fi

# ---------- 3. public symbols ----------
section "3. SYMBOLS DEFINED IN TARGET"
SYM_PATTERN='(public|protected|internal|export|pub)?[[:space:]]*(abstract |final |sealed |data |static |async |default )*(class|interface|enum|record|trait|object|struct|type|function|def|fun|fn)[[:space:]]+[A-Za-z_$][A-Za-z0-9_$]*|func[[:space:]]+(\([^)]*\)[[:space:]]*)?[A-Za-z_][A-Za-z0-9_]*|export[[:space:]]+(const|let|var)[[:space:]]+[A-Za-z_$][A-Za-z0-9_$]*|public[[:space:]]+[A-Za-z0-9_<>,.?[:space:]]+[[:space:]]+[a-zA-Z_][A-Za-z0-9_]*[[:space:]]*\('
s_regex "$SYM_PATTERN" "$TARGET_REL" | norm | cap "$MAX"
STOP='^(main|init|__init__|get|set|run|test|setUp|tearDown|toString|equals|hashCode|handle|execute|process|create|update|delete|apply|build|close|start|stop|value|index|render|constructor|default|config|Config|helper|util|utils|data|item|items|name|type|list|load|save|parse|format|call|invoke|new|then|next|error|errors|result|response|request|props|state)$'
SYMBOLS=$(s_regex "$SYM_PATTERN" "$TARGET_REL" | cut -d: -f3- \
  | grep -oE "$SYM_PATTERN" | sed -E 's/[[:space:]]*\($//' | awk '{print $NF}' \
  | grep -vE "$STOP" | grep -vE '^_' | awk 'length($0) >= 4' | sort -u | head -n 40)

# ---------- 4. upstream callers ----------
section "4. UPSTREAM CALLERS (references from outside the target)"
if [[ "$TARGET_REL" == "." ]]; then
  echo "  (target is the whole repo; pass a narrower path to see external callers)"
else
  echo "-- Imports of '$MODNAME':"
  s_regex "(import|from|require\(|include|use )[^;]*[\"'/.[:space:]]$MODNAME([\"'./;[:space:]]|$)" . | norm | outside_target | cap "$MAX"
  echo "-- References to target symbols:"
  if [[ -n "$SYMBOLS" ]]; then
    TOTAL=0
    while IFS= read -r sym; do
      HITS=$(s_word "$sym" . | norm | outside_target)
      N=$(printf '%s' "$HITS" | grep -c . || true)
      if [[ "$N" -gt 0 ]]; then
        echo "  [$sym] $N reference(s)"; echo "$HITS" | head -n 5 | sed 's/^/    /'
        TOTAL=$((TOTAL + N))
      fi
    done <<< "$SYMBOLS"
    [[ "$TOTAL" -eq 0 ]] && echo "  (no external references found: entry point, dead code, or dynamic dispatch/DI; check routes and config)"
  else
    echo "  (no symbols extracted)"
  fi
fi
echo "-- Entry points inside target (routes, handlers, consumers, jobs):"
s_regex '@(Get|Post|Put|Delete|Patch|Request)Mapping|@(RestController|Controller)|@(KafkaListener|RabbitListener|SqsListener|JmsListener|EventListener|Scheduled)|@(app|router|bp|api)\.(get|post|put|delete|patch|route)|router\.(get|post|put|delete|patch)|app\.(get|post|put|delete|patch|use)\(|path\(|urlpatterns|@(shared_task|task|celery)|HandleFunc|\.Handle\(|r\.(GET|POST|PUT|DELETE|PATCH)|@(Get|Post|Put|Delete|Patch)\(|export (async )?function (GET|POST|PUT|DELETE|PATCH)|#\[(get|post|put|delete)' "$TARGET_REL" | norm | cap "$MAX"

# ---------- 5. tests ----------
section "5. RELATED TESTS"
TEST_FILES=$(find . \( -type d \( "${PRUNE[@]}" \) -prune \) -o -type f \( -name '*Test.java' -o -name '*Tests.java' -o -name '*IT.java' \
  -o -name '*Test.kt' -o -name '*Spec.kt' -o -name 'test_*.py' -o -name '*_test.py' -o -name '*_test.go' \
  -o -name '*.test.ts' -o -name '*.test.tsx' -o -name '*.test.js' -o -name '*.test.jsx' -o -name '*.spec.ts' \
  -o -name '*.spec.js' -o -name '*_spec.rb' -o -name '*Tests.cs' -o -name '*_test.rego' -o -name '*_test.rs' \) -print 2>/dev/null | norm)
TERMS="$MODNAME"
if [[ -n "$SYMBOLS" ]]; then TERMS="$MODNAME|$(echo "$SYMBOLS" | head -n 15 | paste -sd'|' -)"; fi
if [[ -n "$TEST_FILES" ]]; then
  REL_TESTS=$(echo "$TEST_FILES" | while IFS= read -r t; do grep -lE "\b($TERMS)\b" "$t" 2>/dev/null; done | sort -u)
  if [[ -n "$REL_TESTS" ]]; then
    echo "$REL_TESTS" | cap "$MAX"
  else
    echo "  (no tests reference this target: treat changed behavior as untested until proven otherwise)"
  fi
  echo "Total test files in repo: $(echo "$TEST_FILES" | grep -c .)"
else
  echo "  (no test files found in repo)"
fi

# ---------- 6. downstream boundaries ----------
section "6. DOWNSTREAM BOUNDARIES IN TARGET"
boundary() {
  local label="$1" pat="$2" hits n
  hits=$(s_regex "$pat" "$TARGET_REL" | norm)
  n=$(printf '%s' "$hits" | grep -c . || true)
  if [[ "$n" -gt 0 ]]; then
    printf -- '-- %s: %s match(es)\n' "$label" "$n"
    echo "$hits" | head -n 6 | cut -c1-200 | sed 's/^/    /'
  fi
}
boundary "Database / ORM" '(SELECT|INSERT INTO|UPDATE|DELETE FROM)[[:space:]]|@Query|@Transactional|@Entity|@Table|Repository|JdbcTemplate|EntityManager|\.objects\.|session\.(query|execute|add|commit)|cursor\.execute|db\.(Query|Exec|Get|Select)|knex|prisma\.|sequelize|getRepository|createQueryBuilder|gorm\.|sqlx\.|ActiveRecord|DbContext|mongoose|collection\.(find|insert|update)'
boundary "Outbound HTTP / RPC" 'RestTemplate|WebClient|HttpClient|OkHttp|Feign|requests\.(get|post|put|delete|patch|request)|httpx\.|aiohttp|urllib|urlopen|fetch\(|axios|got\(|http\.(Get|Post|NewRequest|DefaultClient)|reqwest|grpc\.|Stub\('
boundary "Cache" '@Cacheable|@CacheEvict|@CachePut|[Rr]edis|[Mm]emcache|Caffeine|lru_cache|functools\.cache|cache\.(get|set|put|delete)|unstable_cache'
boundary "Messaging / async jobs" '[Kk]afka|RabbitMQ|amqp|SQS|SNS|PubSub|[Pp]ublish\(|@KafkaListener|@RabbitListener|celery|\.delay\(|apply_async|bullmq|[Nn]ats|EventBridge|outbox'
boundary "Object storage / files" 'S3Client|AmazonS3|s3\.|putObject|getObject|[Pp]resign|GCS|storage\.bucket|BlobClient|FileInputStream|FileOutputStream|os\.Open|os\.Create|fs\.(read|write|createReadStream)|open\(.+["'"'"'][rwa]'
boundary "AuthN / AuthZ / policy" '@PreAuthorize|@Secured|@RolesAllowed|hasRole|hasAuthority|[Pp]ermission|[Aa]uthoriz|opa|[Rr]ego|[Cc]asbin|current_user|request\.user|getPrincipal|SecurityContext|[Jj][Ww][Tt]|tenant[_]?[Ii]d|TenantId'
boundary "Process / dynamic execution" 'exec\(|eval\(|subprocess|Runtime\.getRuntime|ProcessBuilder|os\.system|child_process|exec\.Command|new Function\('
boundary "Config / env" 'getenv|os\.environ|process\.env|@Value\(|System\.getenv|viper\.|@ConfigurationProperties|settings\.'

# ---------- 7. schema & migrations ----------
section "7. SCHEMA & MIGRATIONS"
MIG_DIRS=$(find . \( -type d \( "${PRUNE[@]}" \) -prune \) -o -type d \( -name migrations -o -name migrate -o -name versions \
  -o -name changelog -o -name flyway -o -name liquibase -o -name schema \) -print 2>/dev/null | norm | cap 10)
if [[ -n "$MIG_DIRS" ]]; then
  echo "$MIG_DIRS" | while IFS= read -r d; do
    echo "-- $d (latest):"; ls -1 "$d" 2>/dev/null | sort | tail -n 5 | sed 's/^/    /'
  done
else
  echo "  (no migration directories found)"
fi
if [[ $IN_GIT -eq 1 && -n "$BASE" ]]; then
  CHANGED_MIG=$(git diff --name-only "${MB:-$BASE}" HEAD 2>/dev/null | grep -iE 'migrat|flyway|liquibase|alembic|schema|\.sql$' || true)
  [[ -n "$CHANGED_MIG" ]] && { echo "Migrations/schema changed in this branch (Pass 5, section 2):"; echo "$CHANGED_MIG" | sed 's/^/  /'; }
  CHANGED_DEPS=$(git diff --name-only "${MB:-$BASE}" HEAD 2>/dev/null | grep -E '(package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|pom\.xml|build\.gradle|requirements.*\.txt|poetry\.lock|pyproject\.toml|go\.(mod|sum)|Cargo\.(toml|lock)|Gemfile(\.lock)?)$' || true)
  [[ -n "$CHANGED_DEPS" ]] && { echo "Dependency manifests changed in this branch (Pass 5, section 4):"; echo "$CHANGED_DEPS" | sed 's/^/  /'; }
fi

section "DONE"
echo "Next: run risk_signals.sh on the same target, then read target files, callers, and tests."
