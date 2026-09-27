"""Private GPU verification; no unsafe prompts and no unchecked public endpoint."""
import json
from pathlib import Path
import modal
model=modal.Cls.from_name('sentinel-model','Gemma')()
messages=[{'role':'user','content':'Explain why leaves look green in one sentence.'}]
results=[model.generate.remote(messages,max_tokens=64,steering_alpha=a) for a in (0,.08,0)]
assert results[0]['content']==results[2]['content'], 'Steering leaked into subsequent baseline'
assert results[0]['steering']['hook_calls']==results[2]['steering']['hook_calls']==0
assert results[1]['steering']['hook_calls']>0
assert .075 < results[1]['steering']['mean_relative_delta'] < .085
assert results[1]['activation_steering_applied']
Path('results').mkdir(exist_ok=True)
Path('results/hook-verification.json').write_text(json.dumps(results,indent=2))
print(json.dumps({'baseline_reproducible':True,'no_hook_leakage':True,'hook_calls':results[1]['steering']['hook_calls'],'relative_delta':results[1]['steering']['mean_relative_delta'],'gpu':results[1]['gpu']}))
