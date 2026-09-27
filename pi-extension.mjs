import { appendFileSync } from "node:fs";
import { evaluate } from "./policy_runtime.mjs";

// Pinned, fail-closed bridge for this custom Modal harness. Uses the real
// FailproofAI policy registry through our adapter, not the fail-open stock bridge.
export default function sentinel(pi) {
  const record = (value) => {
    if (process.env.SENTINEL_PI_EVENTS)
      appendFileSync(process.env.SENTINEL_PI_EVENTS, JSON.stringify(value)+"\n");
  };
  pi.on("tool_call", async (event) => {
    const names = {read:"Read",bash:"Bash",write:"Write",edit:"Edit"};
    try {
      const result = await evaluate({eventType:"PreToolUse",toolName:names[event.toolName] ?? event.toolName,
        toolInput:{...event.input,file_path:event.input?.path},payload:{}});
      record({kind:"policy",tool:event.toolName,id:event.toolCallId,input:event.input,verdict:result});
      if (result.decision !== "allow") return {block:true,reason:result.reason || "Policy denied"};
    } catch { return {block:true,reason:"Policy bridge failed"}; }
  });
  pi.on("tool_result", event => { record({kind:"tool_result",tool:event.toolName,id:event.toolCallId,output:event.content,isError:event.isError}); });
  pi.on("user_bash", () => ({result:{output:"Shell is disabled in this deployment.",exitCode:1,cancelled:false,truncated:false}}));
}
