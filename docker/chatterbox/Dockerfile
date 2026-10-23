# Chatterbox Nano TTS, CPU only. Built by `just tts up -d` (docker/chatterbox/compose.yaml).
# Weights are not baked in: they're mounted from /opt/models/chatterbox-nano.
FROM python:3.11.14-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends libsndfile1 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv

# CPU wheels only: the CUDA build of torch would add ~4 GB the container never uses.
RUN uv pip install --system --no-cache \
      --index-url https://download.pytorch.org/whl/cpu \
      torch==2.6.0 torchaudio==2.6.0

# chatterbox's own pins (pyproject at the commit below), minus gradio and the multilingual
# tokenizers, which the Nano path never imports. resemble-perth from PyPI instead of the
# unpinned git master the pyproject names. --exclude-newer keeps every transitive pick at
# least two weeks older than the build date the Refinery pinned.
RUN uv pip install --system --no-cache --exclude-newer 2026-10-01 \
      "numpy>=1.24,<2" librosa==0.11.0 s3tokenizer==0.3.0 transformers==5.2.0 \
      diffusers==0.29.0 resemble-perth==1.0.1 conformer==0.3.2 safetensors==0.5.3 \
      pyloudnorm omegaconf==2.3.0
RUN uv pip install --system --no-cache --no-deps \
      https://github.com/resemble-ai/chatterbox/archive/5de7a54aa4e5e2baadb0182dde554908b48b85c2.tar.gz

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PYTHONUNBUFFERED=1

COPY server.py /app/server.py
WORKDIR /app
EXPOSE 8080
CMD ["python", "/app/server.py"]
