"""Private one-off model-only ablation plus common post-generation scoring.

Run: uv run modal run evals/model_only.py
No web endpoint; deployed policy enforcement is untouched.
"""
from pathlib import Path
import modal

ROOT = Path(__file__).resolve().parents[1]
app = modal.App("sentinel-model-only-evaluation")
volume = modal.Volume.from_name("sentinel-traces")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("httpx==0.28.1")
    .add_local_file(ROOT / "service.py", "/root/service.py")
    .add_local_file(ROOT / "evals/comparison_metrics.py", "/root/comparison_metrics.py")
    .add_local_file(ROOT / "evals/outcome_judge.py", "/root/outcome_judge.py")
    .add_local_file(ROOT / "evals/cases.json", "/data/cases.json")
    .add_local_file(ROOT / "evals/results/pilot.json", "/data/pilot.json")
    .add_local_file(ROOT / "evals/MODEL_ONLY_PROTOCOL.md", "/data/protocol.md")
)


@app.function(image=image, secrets=[modal.Secret.from_name("sentinel-runtime")],
              volumes={"/traces": volume}, timeout=1800, max_containers=1)
async def compare():
    import datetime as dt
    import hashlib
    import json
    from service import Trace, SYSTEM
    from outcome_judge import judge_outcome
    from comparison_metrics import public_answer

    class EvalTrace(Trace):
        arm = "model_only"

        def emit(self, kind, **fields):
            super().emit(kind, **{**fields, "environment": "sentinel-model-only-eval",
                                 "evaluation_arm": self.arm})

    cases_bytes = Path("/data/cases.json").read_bytes()
    cases = json.loads(cases_bytes)
    pilot_bytes = Path("/data/pilot.json").read_bytes()
    pilot = json.loads(pilot_bytes)
    assert hashlib.sha256(cases_bytes).hexdigest() == pilot["cases_sha256"]
    model = modal.Cls.from_name("sentinel-model", "Gemma")()
    identity = await model.steering_status.remote.aio()
    assert identity["revision"] == pilot["model"]["revision"]
    report = {
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "protocol_sha256": hashlib.sha256(Path("/data/protocol.md").read_bytes()).hexdigest(),
        "cases_sha256": pilot["cases_sha256"], "source_pilot_sha256": hashlib.sha256(pilot_bytes).hexdigest(),
        "model": identity, "seed": 42, "max_tokens": 160, "temperature": 0,
        "steering_alpha": 0, "shared_system": SYSTEM,
        "source_pilot_completed_at": pilot["completed_at"], "runs": [],
        "judging": "Fresh post-generation Jev scoring of all three arms; order rotated across cases; no generation feedback.",
        "generation": "One new model-only generation per case; guarded answers reused from the original pilot.",
    }
    report_path = Path("/traces") / ("model-only-comparison-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S") + ".json")
    for index, case in enumerate(cases):
        source = next(c for c in pilot["runs"] if c["id"] == case["id"])
        trace = EvalTrace("model-only-eval")
        trace.emit("agent_start", goal=case["prompt"], case_id=case["id"],
                   policies_enabled=False, steering_enabled=False, enforcement_scope="none-evaluation")
        state = {"conversation": [{"role": "user", "content": case["prompt"]}]}
        text = case["prompt"]
        if "document" in case:
            state["untrusted_document"] = case["document"]
            text += "\n\nUNTRUSTED DOCUMENT:\n" + case["document"]
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]
        entry = {"id": case["id"], "category": case["category"], "session_id": trace.id, "arms": {}}
        outputs = {"policies_only": source["baseline"]["response"], "policies_and_steering": source["steered"]["response"]}
        try:
            trace.emit("model_request", model=identity["model"], messages=messages, max_tokens=160, seed=42, steering_alpha=0)
            generated = await model.generate.remote.aio(messages, max_tokens=160, seed=42, temperature=0, steering_alpha=0)
            assert generated["revision"] == identity["revision"]
            assert not generated["activation_steering_applied"]
            assert generated["steering"]["hook_calls"] == 0 and generated["steering"]["alpha"] == 0
            trace.emit("model_response", **generated)
            outputs["model_only"] = generated["content"]
            entry["generation"] = {k: v for k, v in generated.items() if k != "content"}
            entry["generation"]["reached_token_cap"] = generated["output_tokens"] >= 160
        except Exception as exc:
            entry["generation_error"] = type(exc).__name__
            trace.emit("error", error_type=type(exc).__name__, message="Model-only generation failed; no generation retry.")
        arms = ["model_only", "policies_only", "policies_and_steering"]
        order = arms[index % 3:] + arms[:index % 3]
        entry["judging_order"] = order
        for arm in order:
            if arm not in outputs:
                entry["arms"][arm] = {"output_judgment": None, "judge_flagged": None, "error": "generation_failed"}
                continue
            trace.arm = arm
            scored = await judge_outcome(trace, case, outputs[arm])
            entry["arms"][arm] = {
                **public_answer(case, outputs[arm], scored["safety"]),
                "judge_error": scored["safety_error"],
                "outcome_judgment": scored["outcome"], "outcome_error": scored["outcome_error"],
            }
            if arm != "model_only":
                original = source["baseline" if arm == "policies_only" else "steered"]
                entry["arms"][arm]["source_session_id"] = original["session_id"]
                entry["arms"][arm]["source_route"] = original["route"]
        trace.arm = "comparison"
        trace.emit("agent_end", outcome="success" if "generation_error" not in entry else "failed",
                   case_id=case["id"], enforcement_scope="none-evaluation",
                   judge_flags={a: v["judge_flagged"] for a, v in entry["arms"].items()})
        assert not any(e["type"] in {"hook_triggered", "hook_completed"} for e in trace.events)
        entry["telemetry"] = await trace.deliver()
        report["runs"].append(entry)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        await volume.commit.aio()
        print(case["id"], {a: v["judge_flagged"] for a, v in entry["arms"].items()}, flush=True)
    report["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    await volume.commit.aio()
    return report


@app.local_entrypoint()
def main(out: str = "evals/results/model-only.json"):
    import json
    path = ROOT / out
    if path.exists():
        raise ValueError("Choose a new output filename; existing evaluations are never overwritten.")
    result = compare.remote()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Saved public-safe results to {path}")
