"""Local operator client. Credentials stay in ~/.config/sentinel/client.json."""
import argparse
import json
import os
from pathlib import Path
import urllib.request

def request(path, body=None):
    if os.getenv("SENTINEL_BASE_URL") and os.getenv("SENTINEL_API_TOKEN"):
        config={"base_url":os.environ["SENTINEL_BASE_URL"].rstrip("/"),"api_token":os.environ["SENTINEL_API_TOKEN"]}
    else:
        config=json.loads((Path.home()/".config/sentinel/client.json").read_text())
    req=urllib.request.Request(config["base_url"]+path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization":"Bearer "+config["api_token"],"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=600) as response:
        return json.load(response)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["health","chat","document","pi","trace","steering","experiment"])
    parser.add_argument("text",nargs="?",default="Explain a rainbow in one sentence.")
    parser.add_argument("--document",type=Path)
    parser.add_argument("--steering",choices=["off","auto","on"],default="off")
    parser.add_argument("--alpha",type=float,default=0.08)
    args=parser.parse_args()
    if args.command in {"health","steering"}: result=request("/"+args.command)
    elif args.command=="trace": result=request("/runs/"+args.text)
    elif args.command=="pi": result=request("/pi",{"prompt":args.text,"steering_mode":args.steering,"steering_alpha":args.alpha})
    else:
        body={"agent":"document-assistant" if args.command=="document" else "assistant",
              "messages":[{"role":"user","content":args.text}],
              "steering_mode":args.steering,"steering_alpha":args.alpha}
        if args.document: body["document"]=args.document.read_text()
        result=request("/experiment" if args.command=="experiment" else "/chat",body)
    print(json.dumps(result,indent=2,ensure_ascii=False))
