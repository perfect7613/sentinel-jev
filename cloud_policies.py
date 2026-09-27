"""Pull the pinned Cloud assignment for this logical Modal service.

This is a serverless application reconciler, not a system failproofaid daemon.
A request pins one verified snapshot. A failed refresh stops new unchecked work.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import httpx

_lock = asyncio.Lock()
_cached = None
_checked_at = 0.0
_highest_deployment = -1
_applied_snapshot = None
TTL_SECONDS = 5
MAX_BYTES = 65536


def validate_state(state):
    if not isinstance(state, dict) or state.get("schemaVersion") != 2:
        raise ValueError("Unsupported Cloud desired-state schema")
    deployment = state.get("deployment")
    if isinstance(deployment, bool) or not isinstance(deployment, int) or deployment < 1:
        raise ValueError("No Cloud deployment assigned")
    policies = state.get("policies")
    if not isinstance(policies, list) or len(policies) != 1:
        raise ValueError("Sentinel requires exactly its own policy bundle")
    policy = policies[0]
    if policy.get("id") != "sentinel-jev" or policy.get("effect") not in {"observe", "enforce"}:
        raise ValueError("Unexpected Cloud policy assignment")
    version = policy.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("Invalid Cloud policy version")
    digest = policy.get("sha256", "")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid policy digest")
    if policy.get("artifactUrl") != "/enforcement/v1/artifacts/" + digest:
        raise ValueError("Unexpected policy artifact location")
    return {"deployment": deployment, **policy}


def verify_source(content, digest):
    if not content or len(content) > MAX_BYTES or hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("Cloud policy failed size/integrity verification")
    content.decode("utf-8")


async def snapshot(*, force=False):
    global _cached, _checked_at, _highest_deployment
    token = os.getenv("FAILPROOFAI_POLICY_TOKEN")
    if not token:
        if os.getenv("SENTINEL_REQUIRE_CLOUD_POLICY") == "1":
            raise RuntimeError("Required policy-pull credential is missing")
        return None
    async with _lock:
        if not force and _cached and time.monotonic() - _checked_at < TTL_SECONDS:
            verify_source(Path(_cached["path"]).read_bytes(), _cached["sha256"])
            return _cached.copy()
        base = os.environ["FAILPROOFAI_CLOUD_URL"].rstrip("/")
        parsed = urlsplit(base)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Cloud policy origin must use HTTPS")
        headers = {"Authorization": "Bearer " + token}
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            params = {"machineId": os.environ["FAILPROOFAI_MACHINE_ID"],
                      "label": os.getenv("FAILPROOFAI_MACHINE_LABEL", "sentinel-modal")}
            if _applied_snapshot:
                verify_source(Path(_applied_snapshot["path"]).read_bytes(), _applied_snapshot["sha256"])
                params["appliedDeployment"] = str(_applied_snapshot["deployment"])
            response = await client.get(base + "/enforcement/v1/desired-state", params=params, headers=headers)
            response.raise_for_status()
            selected = validate_state(response.json())
            if selected["deployment"] < _highest_deployment:
                raise ValueError("Cloud deployment moved backwards")
            _highest_deployment = selected["deployment"]
            directory = Path(os.getenv("SENTINEL_POLICY_CACHE", "/tmp/sentinel-cloud-policies"))
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            path = directory / (selected["sha256"] + ".mjs")
            if path.exists():
                content = path.read_bytes()
            else:
                artifact = await client.get(base + selected["artifactUrl"], headers=headers)
                artifact.raise_for_status()
                content = artifact.content
            verify_source(content, selected["sha256"])
            if not path.exists():
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(content)
                temporary.chmod(0o600)
                temporary.replace(path)
        _cached = {**{k: selected[k] for k in ("id", "version", "effect", "deployment", "sha256")},
                   "path": str(path), "machine_id": os.environ["FAILPROOFAI_MACHINE_ID"]}
        _checked_at = time.monotonic()
        return _cached.copy()


def public_metadata(value):
    return {k: v for k, v in (value or {}).items() if k != "path"}


def runtime_environment(value):
    # Policy source is trusted administrative code, but needs no service secrets.
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "NODE_PATH", "SENTINEL_WORKSPACE"}}
    if value:
        env.update(SENTINEL_POLICY_PATH=value["path"], SENTINEL_POLICY_METADATA=json.dumps(public_metadata(value)))
    return env


def mark_evaluated(value, result):
    """Report only a verified version that actually executed without adapter failure."""
    global _applied_snapshot
    observed = result.get("observed", [])
    if (not value or result.get("error") or any(v.get("error") for v in observed)
            or result.get("cloud_policy", {}).get("sha256") != value["sha256"]):
        return
    if _applied_snapshot is None or value["deployment"] >= _applied_snapshot["deployment"]:
        _applied_snapshot = value.copy()


def last_evaluated_deployment():
    return _applied_snapshot["deployment"] if _applied_snapshot else None


def enforcement_scope(value):
    if not value:
        return "application-bundled"
    return "cloud-managed-application" if value["effect"] == "enforce" else "bundled-with-cloud-observation"
