# Steering backend and compatibility

The deployed backend uses **steering-vectors 0.12.2** for `train_steering_vector` and `SteeringVector.apply`. It runs against Torch 2.10.0 and Transformers 5.17.0, on the pinned `huihui-ai/Huihui-gemma-4-E4B-it-abliterated` revision in `modal_model.py`.

## This is a tested adapter, not out-of-the-box Gemma 4 support

The published package declares `transformers>=4.35.2,<5.0.0`. Gemma 4 requires the newer Transformers stack used here. The Modal image installs the pinned dependency stack first, then installs `steering-vectors==0.12.2 --no-deps`. This is an intentional compatibility override; `pip check` will report that upstream version constraint. It must not be generalized to arbitrary models or library versions.

The explicit decoder mapping is:

```python
LAYER_CONFIG = {"decoder_block": "model.language_model.layers.{num}"}
```

The current TransformerLens documentation did not establish support for this Gemma 4 architecture. We therefore retained the working Hugging Face model rather than claim an unverified TransformerLens conversion.

## Extraction

Twelve synthetic positive/negative response pairs are in `steering.py`. Both sides use the same situation. The package extracts final-token decoder activations at zero-based layer 21 and computes the mean positive-minus-negative direction. We convert the resulting vector to float32 and normalize it to unit RMS. It is persisted as JSON, with model revision, corpus hash, method, layer mapping, package version and artifact SHA-256.

These examples are a small calibration corpus. They are not a trained safety classifier, and end-of-response representations can reflect stylistic or length differences as well as the intended behavior. The pilot cases are separate from the calibration examples; they were not used to select the layer or strength.

## Application

`SteeringVector.apply` installs and removes the hook. We supply a custom bounded delta operator:

```text
h_last ← h_last + alpha × RMS(h_last) × direction
```

`token_indices=[-1]` selects the last token on the prompt forward pass and each decode step. `min_token_index=None` avoids this version's mutually exclusive selector assertion. The package modifies the decoder output in place; normal decoder output does not alias the original input. Inference is serialized under a lock so the hook cannot cross requests. The context manager removes the hook on normal completion and exceptions.

- `off`: exact baseline; no hook installed.
- `auto`: intervene only on an input-approved REDIRECT route.
- `on`: explicit experiment on an input-approved ALLOW or REDIRECT route.
- Alpha: default 0.08, permitted 0–0.12. Zero skips intervention.

Input refusal and missing-context decisions take priority. Output checks apply after generation in every mode. A model response that fails to confirm a requested intervention becomes an ERROR rather than a silently unsteered success.

## Verification

`modal run steering_checks.py` runs actual tensor tests for strength validation, last-token behavior, no original-input mutation, zero-strength identity and cleanup after exceptions. `uv run verify_steering.py` calls the deployed H100 in off/on/off order and checks that the later baseline is unchanged. The pilot results record actual hook calls and artifact identity.

## Upstream sources

- [steering-vectors source](https://github.com/steering-vectors/steering-vectors)
- [0.12.2 package metadata](https://pypi.org/project/steering-vectors/0.12.2/)
- [Training and application](https://steering-vectors.github.io/steering-vectors/basic_usage.html)
- [TransformerLens architecture loading](https://github.com/TransformerLensOrg/TransformerLens/blob/main/transformer_lens/loading_from_pretrained.py)

Passing the pilot does not establish a safety improvement. A larger independently labeled evaluation, multiple seeds, ablations and layer/strength selection on a separate validation set remain future work.
