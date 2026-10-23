# ComfyUI built from a pinned upstream commit, plus ComfyUI-GGUF for the Wan 2.2 GGUFs.
# No prebuilt third-party image: every byte comes from upstream ComfyUI, PyPI and the
# PyTorch wheel index, at the versions below.
#
# Pins (each at least two weeks old when chosen, 2026-10-23):
#   ComfyUI v0.39.0 (2026-10-05)        Comfy-Org/ComfyUI, GPL-3.0
#   ComfyUI-GGUF 6ea2651 (2026-01-12)   city96/ComfyUI-GGUF, Apache-2.0
#   torch 2.11.0 + torchvision 0.26.0, CUDA 12.8 wheels (host driver: CUDA 13.0)
# Dependencies checked for Microsoft-owned packages (onnxruntime, DeepSpeed, playwright,
# azure-*): none in either requirements file.
FROM python:3.12-slim-bookworm

ARG COMFYUI_COMMIT=b0b743566f65daafc423b4fea8a2fbda94b3384a
ARG GGUF_COMMIT=6ea2651e7df66d7585f6ffee804b20e92fb38b8a
ARG TORCH=2.11.0
ARG TORCHVISION=0.26.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu128 \
        torch==${TORCH} torchvision==${TORCHVISION}

WORKDIR /opt/ComfyUI
RUN curl -fsSL https://codeload.github.com/Comfy-Org/ComfyUI/tar.gz/${COMFYUI_COMMIT} \
        | tar -xz --strip-components=1 \
 && mkdir -p custom_nodes/ComfyUI-GGUF \
 && curl -fsSL https://codeload.github.com/city96/ComfyUI-GGUF/tar.gz/${GGUF_COMMIT} \
        | tar -xz --strip-components=1 -C custom_nodes/ComfyUI-GGUF \
 && pip install --no-cache-dir -r requirements.txt -r custom_nodes/ComfyUI-GGUF/requirements.txt \
        torch==${TORCH} torchvision==${TORCHVISION} \
        --extra-index-url https://download.pytorch.org/whl/cu128

COPY extra_model_paths.yaml /opt/ComfyUI/extra_model_paths.yaml

# uid 1000 = bill on this host, so outputs land owned by him.
RUN useradd -u 1000 -m comfy && mkdir -p /data/output /data/user /data/input /data/temp \
 && chown -R comfy /data /opt/ComfyUI
USER comfy

# No network at run time: the models are mounted, and the hubs are told not to look.
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1

EXPOSE 8188
ENTRYPOINT ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", \
            "--output-directory", "/data/output", "--input-directory", "/data/input", \
            "--temp-directory", "/data/temp", "--user-directory", "/data/user", \
            "--offline", "--disable-auto-launch"]
