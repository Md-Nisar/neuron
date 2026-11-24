---
name: free-llm-bench
description: List and benchmark free LLM models (NVIDIA NIM, Gemini, Groq, OpenRouter) from env API keys within free-tier limits; print a results table and recommend top free models for dev and testing.
---

# Free LLM Bench

Finds every **free** chat model available to the user's API keys, tests **availability, speed (TTFT, latency, tok/s) and stability** while staying inside each provider's free-tier limits, prints a table, and recommends models for **development** and **testing**, preferring top-quality free models.

## Supported providers & env keys

| Provider | Env vars checked (first found wins) | Free-tier pacing used by the script |
|---|---|---|
| `nvidia` (build.nvidia.com NIM) | `NVIDIA_API_KEY`, `NVIDIA_NIM_API_KEY`, `NIM_API_KEY`, `NGC_API_KEY` | 1 req / 2 s (30 RPM < 40 RPM limit), ≤400 req/day self-cap |
| `gemini` (Google AI Studio) | `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `GOOGLE_GENERATIVE_AI_API_KEY` | 1 req / 2 s globally, ≤4 RPM **per model**, ≤60 req/day; models with `limit: 0` free quota are skipped instantly |
| `groq` (GroqCloud free plan) | `GROQ_API_KEY` | 1 req / 2.5 s globally, ≤10 RPM **per model** (free plan ≈30 RPM per model), ≤150 req/day; reads each model's remaining daily requests from the `x-ratelimit-remaining-requests` header and stops testing a model when fewer than 20 are left |
| `openrouter` (`:free` models only) | `OPENROUTER_API_KEY`, `OPEN_ROUTER_API_KEY` | 1 req / 3.5 s (<20 RPM); reads today's remaining free quota from `/api/v1/key` (50/day, or 1000/day after $10 credits) and spends **≤40%** of it |

The script also loads `.env` / `.env.local` from the current directory. A daily ledger in `~/.cache/free-llm-bench/ledger.json` counts requests across runs (UTC day, or Pacific day for Gemini), so running the skill repeatedly can't blow the free quotas. Failed calls count against OpenRouter's quota, so models that return 404/400/403 are dropped after the first failure, and a daily-limit 429 stops that provider (Gemini and Groq: that model only).

## Procedure

1. **Install/refresh the script.** The script ships with this skill at `.claude/skills/free-llm-bench/bench.py`. If it is missing, or its docstring does not start with `free-llm-bench v1.1.0`, write the script from the **Appendix** below to that path verbatim with the Write tool. It is stdlib-only Python 3.8+, so nothing needs installing.

2. **Choose providers.**
   - If the user named providers (e.g. "just groq and gemini"), pass `-p groq,gemini`. Aliases: `google`→gemini, `nim`→nvidia, `open-router`→openrouter.
   - Otherwise omit `-p`. The script infers providers from whichever env keys are set and tells you which keys are missing.
   - Never print, echo, or log API key values.

3. **Run it** from the user's project directory so `.env` is picked up:
   ```bash
   python3 .claude/skills/free-llm-bench/bench.py [-p ...] [options]
   ```
   Useful options:
   - `--list-only`: list free models with no generation calls (zero quota used). Use this when the user only wants the list.
   - `--probes N`: requests per model. Defaults: nvidia 3, gemini 3, groq 3, openrouter 2. More probes measure stability better but use more quota.
   - `--max-models N`: number of models tested per provider, picked top-first by a quality heuristic. Defaults: nvidia 25, gemini 12, groq 12, openrouter 12, further capped by the daily budget.
   - `--only REGEX`: test only matching model ids, e.g. `--only 'coder|deepseek|kimi|gpt-oss'`.
   - `--show-untested`: include listed but untested models in the table.
   - `--budget-fraction 0.4`: the share of OpenRouter's remaining daily free quota to spend.
   - `--json path`: also save the full results there. They are always saved to `~/.cache/free-llm-bench/latest.json`.

   Providers run in parallel, and each one is paced sequentially. A full run usually takes 2–6 minutes because of the pacing. Run it with a long timeout (e.g. 600000 ms) or in the background, and tell the user it is pacing on purpose to respect the free limits.

4. **Present the results.**
   - Show the printed table as is, in a code block.
   - Column meanings: **Qual** is the heuristic quality score (0–100). **Succ** is ok/attempts (availability). **Stab** is success rate penalised by latency jitter (stability). **TTFT** is the median time to first token. **p50** is the median total latency. **tok/s** is the median output speed.
   - Mention per-provider notes: quota left, early stops, models with no free quota, and Groq models stopped to preserve daily quota.

5. **Make the final recommendation.** The script's Qual score is only a name-based heuristic. Re-rank the script's suggestions with your own knowledge of which current models are strongest, especially for coding and reasoning, but recommend **only models that passed** (Succ ≥ 2/3, ideally Stab ≥ 70). Give:
   - **Development (primary):** 1–3 top-quality models that are reliably available. Prefer frontier open-weight or Gemini Pro-class models, and say which is best for coding agents.
   - **Testing / CI:** 1–3 fast, stable, quota-friendly models. Groq is usually the fastest (very high tok/s) and its small models have large free RPD. NVIDIA has no daily cap, only an RPM limit; Gemini Flash/Flash-Lite and Gemma have higher free RPD. Avoid OpenRouter `:free` for CI unless the user has the 1000/day tier. Note Groq's per-model TPM caps (a few thousand tokens/min on some models) for long-prompt tests.
   - **Fallback chain:** an ordered list across providers, so a 429 from one provider falls through to the next.
   - For each pick, give the exact provider + model id, plus a one-line config hint: base URL (`https://integrate.api.nvidia.com/v1`, `https://api.groq.com/openai/v1`, `https://openrouter.ai/api/v1`, or Gemini's OpenAI-compatible `https://generativelanguage.googleapis.com/v1beta/openai/`) and the env var to use.
   - Warn briefly about free-tier caveats: free model lists rotate, limits change without notice, free tiers may log prompts, and NVIDIA's free tier is for dev/eval, not production.

