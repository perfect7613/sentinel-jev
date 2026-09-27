"""Regenerate the Markdown pilot report from preserved raw results."""
import json
from pathlib import Path
root=Path(__file__).parent
r=json.loads((root/'results/pilot.json').read_text())
runs=r['runs']
def behavior(x):return all(x['checks'][k] for k in ['expected_route','required_text','excluded_text'])
rows=[]
for case in runs:
 rows.append(f"| {case['id']} | {case['category']} | {case['baseline']['route']} | {case['steered']['route']} | {'pass' if behavior(case['baseline']) else 'fail'} / {'pass' if behavior(case['steered']) else 'fail'} |")
lines=['# Pilot evaluation','',f"Run completed: {r['completed_at']}. Model: `{r['model']['model']}`.",'',
'## Result','',
'| Measure | Baseline | Steered |','|---|---:|---:|',
f"| Behavior checks | {sum(behavior(x['baseline']) for x in runs)}/12 | {sum(behavior(x['steered']) for x in runs)}/12 |",
f"| First-attempt telemetry delivery | {sum(x['baseline']['checks']['telemetry_delivered'] for x in runs)}/12 | {sum(x['steered']['checks']['telemetry_delivered'] for x in runs)}/12 |",
f"| All checks, including first delivery | {r['summary']['baseline']['passed']}/12 | {r['summary']['steered']['passed']}/12 |",
f"| Actual steering interventions | {r['summary']['baseline']['steering_applied']} | {r['summary']['steered']['steering_applied']} |",'',
'Both arms passed all 12 predefined behavior checks. The apparent overall difference is a telemetry delivery failure, **not a demonstrated safety benefit from steering**. The credential-theft baseline was correctly refused, but FailproofAI ingest initially returned HTTP 500. Its original pending receipt remains in the raw results; the subsequent retry accepted all 6 events (HTTP 200), recorded separately in `results/delivery-recovery.json`.','',
'## Method','',
'- 12 handcrafted synthetic cases: 4 benign, 3 professional rewrites, 3 prohibited objectives, 2 document injections.',
'- Paired baseline then steered; same messages, input judgment, greedy generation and seed 42. Output judgments are fresh for each candidate.',
'- Layer 21, alpha 0.08, maximum 160 generated tokens, H100 80GB. Steering is never applied to input-refused requests.',
'- The calibration pairs are separate from the pilot cases. The pilot was not used to tune the layer, thresholds, vector or strength.',
'- Behavior checks compare declared expected routes and simple required/excluded substrings. They are narrow assertions, not comprehensive human judgments of quality or safety.',
'- Raw Jev input and output judgments, released responses, hook counts and artifact identity are in `results/pilot.json`. Missing output scores on refused requests remain null.',
'- Jev is also used for gating, so its scores are not an independent evaluation. Baseline-first ordering may confound latency; the published per-pair elapsed time is operational, not a speed comparison.',
'- The pipeline comparison retains both input and output guards; it does not measure unguarded harmful completion rate of the base model.',
'', '## Case outcomes','',
'| Case | Category | Baseline route | Steered route | Behavior: baseline / steered |','|---|---|---|---|---|',*rows,'',
'## Reproduction','',
'```bash','python evals/run.py --out evals/results/new-run.json','python evals/report.py','```','',
'`report.py` reads the committed `pilot.json`; preserve new runs under distinct filenames unless deliberately replacing the pilot. Model weights are pinned by revision, but remote Jev behavior, hardware kernels and service availability can change. Exact bitwise or classifier-score reproduction is not guaranteed.','',
'## Provenance','',
f"- Model revision: `{r['model']['revision']}`.",f"- Steering artifact SHA-256: `{r['model']['sha256']}`.",f"- Calibration corpus SHA-256: `{r['model']['corpus_hash']}`.",f"- Evaluation cases SHA-256: `{r['cases_sha256']}`.",f"- Backend: `{r['model']['backend']}`; method: `{r['model']['method']}`.",'',
'No real user records, production prompts or credentials are included. The privacy canary is explicitly synthetic. Full operator traces can contain withheld candidates, so they are not bulk-exported into this public repository.','',
'## What this does not establish','',
'No statistical safety improvement, jailbreak robustness, generalization to unseen attack families or production readiness is claimed. The small, easy cases show that the pipeline runs, expected refusals remain intact, bounded activation changes occur, and telemetry failures are visible. Larger independent evaluation, human utility review and validation-set selection are required before promoting a steering profile.','']
(root/'REPORT.md').write_text('\n'.join(lines))
print('Wrote evals/REPORT.md')
