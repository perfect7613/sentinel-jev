import { customPolicies, allow, deny, instruct } from "failproofai";
import { realpathSync } from "node:fs";
import { resolve, sep } from "node:path";

export const POLICY_VERSION = "sentinel-2";
const probability = (v) => typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1;
customPolicies.add({
  name: "jev-input-safety", description: "Classify the conversation before generation.",
  match: { events: ["UserPromptSubmit"] },
  fn: (ctx) => {
    const j = ctx.payload.judgment;
    if (!j || ![j.prohibited, j.missing_context, j.safe_reframing].every(probability))
      return deny("Classification unavailable. No unchecked generation is permitted.");
    if (j.prohibited >= 0.7) return deny("The requested objective is prohibited. Offer a safe alternative.");
    if (j.missing_context >= 0.7) return instruct("CLARIFY: Ask for the missing context before proceeding.");
    if (j.safe_reframing >= 0.6) return instruct("REDIRECT: Answer the legitimate part neutrally and omit harmful assistance.");
    return allow();
  },
});
customPolicies.add({
  name: "jev-response-release", description: "Check the actual candidate before publication.",
  match: { events: ["PreToolUse"] },
  fn: (ctx) => {
    if (ctx.toolName !== "PublishResponse") return allow();
    const j = ctx.payload.judgment;
    if (!j || ![j.harmful, j.private_data, j.injection_followed].every(probability))
      return deny("Output classification unavailable; withhold this candidate.");
    if (Math.max(j.harmful, j.private_data, j.injection_followed) >= 0.5)
      return deny("Do not publish this candidate. Provide a safe, relevant answer without exposing private data.");
    return allow();
  },
});
customPolicies.add({
  name: "tool-boundary", description: "Only documented tools and confined fixture reads are permitted.",
  match: { events: ["PreToolUse"] },
  fn: (ctx) => {
    if (["PublishResponse", "ReadDocument", "ApplyActivationSteering"].includes(ctx.toolName)) return allow();
    if (ctx.toolName === "Read") {
      try {
        const root = realpathSync(process.env.SENTINEL_WORKSPACE || "/workspace");
        const requested = ctx.toolInput?.file_path ?? ctx.toolInput?.path;
        if (typeof requested !== "string") return deny("Read requires an explicit path.");
        const target = realpathSync(resolve(root, requested));
        return target.startsWith(root + sep) ? allow() : deny("Read only files inside the demo workspace.");
      } catch { return deny("The requested workspace file does not exist or is not accessible."); }
    }
    return deny("This tool is unavailable. Use the read-only document tools; shell and writes are disabled.");
  },
});

customPolicies.add({
  name: "activation-steering-boundary",
  description: "Permit only bounded experiments after a valid input judgment. Never steer a prohibited request into compliance.",
  match: { events: ["PreToolUse"] },
  fn: (ctx) => {
    if (ctx.toolName !== "ApplyActivationSteering") return allow();
    const { alpha, route, mode } = ctx.toolInput ?? {};
    const j = ctx.payload?.judgment;
    if (!j || ![j.prohibited,j.missing_context,j.safe_reframing].every(probability)) return deny("Steering requires a valid input judgment.");
    if (j.prohibited >= 0.7 || j.missing_context >= 0.7) return deny("Refuse or clarify this request before generation.");
    if (!probability(alpha) || alpha <= 0 || alpha > 0.12) return deny("Steering strength must be greater than zero and at most 0.12.");
    if (!["ALLOW","REDIRECT"].includes(route) || !["auto","on"].includes(mode)) return deny("Invalid steering route or mode.");
    if (mode === "auto" && route !== "REDIRECT") return deny("Automatic steering is only allowed for redirection.");
    return allow();
  },
});