6. If a provider fails entirely (bad key, 401, or network error), report it plainly and continue with the others. If everything is rate-limited, suggest re-running after the daily reset: 00:00 UTC for OpenRouter, midnight Pacific for Gemini, and the `x-ratelimit-reset-requests` time for Groq.

## Appendix — `bench.py` (write verbatim)

```python
#!/usr/bin/env python3
"""free-llm-bench v1.1.0 — list & benchmark FREE LLM models on NVIDIA NIM, Google Gemini,
Groq and OpenRouter, staying inside each provider's free-tier limits. Stdlib only.

Usage:
  python3 bench.py                         # infer providers from env keys
  python3 bench.py -p nvidia,gemini        # pick providers
  python3 bench.py --list-only             # just list models, no generation calls
  python3 bench.py --probes 3 --max-models 15 --json out.json
"""
import argparse, datetime, json, math, os, pathlib, re, statistics, sys, threading, time
import urllib.error, urllib.request

VERSION = "1.1.0"
CACHE = pathlib.Path(os.environ.get("FREE_LLM_BENCH_DIR", str(pathlib.Path.home() / ".cache" / "free-llm-bench")))
PROMPT = "Reply with the word OK, then count from 1 to 15 separated by spaces. Nothing else."
UA = {"User-Agent": "free-llm-bench/" + VERSION}

# ---------------- provider config (free-tier limits, conservative) ----------------
# OpenRouter: ':free' models -> 20 RPM, 50 RPD (1000 RPD after >=$10 credits ever). Failed calls count.
# Gemini: limits are PER MODEL, PER PROJECT; free RPD can be as low as ~20 on some models, resets midnight PT.
# NVIDIA build.nvidia.com: ~40 RPM per account on the free tier.
# Groq: limits PER MODEL per org (typ. 30 RPM, 250-14.4K RPD, ~6-70K TPM); live RPD left in x-ratelimit-* headers.
PROVIDERS = {
    "nvidia": {
        "env": ["NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "NIM_API_KEY", "NGC_API_KEY"],
        "base": os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        "global_interval": 2.0,   # 30 RPM < 40 RPM limit
        "model_interval": 0.0,
        "daily_budget": 400,      # no published RPD; self-imposed politeness cap per day
        "probes": 3, "max_models": 25,
    },
    "gemini": {
        "env": ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"],
        "base": os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
        "global_interval": 2.0,
        "model_interval": 15.0,   # <= 4 RPM per model (free tiers are 5-30 RPM)
        "daily_budget": 60,       # total across models; per-model RPD handled by 429 detection
        "probes": 3, "max_models": 12,
    },
    "groq": {
        "env": ["GROQ_API_KEY"],
        "base": os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        "global_interval": 2.5,   # ~24 RPM overall
        "model_interval": 6.0,    # <= 10 RPM per model (free is ~30 RPM) and gentle on TPM
        "daily_budget": 150,      # self-cap; per-model RPD read live from headers
        "probes": 3, "max_models": 12,
    },
    "openrouter": {
        "env": ["OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY"],
        "base": os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        "global_interval": 3.5,   # ~17 RPM < 20 RPM
        "model_interval": 0.0,
        "daily_budget": None,     # computed from /key (spend <= 40% of what's left today)
        "probes": 2, "max_models": 12,
    },
}

# ---------------- small utils ----------------
def load_dotenv():
    for p in (pathlib.Path.cwd() / ".env", pathlib.Path.cwd() / ".env.local"):
        if not p.is_file():
            continue
        for line in p.read_text(errors="ignore").splitlines():
            m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", line)
            if m and m.group(1) not in os.environ:
                v = m.group(2).strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                os.environ[m.group(1)] = v

def get_key(name):
    for e in PROVIDERS[name]["env"]:
        if os.environ.get(e):
            return os.environ[e]
    return None

def http(method, url, headers=None, body=None, timeout=60):
    h = dict(UA); h.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    return urllib.request.urlopen(req, timeout=timeout)

def http_json(url, headers=None, timeout=30):
    with http("GET", url, headers, timeout=timeout) as r:
        return json.loads(r.read().decode())

def day_key(provider):
    if provider == "gemini":  # Gemini RPD resets at midnight Pacific
        try:
            from zoneinfo import ZoneInfo
            return datetime.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        except Exception:
            return (datetime.datetime.utcnow() - datetime.timedelta(hours=8)).date().isoformat()
    return datetime.datetime.utcnow().date().isoformat()

class Ledger:
    """Counts generation requests per provider per day across runs, so repeated runs stay within free limits."""
    def __init__(self):
        self.path = CACHE / "ledger.json"; self.lock = threading.Lock()
        try: self.data = json.loads(self.path.read_text())
        except Exception: self.data = {}
    def used(self, p): return self.data.get(p, {}).get(day_key(p), 0)
    def add(self, p):
        with self.lock:
            d = self.data.setdefault(p, {}); k = day_key(p)
            d[k] = d.get(k, 0) + 1
            for old in [x for x in d if x != k]: d.pop(old)
            CACHE.mkdir(parents=True, exist_ok=True); self.path.write_text(json.dumps(self.data))

# ---------------- model listing ----------------
NV_EXCLUDE = re.compile(r"embed|rerank|retriever|guard|safety|reward|parse|ocr|clip|dino|detect|asr|tts|whisper|"
                        r"parakeet|riva|flux|stable-diffusion|sdxl|cosmos|bge|pii|deplot|kosmos|paligemma|"
                        r"neva|vila|fuyu|grounding|segment|audio2|canary|nvclip|topic-control|content-safety|"
                        r"jailbreak|esm|alphafold|genmol|molmim|diffdock|vista|streampetr|ising|gliner|"
                        r"calibration|nemoguard|translate|usdcode|usdsearch|usdvalidate", re.I)
GQ_EXCLUDE = re.compile(r"whisper|tts|orpheus|playai|guard|safeguard|distil", re.I)
GM_EXCLUDE = re.compile(r"embed|imagen|veo|tts|image|live|aqa|robotics|computer-use|native-audio|audio|lyria|"
                        r"learnlm|-exp-\d{4}|nano-banana", re.I)

def list_models(name, key):
    cfg = PROVIDERS[name]; out = []
    if name == "openrouter":
        data = http_json(cfg["base"] + "/models", {"Authorization": "Bearer " + key})["data"]
        for m in data:
            pr = m.get("pricing") or {}
            free = m["id"].endswith(":free") or (str(pr.get("prompt")) in ("0", "0.0") and str(pr.get("completion")) in ("0", "0.0"))
            outmods = ((m.get("architecture") or {}).get("output_modalities")) or ["text"]
            if free and "text" in outmods and m["id"] != "openrouter/auto":
                out.append({"id": m["id"], "ctx": m.get("context_length") or 0, "created": m.get("created") or 0})
    elif name == "gemini":
        url = cfg["base"] + "/models?pageSize=1000"
        data = http_json(url, {"x-goog-api-key": key}).get("models", [])
        for m in data:
            mid = m["name"].split("/", 1)[-1]
            if "generateContent" in (m.get("supportedGenerationMethods") or []) and not GM_EXCLUDE.search(mid):
                out.append({"id": mid, "ctx": m.get("inputTokenLimit") or 0, "created": 0})
    elif name == "groq":
        data = http_json(cfg["base"] + "/models", {"Authorization": "Bearer " + key}).get("data", [])
        for m in data:
            if m.get("active", True) is not False and not GQ_EXCLUDE.search(m["id"]):
                out.append({"id": m["id"], "ctx": m.get("context_window") or 0, "created": m.get("created") or 0})
    elif name == "nvidia":
        data = http_json(cfg["base"] + "/models", {"Authorization": "Bearer " + key}).get("data", [])
        for m in data:
            if not NV_EXCLUDE.search(m["id"]):
                out.append({"id": m["id"], "ctx": 0, "created": m.get("created") or 0})
    for m in out:
        m["provider"] = name; m["quality"] = quality_score(m)
    return out

# ---------------- quality heuristic (Claude refines this with its own model knowledge) ----------------
FAMILY_BONUS = [  # (regex, bonus) — newer / frontier open-weight families first
    (r"gemini-3", 30), (r"gemini-2\.5-pro", 24), (r"gemini-2\.5-flash(?!-lite)", 14), (r"gemini-.*flash-lite", 6),
    (r"deepseek.*(v3|r1|v4)", 26), (r"kimi-k2|moonshot", 26), (r"qwen3.*(coder|235b|480b|max)", 26), (r"qwen3", 16),
    (r"glm-?[45]", 24), (r"gpt-oss-120b", 22), (r"gpt-oss", 14), (r"minimax", 20), (r"llama-?4", 16),
    (r"nemotron.*ultra", 22), (r"nemotron.*super", 18), (r"llama-3\.[13]-.*(405|70)b", 12), (r"compound", 18),
    (r"mistral-large|magistral|devstral|codestral", 16), (r"gemma-?3", 8), (r"hermes-?4", 14),
]
def quality_score(m):
    i = m["id"].lower(); s = 30.0
    for rx, b in FAMILY_BONUS:
        if re.search(rx, i): s += b; break
    sizes = [float(x) for x in re.findall(r"(?<![a-z])(\d+(?:\.\d+)?)b(?![a-z])", i)]
    if sizes: s += min(20, 6 * math.log10(max(sizes) + 1) * 1.6)
    if re.search(r"ultra|pro|large|max|maverick|opus", i): s += 6
    if re.search(r"mini|small|lite|nano|tiny|(?<![\d.])[1-4]b(?![a-z])", i): s -= 8
    if m.get("ctx", 0) >= 200_000: s += 4
    if re.search(r"preview|exp", i): s -= 1
    return round(max(0, min(100, s)), 1)

def tags_for(mid):
    i = mid.lower(); t = []
    if re.search(r"coder|code|devstral|codestral|kimi|glm|qwen3-coder|deepseek|gpt-oss|minimax", i): t.append("coding")
    if re.search(r"r1|reason|think|magistral|qwq|gpt-oss|gemini-(2\.5|3)|kimi-k2-thinking", i): t.append("reasoning")
    if re.search(r"vision|vl|-v\b|maverick|scout|gemini|gemma-3", i): t.append("vision")
    return t

# ---------------- one generation call (streaming, measures TTFT) ----------------
class RateLimited(Exception):
    def __init__(self, msg, retry_after=None, daily=False, zero=False):
        super().__init__(msg); self.retry_after = retry_after; self.daily = daily; self.zero = zero

def call_model(name, key, mid, timeout):
    cfg = PROVIDERS[name]; t0 = time.monotonic(); ttft = None; text = ""; out_tokens = None
    if name == "gemini":
        url = f"{cfg['base']}/models/{mid}:streamGenerateContent?alt=sse"
        body = {"contents": [{"role": "user", "parts": [{"text": PROMPT}]}],
                "generationConfig": {"maxOutputTokens": 1024, "temperature": 0}}
        headers = {"x-goog-api-key": key}
    else:
        url = cfg["base"] + "/chat/completions"
        body = {"model": mid, "messages": [{"role": "user", "content": PROMPT}], "max_tokens": 512,
                "temperature": 0, "stream": True}
        if name != "groq":
            body["stream_options"] = {"include_usage": True}
        headers = {"Authorization": "Bearer " + key}
        if name == "openrouter":
            headers.update({"HTTP-Referer": "https://github.com/free-llm-bench", "X-Title": "free-llm-bench"})
    try:
        resp = http("POST", url, headers, body, timeout=timeout)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")[:600]
        if e.code == 429:
            ra = e.headers.get("Retry-After")
            low = raw.lower()
            daily = bool(re.search(r"per.?day|perday|daily|free-models-per-day|rpd", low))
            zero = "limit: 0" in low or '"limit":0' in low.replace(" ", "")
            m = re.search(r'retrydelay"?\s*:\s*"(\d+)', low)
            raise RateLimited(raw, float(ra) if ra and ra.replace(".", "").isdigit() else (float(m.group(1)) if m else None), daily, zero)
        raise RuntimeError(f"HTTP {e.code}: {short_err(raw)}")
    rpd_left = resp.headers.get("x-ratelimit-remaining-requests") if name == "groq" else None
    with resp:
        for raw in resp:
            line = raw.decode(errors="ignore").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try: ev = json.loads(payload)
            except Exception: continue
            if isinstance(ev, dict) and ev.get("error"):
                raise RuntimeError("stream error: " + short_err(json.dumps(ev["error"])))
            piece = ""
            if name == "gemini":
                for c in ev.get("candidates") or []:
                    for p in ((c.get("content") or {}).get("parts") or []):
                        piece += p.get("text", "")
                um = ev.get("usageMetadata") or {}
                if um.get("candidatesTokenCount") is not None:
                    out_tokens = um.get("candidatesTokenCount", 0) + um.get("thoughtsTokenCount", 0)
            else:
                for c in ev.get("choices") or []:
                    d = c.get("delta") or {}
                    piece += (d.get("content") or "") + (d.get("reasoning") or d.get("reasoning_content") or "")
                usage = ev.get("usage") or (ev.get("x_groq") or {}).get("usage")
                if usage and usage.get("completion_tokens") is not None:
                    out_tokens = usage["completion_tokens"]
            if piece and ttft is None:
                ttft = time.monotonic() - t0
            text += piece
            if time.monotonic() - t0 > timeout:
                raise RuntimeError("timeout")
    total = time.monotonic() - t0
    if not text.strip():
        raise RuntimeError("empty response")
    if not out_tokens:
        out_tokens = max(1, len(text) // 4)
    gen_time = max(1e-3, total - (ttft or 0))
    return {"ttft": ttft or total, "total": total, "tps": out_tokens / gen_time, "correct": "ok" in text.lower()[:200],
            "rpd_left": int(rpd_left) if rpd_left and rpd_left.isdigit() else None}

def short_err(s):
    try:
        j = json.loads(s); j = j.get("error", j)
        s = j.get("message", s) if isinstance(j, dict) else s
    except Exception: pass
    return re.sub(r"\s+", " ", str(s))[:90]

# ---------------- benchmark runner (per provider, sequential + paced) ----------------
def openrouter_daily_remaining(key):
    try:
        d = http_json(PROVIDERS["openrouter"]["base"] + "/key", {"Authorization": "Bearer " + key}).get("data", {})
        f = d.get("free_model_daily_requests") or {}
        if f.get("remaining") is not None: return int(f["remaining"]), int(f.get("limit") or 0)
        limit = 50 if d.get("is_free_tier", True) else 1000
        return None, limit
    except Exception:
        return None, 50

def run_provider(name, key, args, ledger, log):
    cfg = PROVIDERS[name]; res = {"provider": name, "models": [], "notes": [], "requests": 0}
    try:
        models = list_models(name, key)
    except Exception as e:
        res["notes"].append(f"model listing failed: {e}"); return res
    res["listed"] = len(models)
    models.sort(key=lambda m: (-m["quality"], -m.get("created", 0)))
    if args.only:
        rx = re.compile(args.only, re.I); models = [m for m in models if rx.search(m["id"])]
    probes = args.probes or cfg["probes"]
    max_models = args.max_models or cfg["max_models"]

    # daily budget (spend at most a fraction of today's remaining free quota)
    if name == "openrouter":
        remaining, limit = openrouter_daily_remaining(key)
        if remaining is None: remaining = max(0, limit - ledger.used(name))
        budget = int(remaining * args.budget_fraction)
        res["notes"].append(f"free quota today: {remaining}/{limit} left -> using <= {budget}")
    else:
        budget = max(0, cfg["daily_budget"] - ledger.used(name))
    max_models = max(0, min(max_models, budget // max(1, probes)))
    if max_models == 0 and not args.list_only:
        res["notes"].append("daily safety budget exhausted - skipping generation tests")
    chosen = models[:max_models]
    for m in models:
        m.update({"tested": False, "ok": 0, "fail": 0, "lat": [], "ttft": [], "tps": [], "correct": 0, "err": ""})
    res["models"] = models
    if args.list_only or not chosen:
        return res

    last_global = [0.0]; last_model = {}; dead = set(); provider_stop = False
    def wait(mid):
        now = time.monotonic()
        t = max(last_global[0] + cfg["global_interval"], last_model.get(mid, 0) + cfg["model_interval"])
        if t > now: time.sleep(t - now)
    for rnd in range(probes):                       # round-robin: spreads repeats in time -> stability signal
        for m in chosen:
            mid = m["id"]
            if mid in dead or provider_stop: continue
            if res["requests"] >= budget: provider_stop = True; res["notes"].append("hit run budget"); break
            m["tested"] = True
            for attempt in range(2):
                wait(mid)
                last_global[0] = last_model[mid] = time.monotonic()
                res["requests"] += 1; ledger.add(name)
                try:
                    r = call_model(name, key, mid, args.timeout)
                    m["ok"] += 1; m["lat"].append(r["total"]); m["ttft"].append(r["ttft"]); m["tps"].append(r["tps"])
                    m["correct"] += r["correct"]; log(f"[{name}] {mid} #{rnd+1} ok {r['total']:.2f}s")
                    if r.get("rpd_left") is not None:
                        m["rpd_left"] = r["rpd_left"]
                        if r["rpd_left"] < 20:       # keep the model's remaining daily quota for real work
                            dead.add(mid); m["err"] = f"only {r['rpd_left']} req/day left - stopped"
                    break
                except RateLimited as e:
                    if e.zero:
                        m["err"] = "no free-tier quota"; dead.add(mid); m["fail"] += 1; break
                    if e.daily:
                        m["err"] = "daily limit reached"; m["fail"] += 1
                        if name == "openrouter": provider_stop = True
                        else: dead.add(mid)
                        break
                    delay = min(60, e.retry_after or 20)
                    log(f"[{name}] {mid} 429 -> backing off {delay:.0f}s")
                    if attempt == 0 and res["requests"] < budget:
                        time.sleep(delay); continue
                    m["fail"] += 1; m["err"] = "rate limited (429)"; break
                except Exception as e:
                    m["fail"] += 1; m["err"] = short_err(str(e))
                    log(f"[{name}] {mid} #{rnd+1} FAIL {m['err']}")
                    if re.search(r"HTTP (404|400|403|410|422)", m["err"]) or "not found" in m["err"].lower():
                        dead.add(mid)            # permanently unavailable -> don't waste quota
                    break
    if provider_stop and "hit run budget" not in res["notes"]:
        res["notes"].append("stopped early: provider daily free limit reached")
    return res

# ---------------- scoring, table, suggestions ----------------
def summarize(m):
    n = m["ok"] + m["fail"]
    m["success"] = m["ok"] / n if n else 0.0
    m["p50"] = statistics.median(m["lat"]) if m["lat"] else None
    m["ttft50"] = statistics.median(m["ttft"]) if m["ttft"] else None
    m["tps50"] = statistics.median(m["tps"]) if m["tps"] else None
    m["cv"] = (statistics.pstdev(m["lat"]) / statistics.mean(m["lat"])) if len(m["lat"]) >= 2 else None
    # stability: success rate penalised by latency jitter
    m["stability"] = round(100 * m["success"] * (1 - min(0.5, (m["cv"] or 0) / 2)), 0) if n else None
    m["tags"] = tags_for(m["id"])
    return m

def fmt(v, f="{:.0f}", d="-"): return d if v is None else f.format(v)

def table(rows):
    cols = ["Provider", "Model", "Qual", "Succ", "Stab", "TTFT ms", "p50 ms", "tok/s", "Tags", "Note"]
    data = []
    for m in rows:
        data.append([m["provider"], m["id"][:46], fmt(m["quality"]), f"{m['ok']}/{m['ok']+m['fail']}",
                     fmt(m["stability"]), fmt(m["ttft50"] and m["ttft50"] * 1000), fmt(m["p50"] and m["p50"] * 1000),
                     fmt(m["tps50"]), ",".join(m["tags"]), m["err"][:34]])
    w = [max(len(str(x)) for x in [c] + [r[i] for r in data]) for i, c in enumerate(cols)]
    line = "+" + "+".join("-" * (x + 2) for x in w) + "+"
    out = [line, "| " + " | ".join(c.ljust(w[i]) for i, c in enumerate(cols)) + " |", line]
    out += ["| " + " | ".join(str(c).ljust(w[i]) for i, c in enumerate(r)) + " |" for r in data]
    return "\n".join(out + [line])

def suggest(rows):
    good = [m for m in rows if m["tested"] and m["success"] >= 0.66 and m["ok"] >= 1]
    dev = sorted(good, key=lambda m: (-(m["quality"] + 0.15 * (m["stability"] or 0)), m["p50"] or 99))[:5]
    def test_score(m):  # fast, stable, cheap on quota
        quota = 1.0 if m["provider"] in ("nvidia", "groq") else (0.9 if re.search(r"flash|lite|gemma", m["id"]) else 0.6)
        return (m["stability"] or 0) / 100 * quota * (1 / max(0.3, m["p50"] or 10)) * (1 + (m["tps50"] or 0) / 200)
    test = sorted(good, key=lambda m: -test_score(m))[:5]
    coding = [m for m in dev + sorted(good, key=lambda m: -m["quality"]) if "coding" in m["tags"]]
    seen = set(); coding = [m for m in coding if not (m["id"] in seen or seen.add(m["id"]))][:3]
    return dev, test, coding

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--providers", help="comma list: nvidia,gemini,groq,openrouter (default: inferred from env keys)")
    ap.add_argument("--probes", type=int, help="requests per model (default per provider: nvidia 3, gemini 3, groq 3, openrouter 2)")
    ap.add_argument("--max-models", type=int, help="max models tested per provider (top by quality heuristic)")
    ap.add_argument("--only", help="regex filter on model ids")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--budget-fraction", type=float, default=0.4, help="OpenRouter: share of today's remaining free requests to spend")
    ap.add_argument("--list-only", action="store_true", help="list free models only, no generation calls")
    ap.add_argument("--show-untested", action="store_true", help="include untested models in table")
    ap.add_argument("--json", help="write full results JSON here (also saved to cache dir)")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()
    load_dotenv()

    if args.providers:
        names = [x.strip().lower().replace("open-router", "openrouter").replace("google", "gemini").replace("nim", "nvidia")
                 for x in args.providers.split(",") if x.strip()]
    else:
        names = [n for n in PROVIDERS if get_key(n)]
    bad = [n for n in names if n not in PROVIDERS]
    if bad: sys.exit(f"Unknown provider(s): {bad}. Use nvidia, gemini, groq, openrouter.")
    missing = [n for n in names if not get_key(n)]
    for n in missing:
        print(f"! {n}: no key found in env ({' / '.join(PROVIDERS[n]['env'])}) - skipping", file=sys.stderr)
    names = [n for n in names if get_key(n)]
    if not names: sys.exit("No provider API keys found. Set NVIDIA_API_KEY, GEMINI_API_KEY, GROQ_API_KEY and/or OPENROUTER_API_KEY.")

    ledger = Ledger(); lock = threading.Lock()
    def log(s):
        if not args.quiet:
            with lock: print(s, file=sys.stderr, flush=True)
    print(f"free-llm-bench {VERSION} | providers: {', '.join(names)} | testing in parallel across providers, paced within each",
          file=sys.stderr)
    results = {}
    threads = [threading.Thread(target=lambda n=n: results.__setitem__(n, run_provider(n, get_key(n), args, ledger, log)))
               for n in names]
    for t in threads: t.start()
    for t in threads: t.join()

    rows = []
    for n in names:
        r = results.get(n, {"models": [], "notes": ["crashed"]})
        for m in r["models"]: summarize(m)
        rows += r["models"]
    shown = [m for m in rows if m["tested"] or args.list_only or args.show_untested]
    shown.sort(key=lambda m: (not m["tested"], -(m["success"] if m["tested"] else 0), -m["quality"]))

    print(f"\n## Free models ({'listed' if args.list_only else 'tested'})\n")
    print(table(shown))
    print("\nQual = heuristic quality 0-100 | Succ = ok/attempts | Stab = success x low latency jitter (0-100)")
    print("TTFT = median time to first token | p50 = median total latency | tok/s = median output speed\n")
    for n in names:
        r = results.get(n, {})
        print(f"- {n}: listed {r.get('listed', 0)}, tested {sum(m['tested'] for m in r.get('models', []))}, "
              f"requests used {r.get('requests', 0)}" + ("; " + "; ".join(r["notes"]) if r.get("notes") else ""))

    if not args.list_only:
        dev, test, coding = suggest(rows)
        def lst(title, ms):
            print(f"\n### {title}")
            if not ms: print("  (none passed - try again later or raise --max-models)")
            for i, m in enumerate(ms, 1):
                print(f"  {i}. {m['provider']}:{m['id']}  (qual {m['quality']:.0f}, stab {fmt(m['stability'])}, "
                      f"p50 {fmt(m['p50'] and m['p50']*1000)} ms, {fmt(m['tps50'])} tok/s)")
        lst("Suggested for DEVELOPMENT (best quality that is reliably available)", dev)
        lst("Suggested for TESTING / CI (fast, stable, quota-friendly)", test)
        lst("Suggested for CODING agents", coding)

    CACHE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = {"version": VERSION, "time": stamp, "providers": {n: {k: v for k, v in results[n].items() if k != "models"} for n in results},
               "models": rows}
    for p in filter(None, [args.json, str(CACHE / f"results-{stamp}.json"), str(CACHE / "latest.json")]):
        pathlib.Path(p).write_text(json.dumps(payload, indent=1, default=str))
    print(f"\nFull results: {CACHE / 'latest.json'}")

if __name__ == "__main__":
    main()
```
