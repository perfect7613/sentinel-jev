"""Populate the existing FailproofAI dashboard with validated Sentinel queries.
Uses the operator's existing Cloud key locally; never copies it to Modal.
"""
import json
import os
from pathlib import Path
import urllib.request
import urllib.error

BASE = os.getenv("FP_DASHBOARD_URL", "https://app.befailproof.ai").rstrip("/") + "/v1"
ORG = os.getenv("FP_ORG", "amey")

def api(path, body=None, method=None):
    token=os.getenv("FP_API_KEY")
    if not token:
        creds=json.loads((Path.home()/".failproofai/credentials.json").read_text())
        token=creds["cloud"]["token"]
    request=urllib.request.Request(BASE+path,method=method,data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization":"Bearer "+token,"X-AgentEye-Org":ORG,"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Cloud HTTP {exc.code}: {exc.read().decode()[:800]}") from None

DASHBOARD_NAME = "sentinel-tracking"
QUERIES = [
    ("Sentinel · request routes", "SELECT JSONExtractString(payload, 'route') AS route, uniqExact(session_id) AS sessions FROM events WHERE ts >= now() - INTERVAL 1 DAY AND environment = 'sentinel-modal' AND event_type = 'agent_end' AND JSONExtractString(payload, 'route') != '' GROUP BY route ORDER BY sessions DESC"),
    ("Sentinel · steering usage", "SELECT if(JSONExtractBool(payload, 'activation_steering_applied'), 'activation applied', 'no activation') AS intervention, uniqExact(session_id) AS sessions FROM events WHERE ts >= now() - INTERVAL 1 DAY AND environment = 'sentinel-modal' AND event_type = 'agent_end' AND agent_id != 'pi-assistant' GROUP BY intervention"),
    ("Sentinel · policy decisions", "SELECT hook_name, JSONExtractString(payload, 'output', 'decision') AS decision, uniqExact(hook_id) AS decisions FROM events WHERE ts >= now() - INTERVAL 1 DAY AND environment = 'sentinel-modal' AND event_type = 'hook_completed' GROUP BY hook_name, decision ORDER BY decisions DESC"),
    ("Sentinel · model latency", "SELECT model, count() AS responses, round(avg(duration_ms), 1) AS mean_ms, round(quantile(0.95)(duration_ms), 1) AS p95_ms FROM events WHERE ts >= now() - INTERVAL 1 DAY AND environment = 'sentinel-modal' AND event_type = 'model_response' AND duration_ms IS NOT NULL GROUP BY model"),
    ("Sentinel · recent experiments", "SELECT ts, session_id, JSONExtractString(payload, 'conversation_id') AS experiment, JSONExtractString(payload, 'route') AS route, JSONExtractBool(payload, 'activation_steering_applied') AS activation_applied, JSONExtractFloat(payload, 'steering', 'alpha') AS alpha, JSONExtractInt(payload, 'steering', 'layer') AS layer, JSONExtractInt(payload, 'steering', 'hook_calls') AS hook_calls FROM events WHERE ts >= now() - INTERVAL 1 DAY AND environment = 'sentinel-modal' AND event_type = 'agent_end' AND JSONExtractString(payload, 'steering', 'method') != '' ORDER BY ts DESC LIMIT 50"),
    ("Sentinel · dependency failures", "SELECT error_type, uniqExact(session_id) AS affected_sessions FROM events WHERE ts >= now() - INTERVAL 1 DAY AND environment = 'sentinel-modal' AND event_type = 'error' GROUP BY error_type ORDER BY affected_sessions DESC"),
    ('Sentinel · raw Jev input probabilities', "SELECT ts, session_id, JSONExtractFloat(payload,'content','answers','prohibited','noul') AS prohibited, JSONExtractFloat(payload,'content','answers','missing_context','noul') AS missing_context, JSONExtractFloat(payload,'content','answers','safe_reframing','noul') AS safe_reframing FROM events WHERE ts >= now() - INTERVAL 1 DAY AND environment = 'sentinel-modal' AND event_type = 'model_response' AND model = 'jev-1.13.0' AND JSONHas(payload,'content','answers','prohibited') ORDER BY ts DESC LIMIT 100"),
    ('Sentinel · raw Jev output probabilities', "SELECT ts, session_id, JSONExtractFloat(payload,'content','answers','harmful','noul') AS harmful, JSONExtractFloat(payload,'content','answers','private_data','noul') AS private_data, JSONExtractFloat(payload,'content','answers','injection_followed','noul') AS injection_followed FROM events WHERE ts >= now() - INTERVAL 1 DAY AND environment = 'sentinel-modal' AND event_type = 'model_response' AND model = 'jev-1.13.0' AND JSONHas(payload,'content','answers','harmful') ORDER BY ts DESC LIMIT 100"),
    ('Sentinel · individual policy decisions', "SELECT ts, session_id, JSONExtractString(policy,'name') AS policy_name, JSONExtractString(policy,'decision') AS decision, JSONExtractString(policy,'reason') AS reason, 'application-enforced' AS enforcement_scope FROM events ARRAY JOIN JSONExtractArrayRaw(payload,'output','policies') AS policy WHERE ts >= now() - INTERVAL 1 DAY AND environment = 'sentinel-modal' AND event_type = 'hook_completed' ORDER BY ts DESC LIMIT 100"),
    ('Sentinel · input scores at enforcement', "SELECT ts, session_id, JSONExtractString(payload,'input','eventType') AS trigger_event, JSONExtractString(payload,'input','toolName') AS action, JSONExtractFloat(payload,'input','payload','judgment','prohibited') AS prohibited, JSONExtractFloat(payload,'input','payload','judgment','missing_context') AS missing_context, JSONExtractFloat(payload,'input','payload','judgment','safe_reframing') AS safe_reframing FROM events WHERE ts >= now() - INTERVAL 1 DAY AND environment = 'sentinel-modal' AND event_type = 'hook_triggered' AND JSONHas(payload,'input','payload','judgment','prohibited') ORDER BY ts DESC LIMIT 100"),
]


def install():
    # Validate every query before changing anything in the dashboard.
    for name, sql in QUERIES:
        result=api('/queries/run',{'sql':sql})
        print(name, 'validated', len(result['rows']), 'rows', flush=True)
    dashboards=api('/dashboards')['dashboards']
    dashboard=next((d for d in dashboards if d['name']==DASHBOARD_NAME),None)
    if dashboard is None:
        dashboard=api('/dashboards',{'name':DASHBOARD_NAME,'description':'Sentinel H100 safety experiments. Experimental steering, not a validated safety claim.','definition':{}})
    dashboard_id=dashboard['id']
    existing=api('/dashboards/'+dashboard_id+'/tiles')['tiles']
    queries=api('/queries')['queries']
    for i,(name,sql) in enumerate(QUERIES):
        query=next((q for q in queries if q['name']==name),None)
        if query is None: query=api('/queries',{'name':name,'sql_text':sql,'params':[],'description':'Sentinel Modal environment only; provisional experiment monitoring.'})
        elif query['sql_text'] != sql:
            query=api('/queries/'+query['id'],{'name':name,'sql_text':sql,'params':query.get('params',[]),'description':query.get('description','')},method='PUT')
        if not any(t['query_id']==query['id'] for t in existing):
            api('/dashboards/'+dashboard_id+'/tiles',{'query_id':query['id'],'title':name,'chart_type':'table','pos_x':(i%2)*6,'pos_y':(i//2)*6,'pos_w':6,'pos_h':6,'chart_config':{},'param_bindings':{}})
    # Put wide raw-score/policy tables first so their columns remain readable.
    tiles=api('/dashboards/'+dashboard_id+'/tiles')['tiles']
    ordered_names=[name for name,_ in QUERIES[6:]+QUERIES[:6]]
    layout=[]
    for i,name in enumerate(ordered_names):
        tile=next((t for t in tiles if t.get('title')==name),None)
        if tile:
            layout.append({'id':tile['id'],'pos_x':0 if i<4 else ((i-4)%2)*6,
                           'pos_y':i*6 if i<4 else 24+((i-4)//2)*6,
                           'pos_w':12 if i<4 else 6,'pos_h':6})
    api('/dashboards/'+dashboard_id+'/tiles/layout',{'tiles':layout},method='PUT')
    result=api('/dashboards/'+dashboard_id)
    print(json.dumps({'dashboard_id':dashboard_id,'tiles':len(result['tiles']),'url':BASE.removesuffix('/v1')+'/'+ORG+'/dashboards/'+dashboard_id}))

if __name__ == '__main__': install()
