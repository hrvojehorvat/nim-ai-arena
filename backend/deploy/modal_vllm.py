"""Serve an open-weight chat model on Modal with vLLM, behind an OpenAI-compatible API.

Not part of the app: this is a standalone deploy script. The app will call the resulting URL with
`ChatOpenAI(base_url=<url>/v1, api_key=<key>, model=MODEL)` (subphase 5.6).

One-time setup (Modal CLI is not a project dependency):
    uv tool install modal            # or: pip install modal
    modal setup                      # log in
    modal secret create nim-llm-key NIM_LLM_API_KEY=<pick-a-long-random-string>

Deploy / try:
    modal deploy backend/deploy/modal_vllm.py     # prints the URL, stays deployed, scales to zero
    modal serve backend/deploy/modal_vllm.py      # same but temporary, stops with Ctrl+C
    modal app stop nim-llm                        # remove the deployment

Cost: billed per second only while a container runs (L4 is roughly $0.8/h); it shuts down
after SCALEDOWN_SECONDS without requests. The first request after idle takes ~1-3 minutes
(cold start: start container, load weights). Weights are cached in a Volume after the first run.
The Starter plan includes $30/month of free credits; check modal.com/pricing for current rates.

Test:
    curl <url>/v1/models -H "Authorization: Bearer <your key>"
"""

import subprocess

import modal

# Ungated open model (no Hugging Face token needed). Swap for e.g. "Qwen/Qwen2.5-3B-Instruct"
# (cheaper/faster, weaker) or "Qwen/Qwen2.5-14B-Instruct" with GPU="A100-40GB".
MODEL = "Qwen/Qwen2.5-7B-Instruct"
GPU = "L4"  # 24 GB: fits a 7B model in fp16
PORT = 8000
SCALEDOWN_SECONDS = 300  # idle time before the container (and billing) stops

# The CUDA "devel" base image ships nvcc. vLLM's FlashInfer sampler compiles a kernel on first
# use and crashed on debian_slim ("Could not find nvcc"). Version pinned to what was tested.
image = (
    modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12")
    .uv_pip_install("vllm==0.33.0", "huggingface_hub")
    .env({"HF_XET_HIGH_PERFORMANCE": "1", "VLLM_USE_FLASHINFER_SAMPLER": "0"})
)

# Keep downloaded weights between cold starts.
hf_cache = modal.Volume.from_name("nim-llm-hf-cache", create_if_missing=True)

app = modal.App("nim-llm")


@app.function(
    image=image,
    gpu=GPU,
    volumes={"/root/.cache/huggingface": hf_cache},
    secrets=[modal.Secret.from_name("nim-llm-key")],
    scaledown_window=SCALEDOWN_SECONDS,
    timeout=10 * 60,
)
@modal.concurrent(max_inputs=8)
@modal.web_server(port=PORT, startup_timeout=10 * 60)
def serve() -> None:
    import os

    subprocess.Popen(
        [
            "vllm",
            "serve",
            MODEL,
            "--served-model-name",
            MODEL,
            "--host",
            "0.0.0.0",
            "--port",
            str(PORT),
            "--api-key",
            os.environ["NIM_LLM_API_KEY"],  # requests need this as the bearer token
            "--max-model-len",
            "4096",  # Nim prompts are small; saves GPU memory
            "--enforce-eager",  # faster start, slightly slower tokens: fine here
        ]
    )
