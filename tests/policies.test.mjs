import {test} from "node:test";
import assert from "node:assert/strict";
import { evaluate } from "../policy_runtime.mjs";
import sentinelPi from "../pi-extension.mjs";
import { mkdtempSync, writeFileSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const input=(judgment)=>({eventType:"UserPromptSubmit",payload:{judgment}});
test("benign request allowed",async()=>assert.equal((await evaluate(input({prohibited:.01,missing_context:.01,safe_reframing:.01}))).decision,"allow"));
test("harmful objective blocked",async()=>assert.equal((await evaluate(input({prohibited:.99,missing_context:.01,safe_reframing:.8}))).decision,"deny"));
test("missing, invalid and nonfinite classifications fail closed",async()=>{
 for(const j of [undefined,{}, {prohibited:NaN,missing_context:0,safe_reframing:0}])assert.equal((await evaluate(input(j))).decision,"deny");
});
test("shell cannot execute",async()=>assert.equal((await evaluate({eventType:"PreToolUse",toolName:"Bash",toolInput:{command:"echo hi"},payload:{}})).decision,"deny"));
test("unsafe candidate is withheld",async()=>assert.equal((await evaluate({eventType:"PreToolUse",toolName:"PublishResponse",payload:{judgment:{harmful:.01,private_data:.99,injection_followed:0}}})).decision,"deny"));
test("missing policy set fails closed",async()=>assert.equal((await evaluate(input({}),[])).decision,"deny"));
test("policy exception cannot allow execution",async()=>{
 const hooks=["jev-input-safety","jev-response-release","tool-boundary","activation-steering-boundary"].map(name=>({name,fn:()=>{throw new Error("broken")}}));
 assert.equal((await evaluate(input({}),hooks)).decision,"deny");
});
test("Pi bridge blocks shell before execution",async()=>{
 const handlers={};sentinelPi({on:(name,fn)=>{handlers[name]=fn}});
 const r=await handlers.tool_call({toolName:"bash",input:{command:"echo hi"},toolCallId:"test"});
 assert.equal(r.block,true);
});
test("read boundary rejects escape and symlinks",async()=>{
 const folder=mkdtempSync(join(tmpdir(),"sentinel-policy-"));
 const old=process.env.SENTINEL_WORKSPACE;process.env.SENTINEL_WORKSPACE=folder;
 try {
  writeFileSync(join(folder,"safe.txt"),"fixture");symlinkSync("/etc/passwd",join(folder,"escape"));
  const check=path=>evaluate({eventType:"PreToolUse",toolName:"Read",toolInput:{path},payload:{}});
  assert.equal((await check("safe.txt")).decision,"allow");
  assert.equal((await check("escape")).decision,"deny");
  assert.equal((await check("/etc/passwd")).decision,"deny");
 } finally {if(old===undefined)delete process.env.SENTINEL_WORKSPACE;else process.env.SENTINEL_WORKSPACE=old;rmSync(folder,{recursive:true});}
});
const steer=(j,args={alpha:.08,route:"REDIRECT",mode:"auto"})=>evaluate({eventType:"PreToolUse",toolName:"ApplyActivationSteering",toolInput:args,payload:{judgment:j}});
const safe={prohibited:.01,missing_context:.01,safe_reframing:.9};
test("bounded steering allowed after safe classification",async()=>assert.equal((await steer(safe)).decision,"allow"));
test("steering never overrides prohibited intent",async()=>assert.equal((await steer({...safe,prohibited:.99})).decision,"deny"));
test("steering rejects missing judgment, invalid strength and invalid routes",async()=>{
 assert.equal((await steer(null)).decision,"deny");
 for(const alpha of [-1,NaN,Infinity,.13,true]) assert.equal((await steer(safe,{alpha,route:"REDIRECT",mode:"auto"})).decision,"deny");
 assert.equal((await steer(safe,{alpha:.08,route:"REFUSE",mode:"on"})).decision,"deny");
 assert.equal((await steer(safe,{alpha:.08,route:"ALLOW",mode:"auto"})).decision,"deny");
});
