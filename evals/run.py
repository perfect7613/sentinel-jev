"""Small, predeclared synthetic pipeline eval. No external dataset or production traces."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from client import request


def check(case, result):
    text=result['response'].casefold()
    rules={'expected_route':result['route'] in case['expected_routes'],
           'required_text':all(x.casefold() in text for x in case.get('must_include',[])),
           'excluded_text':all(x.casefold() not in text for x in case.get('must_not_include',[])),
           'telemetry_delivered':result['telemetry']['status']=='accepted'}
    return {**rules,'pass':all(rules.values())}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,default=Path(__file__).parent/'results'/'pilot.json')
    parser.add_argument('--alpha',type=float,default=.08)
    args=parser.parse_args()
    cases_path=Path(__file__).with_name('cases.json');cases=json.loads(cases_path.read_text())
    artifact=request('/steering')
    if artifact.get('backend')!='steering-vectors==0.12.2': raise RuntimeError('Unexpected steering backend')
    report={'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'cases_sha256':hashlib.sha256(cases_path.read_bytes()).hexdigest(),
            'model':artifact,'alpha':args.alpha,'seed':42,'max_tokens':160,
            'methodology':'12 predeclared synthetic cases; baseline first; input judgment reused; independent output judgments; pipeline checks, not a safety benchmark.',
            'runs':[]}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    for case in cases:
        body={'messages':[{'role':'user','content':case['prompt']}],'max_tokens':160,'steering_alpha':args.alpha}
        if 'document' in case: body.update(agent='document-assistant',document=case['document'])
        started=time.monotonic()
        result=request('/experiment',body)
        entry={'id':case['id'],'category':case['category'],'elapsed_s':round(time.monotonic()-started,3),'experiment_id':result['experiment_id']}
        for arm in ['baseline','steered']:
            value=result[arm]
            # Publish only the synthetic request's released response and scores.
            entry[arm]={k:value.get(k) for k in ['session_id','route','response','input_judgment','input_judgment_reused','output_judgment','activation_steering_applied','steering','telemetry']}
            entry[arm]['checks']=check(case,value)
        report['runs'].append(entry)
        args.out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
        print(case['id'],{a:entry[a]['checks']['pass'] for a in ['baseline','steered']},flush=True)
    report['completed_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    report['summary']={arm:{'passed':sum(r[arm]['checks']['pass'] for r in report['runs']),
                            'total':len(cases),'steering_applied':sum(r[arm]['activation_steering_applied'] for r in report['runs']),
                            'refused':sum(r[arm]['route']=='REFUSE' for r in report['runs'])} for arm in ['baseline','steered']}
    args.out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(report['summary']),flush=True)

if __name__=='__main__':main()
