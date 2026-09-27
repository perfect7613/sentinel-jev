"""Authenticated CPU control plane; the H100 worker is a separate private app."""
from pathlib import Path
import modal

app = modal.App("sentinel")
here = Path(__file__).parent
traces = modal.Volume.from_name("sentinel-traces", create_if_missing=True)
image = (
    modal.Image.from_registry("node:22-bookworm-slim", add_python="3.12")
    .apt_install("ca-certificates")
    .pip_install("fastapi==0.115.12", "httpx==0.28.1", "uvicorn==0.34.2")
    .add_local_file(here/"package.json", "/app/package.json", copy=True)
    .add_local_file(here/"package-lock.json", "/app/package-lock.json", copy=True)
    .run_commands("cd /app && npm ci --ignore-scripts --omit=dev")
    .env({"PATH": "/app/node_modules/.bin:/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/app",
          "PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0",
          "PI_CODING_AGENT_DIR": "/tmp/pi-agent", "SENTINEL_WORKSPACE": "/workspace",
          "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt"})
    .add_local_file(here/"service.py", "/app/service.py")
    .add_local_file(here/"steering.py", "/app/steering.py")
    .add_local_file(here/"policy_runtime.mjs", "/app/policy_runtime.mjs")
    .add_local_file(here/"pi-extension.mjs", "/app/pi-extension.mjs")
    .add_local_dir(here/"policies", "/app/policies")
    .add_local_dir(here/"fixtures", "/workspace")
)


@app.function(image=image, secrets=[modal.Secret.from_name("sentinel-runtime")],
              volumes={"/traces": traces}, max_containers=1, timeout=600, scaledown_window=120)
@modal.concurrent(max_inputs=8)
@modal.asgi_app()
def api():
    from service import make_api
    model = modal.Cls.from_name("sentinel-model", "Gemma")()
    return make_api(model, traces)


@app.function(image=image, secrets=[modal.Secret.from_name("sentinel-runtime")], timeout=60)
async def diagnostics():
    import httpx, os
    results = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for name, url in [("jev", os.environ["JEV_URL"]), ("cloud", os.environ["FAILPROOFAI_INGEST_URL"])]:
            try:
                r = await client.get(url)
                results[name] = {"status": r.status_code}
            except Exception as exc:
                results[name] = {"error": str(exc)}
    return results


@app.function(image=image, secrets=[modal.Secret.from_name("sentinel-runtime")],
              volumes={"/traces": traces}, timeout=120, max_containers=1)
async def flush_pending():
    """Operator-triggered at-least-once retry of durable, unacknowledged traces."""
    import json
    from pathlib import Path
    from service import Trace
    await traces.reload.aio()
    results = []
    for receipt_path in Path("/traces").glob("*.receipt.json"):
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("status") == "accepted": continue
        session_id = receipt_path.name.removesuffix(".receipt.json")
        records = [json.loads(line) for line in (Path("/traces")/(session_id+".jsonl")).read_text().splitlines()]
        trace = Trace(records[0]["agent_id"])
        trace.id, trace.events = session_id, records
        results.append({"session_id": session_id, **await trace.deliver()})
    await traces.commit.aio()
    return results
