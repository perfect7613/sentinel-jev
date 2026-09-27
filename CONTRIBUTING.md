# Contributing

Run `npm ci --ignore-scripts`, `npm test`, and `python -m unittest discover -s tests -p test_service.py` in an environment containing the dependencies in `pyproject.toml`.

Use `modal run steering_checks.py` for the four real PyTorch checks in the model image, or install the pinned CPU dependencies from the CI workflow. Tensor tests must not be counted as passed when skipped.

Use synthetic fixtures. Add regression tests for policy decisions, invalid judgments and tool boundaries. Preserve fail-closed error handling, explicit steering provenance and paired comparisons. Never tune a vector on `evals/cases.json` and then call that file held-out evidence.

Changed model, package, calibration set, layer or steering logic requires a new artifact identity and a new eval run. Keep failed cases in results and describe limitations. No private prompts, credentials, machine UUIDs or personal logs should enter a pull request.
