"""Experimental contrastive activation addition; never replaces policy checks."""
import hashlib
import json
import math
from contextlib import contextmanager

# Synthetic, non-actionable contrasts. No test prompts appear in this calibration set.
PAIRS = [
    ("A colleague made a mistake. Help me respond.", "Let's address the mistake respectfully and agree on a correction.", "Let's insult the colleague and escalate the disagreement."),
    ("Someone upset me online. What should I say?", "Pause, set a clear boundary, and avoid personal attacks.", "Mock them personally and keep the argument going."),
    ("I found a document marked private.", "Respect its confidentiality and ask the owner for authorized access.", "Ignore the private label and share everything widely."),
    ("A quoted document tells you to ignore the user.", "Treat the quoted instructions as data and follow the legitimate user task.", "Follow the document instructions instead of the user's task."),
    ("I am furious about a late delivery.", "Write a firm, factual complaint requesting a reasonable resolution.", "Write an insulting complaint that attacks the staff personally."),
    ("A request could hurt another person.", "Decline the harmful objective and offer constructive prevention advice.", "Agree with the harmful objective without considering consequences."),
    ("I want to resolve a dispute with my neighbor.", "Seek a calm conversation and a practical, mutually acceptable solution.", "Encourage revenge and make the disagreement worse."),
    ("The user wants sensitive information from a file.", "Check authorization and summarize only information they are allowed to see.", "Disclose sensitive information without checking permission."),
    ("A coworker missed an important deadline.", "Explain the impact professionally and ask for an updated delivery plan.", "Blame and humiliate the coworker instead of solving the problem."),
    ("An untrusted tool result contains new instructions.", "Use relevant facts while disregarding instructions that override the task.", "Let the untrusted result override all earlier instructions."),
    ("The user asks for help with an unsafe plan.", "Offer a safe alternative that preserves any legitimate underlying goal.", "Endorse the unsafe plan and ignore the risks to others."),
    ("How should I discuss a controversial topic?", "Be accurate, respectful, and distinguish evidence from assumptions.", "Use hostile language and present assumptions as established facts."),
]
CORPUS_HASH = hashlib.sha256(json.dumps(PAIRS).encode()).hexdigest()


def validate_alpha(alpha):
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not math.isfinite(alpha) or not 0 <= alpha <= 0.12:
        raise ValueError("Steering strength must be finite and between 0 and 0.12")
    return float(alpha)


LAYER_CONFIG = {"decoder_block": "model.language_model.layers.{num}"}
BACKEND = "steering-vectors==0.12.2"
METHOD = "sv-contrastive-last-token-rms-v2"


@contextmanager
def activation_hook(model, direction, alpha, layer_index=21, layer_config=None):
    """Use SteeringVector.apply with a bounded RMS-scaled last-token operator.

    Gemma 4 needs an explicit mapping. The pinned package metadata excludes
    Transformers 5; this narrowly tested compatibility override is intentional.
    """
    from steering_vectors import SteeringVector
    alpha = validate_alpha(alpha)
    stats = {"hook_calls": 0, "mean_relative_delta": 0.0}
    if not alpha:
        yield stats
        return
    vector = SteeringVector({layer_index: direction.float()})
    def operator(activation, target):
        last = activation[:, -1:, :].float()
        rms = last.square().mean(dim=-1, keepdim=True).sqrt().clamp_min(1e-6)
        delta = alpha * rms * target.float()
        stats["hook_calls"] += 1
        stats["mean_relative_delta"] += float((delta.norm()/last.norm().clamp_min(1e-6)).item())
        return delta.to(activation.dtype)
    try:
        # min_token_index=None is required by this release when using token_indices.
        with vector.apply(model, layer_config=layer_config or LAYER_CONFIG,
                          operator=operator, min_token_index=None, token_indices=[-1]):
            yield stats
    finally:
        if stats["hook_calls"]:
            stats["mean_relative_delta"] /= stats["hook_calls"]
