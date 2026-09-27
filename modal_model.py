"""Private H100 model service with experimental contrastive activation addition."""
from pathlib import Path
import modal

MODEL_ID = "huihui-ai/Huihui-gemma-4-E4B-it-abliterated"
MODEL_REVISION = "03ce1f3a982b544afb03878ce80e7f042bcdc172"
app = modal.App("sentinel-model")
weights = modal.Volume.from_name("sentinel-model-weights", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.10.0", "transformers==5.17.0", "accelerate==1.13.0", "sentencepiece==0.2.1")
    .pip_install("scikit-learn==1.7.2")
    .pip_install("steering-vectors==0.12.2", extra_options="--no-deps")
    .env({"HF_HOME": "/models", "HF_HUB_DISABLE_TELEMETRY": "1"})
    .add_local_file(Path(__file__).parent/"steering.py", "/root/steering.py")
)


@app.cls(image=image, gpu="H100!", volumes={"/models": weights},
         max_containers=1, min_containers=0, scaledown_window=180,
         timeout=300, startup_timeout=900)
class Gemma:
    @modal.enter()
    def load(self):
        import threading
        import torch
        from transformers import AutoTokenizer, Gemma4ForConditionalGeneration
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
        self.model = Gemma4ForConditionalGeneration.from_pretrained(
            MODEL_ID, revision=MODEL_REVISION, torch_dtype=torch.bfloat16,
            device_map="cuda", attn_implementation="sdpa",
        ).eval()
        weights.commit()
        self.device_name = torch.cuda.get_device_name(0)
        self.lock = threading.Lock()
        self.layers = self.model.model.language_model.layers
        self.layer_index = len(self.layers) // 2
        self._prepare_steering()

    def _prepare_steering(self):
        import hashlib, json, torch
        from steering import PAIRS, CORPUS_HASH, LAYER_CONFIG, BACKEND, METHOD
        from steering_vectors import train_steering_vector
        path = Path("/models/sentinel-steering") / f"{MODEL_REVISION}-{CORPUS_HASH[:12]}-l{self.layer_index}-{METHOD}.json"
        if path.exists():
            artifact = json.loads(path.read_text())
        else:
            def format_sample(prompt, response):
                return self.tokenizer.apply_chat_template(
                    [{"role":"user","content":prompt},{"role":"assistant","content":response}],
                    tokenize=False, add_generation_prompt=False, enable_thinking=False)
            samples = [(format_sample(p,a),format_sample(p,b)) for p,a,b in PAIRS]
            vector = train_steering_vector(
                self.model, self.tokenizer, samples, layers=[self.layer_index],
                layer_config=LAYER_CONFIG, read_token_index=-1, batch_size=1,
                move_to_cpu=True, show_progress=False)
            direction = vector.layer_activations[self.layer_index].float()
            direction /= direction.square().mean().sqrt().clamp_min(1e-6)
            artifact = {"model":MODEL_ID,"revision":MODEL_REVISION,"corpus_hash":CORPUS_HASH,
                        "layer":self.layer_index,"pairs":len(PAIRS),"method":METHOD,"backend":BACKEND,"layer_config":LAYER_CONFIG,
                        "direction":direction.tolist(),"validated_safety_improvement":False}
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(artifact))
            weights.commit()
        vector = torch.tensor(artifact["direction"],device="cuda",dtype=torch.float32)
        if artifact["revision"] != MODEL_REVISION or artifact["corpus_hash"] != CORPUS_HASH or artifact["layer"] != self.layer_index:
            raise ValueError("Steering artifact provenance mismatch")
        if vector.numel() != self.model.config.text_config.hidden_size or not torch.isfinite(vector).all() or vector.norm() < 1e-6:
            raise ValueError("Invalid steering vector")
        self.direction = vector
        self.steering_artifact = {k:v for k,v in artifact.items() if k != "direction"}
        self.steering_artifact["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    @modal.method()
    def steering_status(self):
        return {**self.steering_artifact,"gpu":self.device_name,"ready":True}

    @modal.method()
    def generate(self, messages: list[dict], max_tokens: int = 256, seed: int = 42,
                 temperature: float = 0.0, steering_alpha: float = 0.0):
        # A hook must never affect a different concurrent request.
        with self.lock:
            return self._generate(messages,max_tokens,seed,temperature,steering_alpha)

    def _generate(self, messages, max_tokens, seed, temperature, steering_alpha):
        import time
        import torch
        from steering import activation_hook, validate_alpha
        steering_alpha = validate_alpha(steering_alpha)
        if not messages or len(messages) > 32:
            raise ValueError("Expected between 1 and 32 messages")
        if any(m.get("role") not in {"system", "user", "assistant"}
               or not isinstance(m.get("content"), str) for m in messages):
            raise ValueError("Text-only messages with explicit roles required")
        torch.manual_seed(seed)
        prompt = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
        )
        inputs = self.tokenizer(prompt, return_tensors="pt").to("cuda")
        count = inputs.input_ids.shape[-1]
        if count > 8192:
            raise ValueError("Input exceeds the 8192-token deployment limit")
        options = {"max_new_tokens": max(1, min(int(max_tokens), 512)),
                   "do_sample": temperature > 0, "use_cache": True}
        if temperature > 0:
            options["temperature"] = max(0.1, min(temperature, 1.5))
        started = time.monotonic()
        with torch.inference_mode(), activation_hook(self.model,self.direction,steering_alpha,self.layer_index) as stats:
            ids = self.model.generate(**inputs, **options)[0, count:]
        return {"content": self.tokenizer.decode(ids, skip_special_tokens=True),
                "model": MODEL_ID, "revision": MODEL_REVISION, "gpu": self.device_name,
                "input_tokens": count, "output_tokens": len(ids),
                "duration_ms": round((time.monotonic()-started)*1000),
                "activation_steering_applied": stats["hook_calls"] > 0,
                "steering": {"alpha":steering_alpha,**stats,**self.steering_artifact}}


@app.local_entrypoint()
def main():
    print(Gemma().steering_status.remote())
