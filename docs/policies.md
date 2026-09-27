# Policies, probabilities and enforcement

Jev reads the request and returns raw `noul` values between 0 and 1. Our JavaScript policies validate those numbers and make decisions. The values are classifier judgments; they are not empirically calibrated probabilities on this demo's corpus.

| Policy | Trigger | Decision |
|---|---|---|
| `jev-input-safety` | UserPromptSubmit | Prohibited ≥0.70 → refuse; missing_context ≥0.70 → clarify; safe_reframing ≥0.60 → redirect; otherwise allow. |
| `jev-response-release` | PreToolUse: PublishResponse | Withhold if any of harmful/private_data/injection_followed ≥0.50. The controller tries one revision. |
| `tool-boundary` | PreToolUse | Permit defined application actions and Pi reads whose resolved real path lies inside `/workspace`; deny shell, writes and outside reads. |
| `activation-steering-boundary` | PreToolUse: ApplyActivationSteering | Require valid input scores, approved route, allowed mode and 0 < alpha ≤0.12. Never override a refusal. |

Missing/invalid judgments, required-policy absence, policy exceptions and timeouts fail closed. The evaluator combines decisions as deny > instruct > allow. An allow from the generic tool boundary does not override a deny from the response or steering policy.

`CLARIFY:` and `REDIRECT:` are conventions interpreted by our controller, not native commands that automatically modify a model. `PublishResponse`, `ReadDocument`, and `ApplyActivationSteering` are application actions.

## FailproofAI surfaces

- **Sessions / Events / Hooks:** receive lifecycle, model/Jev calls, decisions and tool events from Modal.
- **Analyze → Dashboards:** saved SQL queries expose raw input/output scores, individual policy names and reasons, decision counts, activation metadata and latency.
- **Admin → Enforcement:** native enrolled machines and assigned/reported Cloud deployments. This project does **not** implement native fleet enrollment. Its policies are bundled and enforced by the application dispatcher.

The dashboard's `application-enforced` label describes the custom dispatcher, not a native machine deployment. Enrollment and publishing a Cloud policy are separate operations; copying a machine UUID or emitting a session does not enroll a workload.

## Transport

The npm `failproofai` registry supplies policy registration and verdict helpers. The Python/TypeScript observability SDKs normally spool events to files for a collector. This serverless integration instead writes durable JSONL and sends the documented NDJSON ingest format directly, validating `accepted` and `skipped` counts. It does not claim to run a system daemon inside Modal.

`flush_pending` provides operator-triggered retries. Delivery is at least once; a lost acknowledgement can cause duplicates. Session and hook counts use distinct IDs; raw event latency aggregates may include retried events. Requests rejected before session creation, including unauthenticated calls, are not application sessions.

## Dashboard setup

`uv run cloud_dashboard.py` validates SQL, creates or updates this project's saved queries, and adds missing tiles to `sentinel-tracking`. It uses the existing local FailproofAI Cloud credential. Set `FP_API_KEY`, `FP_ORG` and `FP_DASHBOARD_URL` to use explicit operator settings. It does not copy the administrative credential to Modal. Only the ingest key goes into the runtime secret.

Raw-score queries require the score's JSON key to exist before displaying it. Missing classification is not displayed as a zero. Historical traces may have fewer fields. All queries cover the last 24 hours of the `sentinel-modal` environment.
