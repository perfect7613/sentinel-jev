// Adapter over the real FailproofAI registry; not the host/fleet daemon.
// Mirrors the package's ESM compatibility shim and fails closed on errors.
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const root = dirname(require.resolve("failproofai/package.json"));
const runtime = require(join(root, "dist/index.js"));
const dist = pathToFileURL(join(root, "dist/index.js")).href;
const shim = `import api from ${JSON.stringify(dist)}; export const {customPolicies,allow,deny,instruct}=api;`;
const shimURL = `data:text/javascript;base64,${Buffer.from(shim).toString("base64")}`;
const bundledPath = join(dirname(fileURLToPath(import.meta.url)), "policies/sentinel-policies.mjs");
async function loadHooks(path, tag) {
  const source = (await readFile(path,"utf8")).replace(/from\s+["']failproofai["']/g, `from "${shimURL}"`);
  runtime.clearCustomHooks();
  await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}#${tag}`);
  return [...runtime.getCustomHooks()];
}
const cloud = process.env.SENTINEL_POLICY_PATH ? JSON.parse(process.env.SENTINEL_POLICY_METADATA || "null") : null;
if (process.env.SENTINEL_POLICY_PATH && (!cloud || !["observe","enforce"].includes(cloud.effect)))
  throw new Error("Cloud policy metadata is required");
const cloudHooks = cloud ? await loadHooks(process.env.SENTINEL_POLICY_PATH,"cloud") : null;
const activeHooks = cloud?.effect === "enforce" ? cloudHooks : await loadHooks(bundledPath,"bundled");
const expected = ["jev-input-safety", "jev-response-release", "tool-boundary", "activation-steering-boundary"];

async function evaluateHooks(ctx, hooks) {
  if (expected.some(name => !hooks.some(h => h.name === name)))
    return {decision:"deny",reason:"Required policies are missing",error:true,policies:[]};
  const results = [];
  for (const hook of hooks) {
    if (hook.match?.events && !hook.match.events.includes(ctx.eventType)) continue;
    let timer;
    try {
      const r = await Promise.race([Promise.resolve().then(() => hook.fn(ctx)), new Promise((_,reject) => {
        timer=setTimeout(() => reject(new Error("Policy timeout")), 2000);
      })]);
      if (!r || !["allow","deny","instruct"].includes(r.decision)) throw new Error("Invalid policy result");
      results.push({name:hook.name,...r});
    } catch {
      results.push({name:hook.name,decision:"deny",reason:"Policy evaluation failed",error:true});
    } finally { clearTimeout(timer); }
  }
  if (!results.length) return {decision:"deny",reason:"No applicable policy",error:true,policies:[]};
  const decisive=results.find(x=>x.decision==="deny") ?? results.find(x=>x.decision==="instruct") ?? results[0];
  return {...decisive,policies:results,version:"sentinel-2"};
}
export async function evaluate(ctx, hooks = activeHooks) {
  const result = await evaluateHooks(ctx, hooks);
  if (!cloud) return result;
  const metadata = {...cloud, runtime: "serverless-application-reconciler"};
  if (cloud.effect === "observe") {
    const observed = await evaluateHooks(ctx, cloudHooks);
    return {...result, cloud_policy: metadata, observed: [observed], enforcement_scope: "bundled-with-cloud-observation"};
  }
  return {...result, cloud_policy: metadata, enforcement_scope: "cloud-managed-application"};
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    let data=""; for await (const chunk of process.stdin) data+=chunk;
    console.log(JSON.stringify(await evaluate(JSON.parse(data))));
  } catch { console.log(JSON.stringify({decision:"deny",reason:"Policy adapter failed",error:true})); process.exitCode=1; }
}
