# Security and deployment boundaries

The HTTP controller requires a bearer token on every route. The GPU class is private to the Modal workspace. Pi receives only the controller token, not Jev or FailproofAI credentials. Shell and write tools are outside this demo's allowed tool set.

The `/runs` endpoint contains full operator traces, including withheld candidates. Treat the controller token as an operator credential. This is a single-tenant hackathon prototype, not a multi-user production authorization system.

Raw prompts, generated candidates and tool data are transmitted to configured Jev and FailproofAI services. Use synthetic data for demos unless you have permission to process real data. The published pilot contains only synthetic cases. Screenshots are cropped to omit account identifiers; they are real captures, not recreated UIs.

Policies execute in the application's dispatcher. No native FailproofAI fleet daemon or Cloud deployment assignment is claimed. Do not interpret a session in Cloud as proof of fleet enrollment.

Steering is experimental, defaults off, and cannot override input refusals or output release checks. A successful small pilot does not establish jailbreak robustness, model safety or safe autonomous tool execution.

Keep runtime credentials outside the repository. `runtime-secrets.example.json` is a template only. Never replace its placeholders in a committed file. If reporting a vulnerability, do not include tokens, private traces or withheld sensitive content in a public issue; contact the repository owner privately.
