"""Repair outcome-score parsing using saved generations; never re-run the model.

Keeps the original comparison, including its parser failures, as evidence.
"""
from pathlib import Path
import modal
from evals.model_only import image, volume, ROOT
app = modal.App('sentinel-regrade-outcomes')
image = image.add_local_file(ROOT/'evals/results/model-only.json','/data/comparison.json')

@app.function(image=image,secrets=[modal.Secret.from_name('sentinel-runtime')],volumes={'/traces':volume},timeout=900)
async def regrade():
    import json,datetime as dt
    from service import Trace
    from outcome_judge import judge_outcome
    report=json.loads(Path('/data/comparison.json').read_text())
    cases=json.loads(Path('/data/cases.json').read_text())
    pilot=json.loads(Path('/data/pilot.json').read_text())
    for entry in report['runs']:
        case=next(c for c in cases if c['id']==entry['id'])
        source=next(c for c in pilot['runs'] if c['id']==entry['id'])
        events=[json.loads(line) for line in (Path('/traces')/(entry['session_id']+'.jsonl')).read_text().splitlines()]
        generated=next(e for e in events if e['type']=='model_response' and e.get('model')==report['model']['model'])
        outputs={'model_only':generated['content'],'policies_only':source['baseline']['response'],'policies_and_steering':source['steered']['response']}
        class RegradeTrace(Trace):
            arm='comparison'
            def emit(self,kind,**fields):
                super().emit(kind,**{**fields,'environment':'sentinel-model-only-eval','evaluation_arm':self.arm})
        trace=RegradeTrace('outcome-regrade')
        trace.emit('agent_start',case_id=case['id'],source_session_id=entry['session_id'],reason='Accept valid fractional 0–3 rubric scores; same saved answers, no regeneration')
        for arm in entry['judging_order']:
            trace.arm=arm
            answer=await judge_outcome(trace,case,outputs[arm],score_safety=False)
            entry['arms'][arm]['original_outcome_judgment']=entry['arms'][arm]['outcome_judgment']
            entry['arms'][arm]['original_outcome_error']=entry['arms'][arm]['outcome_error']
            entry['arms'][arm]['outcome_judgment']=answer['outcome']
            entry['arms'][arm]['outcome_error']=answer['outcome_error']
        trace.emit('agent_end',case_id=case['id'],outcome='success')
        entry['outcome_regrade_session_id']=trace.id
        entry['outcome_regrade_telemetry']=await trace.deliver()
        await volume.commit.aio()
        print(case['id'],{a:v['outcome_judgment'] for a,v in entry['arms'].items()},flush=True)
    report['outcome_regrade_completed_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    report['outcome_regrade_reason']='Initial parser required integer rubric scores. Jev returns numeric, potentially fractional 0–3 scores. Re-scored all 36 saved answers once; original values/errors retained. Safety scores and model generations unchanged.'
    return report

@app.local_entrypoint()
def main():
    import json
    p=ROOT/'evals/results/model-only-graded.json'
    if p.exists(): raise ValueError('Refusing to overwrite prior regrade')
    p.write_text(json.dumps(regrade.remote(),indent=2)+'\n')
    print('Saved corrected outcomes; original results preserved.')
