import asyncio, os, re, subprocess, time
from pathlib import Path
import httpx
from langgraph_sdk import get_client
RC = Path("/var/tmp/neuron-rc")
(RC / ".env").write_text("APP_ENV=development\nAPP_AUTH_MODE=none\nOPENAI_API_KEY=\n")
env = {k: v for k, v in os.environ.items() if not k.startswith("APP_") and "OPENAI" not in k}
log = Path("/var/tmp/gate/langgraph-studio.log")
server = subprocess.Popen(["uv", "run", "langgraph", "dev", "--no-browser", "--no-reload"], cwd=RC, env=env, stdout=log.open("wb"), stderr=subprocess.STDOUT)
try:
    url = None
    for _ in range(180):
        m = re.search(r"API: \S*?(http://127\.0\.0\.1:\d+)", log.read_text(errors="replace"))
        if m:
            try:
                if httpx.get(f"{m.group(1)}/ok").status_code == 200:
                    url = m.group(1); break
            except httpx.TransportError:
                pass
        time.sleep(1)
    async def go():
        client = get_client(url=url)
        thread = await client.threads.create()
        result = await client.runs.wait(thread["thread_id"], "main", input={"messages": [{"role": "user", "content": "hi"}]})
        print("[PASS]" if "answer" in result else "[FAIL]", "Studio identity (APP_AUTH_MODE=none) run:", thread["metadata"].get("owner"), result.get("answer", {}).get("answer"))
    asyncio.run(go())
finally:
    server.terminate(); server.wait(timeout=30)
    (RC / ".env").unlink()
