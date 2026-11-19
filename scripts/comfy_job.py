#!/usr/bin/env python3
"""Queue one ComfyUI job and wait for it: `just image "prompt"` / `just video "prompt"`.

Builds the workflow in API format (Z-Image-Turbo for images, Wan 2.2 T2V A14B GGUF with
the lightx2v 4-step LoRAs for video), POSTs it to ComfyUI's /prompt, polls /history until
it finishes, and prints the output files (host paths under /opt/outputs/comfyui), the wall
time, and the peak VRAM seen while it ran (whole GPU, and ComfyUI's own process).

If ComfyUI isn't running it starts it (`scripts/comfy.sh up -d`, through dcup) after any
wait for Klarheit, and stops it again when the job ends, so an idle ComfyUI never holds the
GPU. --keep-up leaves it running; --no-autostart restores "exit 2 if it isn't up".

Stdlib only, so it runs with the system python3.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import signal
import subprocess
import fcntl
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8188"
OUTPUT_ROOT = Path("/opt/outputs/comfyui")
HERETIC_CONTAINER = "llama-heretic"
COMFY_SH = Path(__file__).resolve().parent / "comfy.sh"

IMAGE_MODELS = {
    "unet": "z_image_turbo_bf16.safetensors",
    "clip": "qwen_3_4b_fp8_mixed.safetensors",
    "vae": "ae.safetensors",
}
# FLUX.2 [klein] 4B (Apache 2.0) for reference-based editing. The text encoder is Z-Image's:
# both use the same Qwen3-4B (docker/comfyui/models.txt).
EDIT_MODELS = {
    "unet": "flux-2-klein-4b-fp8.safetensors",
    "clip": IMAGE_MODELS["clip"],
    "vae": "flux2-vae.safetensors",
}
MAX_REFS = 4
# Qwen-Image-Edit-2511 (Apache 2.0): keeps several characters' faces and outfits apart far
# better than klein, at ~3 min an image, ~11 GB VRAM and ~12 GB of RAM for the offloaded
# weights. Its text encoder takes at most 3 pictures.
QWEN_MODELS = {
    "unet": "qwen-image-edit-2511-Q4_K_M.gguf",
    "lora": "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
    "clip": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
    "vae": "qwen_image_vae.safetensors",
}
QWEN_MAX_REFS = 3
QWEN_REF_MEGAPIXELS = 0.6
# Free RAM (MemAvailable) a job needs before it starts. 2026-11-17: a Qwen batch run with
# --ignore-klarheit beside Klarheit's Ollama 9B filled the 46 GB host and its swap (load 69,
# desktop froze). So Qwen also always waits for Klarheit, --ignore-klarheit or not.
MIN_FREE_RAM_GIB = {"qwen": 20}
VIDEO_MODELS = {
    "high": "Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf",
    "low": "Wan2.2-T2V-A14B-LowNoise-Q4_K_M.gguf",
    "lora_high": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
    "lora_low": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors",
    "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "vae": "wan_2.1_vae.safetensors",
}
# Wan's stock negative prompt (Chinese, from the Wan 2.2 ComfyUI template). With cfg 1 the
# lightx2v LoRAs ignore it, but the sampler still needs a negative input.
WAN_NEGATIVE = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
                "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
                "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，"
                "杂乱的背景，三条腿，背景人很多，倒着走")


REF_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_DENOISE = 0.6   # with a reference: lower keeps more of it, higher follows the prompt
SIZE_STEP, SIZE_MIN, SIZE_MAX = 16, 256, 2048   # Z-Image latents: 8x VAE, then 2x2 patches


def image_workflow(prompt: str, seed: int, width: int | None = None, height: int | None = None,
                   steps: int = 9, prefix: str = "image", ref_image: str | None = None,
                   denoise: float = DEFAULT_DENOISE) -> dict:
    """Z-Image-Turbo text-to-image, per the ComfyUI template (cfg 1, res_multistep, shift 3).

    With ref_image (a file name in ComfyUI's input folder, see upload_image) it is img2img:
    the reference is scaled, VAE-encoded and sampled from at `denoise` instead of 1.0. That
    keeps the reference's layout and colours; it does not carry a character into a new pose.
    Without width/height the reference keeps its aspect ratio at ~1 megapixel, sides snapped
    to 16 (ImageScaleToTotalPixels' resolution_steps, present in ComfyUI v0.39.0).
    """
    wf = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": IMAGE_MODELS["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": IMAGE_MODELS["clip"], "type": "lumina2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": IMAGE_MODELS["vae"]}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": width or 1024, "height": height or 1024, "batch_size": 1}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["4", 0], "seed": seed, "steps": steps, "cfg": 1.0,
                         "sampler_name": "res_multistep", "scheduler": "simple",
                         "positive": ["5", 0], "negative": ["6", 0],
                         "latent_image": ["7", 0], "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": prefix}},
    }
    if ref_image is None:
        return wf
    wf["11"] = {"class_type": "LoadImage", "inputs": {"image": ref_image}}
    if width and height:
        wf["12"] = {"class_type": "ImageScale",
                    "inputs": {"image": ["11", 0], "upscale_method": "lanczos",
                               "width": width, "height": height, "crop": "center"}}
    else:
        wf["12"] = {"class_type": "ImageScaleToTotalPixels",
                    "inputs": {"image": ["11", 0], "upscale_method": "lanczos",
                               "megapixels": 1.0, "resolution_steps": SIZE_STEP}}
    wf["7"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["12", 0], "vae": ["3", 0]}}
    wf["8"]["inputs"]["denoise"] = denoise
    return wf


def edit_workflow(prompt: str, seed: int, refs: list[str], width: int | None = None,
                  height: int | None = None, steps: int = 4, prefix: str = "edit") -> dict:
    """FLUX.2 [klein] 4B multi-reference edit, per ComfyUI's image_flux2_klein_image_edit_4b
    template (distilled: 4 steps, cfg 1, euler).

    refs are file names in ComfyUI's input folder (upload_image), referred to in the prompt as
    image 1, image 2, ... Each is scaled to ~1 megapixel, VAE-encoded and attached to both the
    prompt and the zeroed negative with ReferenceLatent. Without width/height the output takes
    the first reference's size.
    """
    wf = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": EDIT_MODELS["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": EDIT_MODELS["clip"], "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": EDIT_MODELS["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
    }
    pos, neg = ["4", 0], ["5", 0]
    for i, name in enumerate(refs):
        load, scale, enc, rp, rn = (f"r{i}{k}" for k in "lsepn")
        wf[load] = {"class_type": "LoadImage", "inputs": {"image": name}}
        wf[scale] = {"class_type": "ImageScaleToTotalPixels",
                     "inputs": {"image": [load, 0], "upscale_method": "lanczos",
                                "megapixels": 1.0, "resolution_steps": SIZE_STEP}}
        wf[enc] = {"class_type": "VAEEncode", "inputs": {"pixels": [scale, 0], "vae": ["3", 0]}}
        wf[rp] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": pos, "latent": [enc, 0]}}
        wf[rn] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": neg, "latent": [enc, 0]}}
        pos, neg = [rp, 0], [rn, 0]
    if width and height:
        w, h = width, height
    else:
        wf["6"] = {"class_type": "GetImageSize", "inputs": {"image": ["r0s", 0]}}
        w, h = ["6", 0], ["6", 1]
    wf.update({
        "7": {"class_type": "EmptyFlux2LatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "8": {"class_type": "Flux2Scheduler", "inputs": {"steps": steps, "width": w, "height": h}},
        "9": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "10": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "11": {"class_type": "CFGGuider",
               "inputs": {"model": ["1", 0], "positive": pos, "negative": neg, "cfg": 1.0}},
        "12": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["9", 0], "guider": ["11", 0], "sampler": ["10", 0],
                          "sigmas": ["8", 0], "latent_image": ["7", 0]}},
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}},
        "14": {"class_type": "SaveImage", "inputs": {"images": ["13", 0], "filename_prefix": prefix}},
    })
    return wf


def qwen_workflow(prompt: str, seed: int, refs: list[str], width: int | None = None,
                  height: int | None = None, steps: int = 4, prefix: str = "qwen") -> dict:
    """Qwen-Image-Edit-2511, per ComfyUI's image_qwen_image_edit_2511 template, with the
    Lightning 4-step LoRA (cfg 1). The prompt calls the references Picture 1, 2, 3."""
    wf = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": QWEN_MODELS["unet"]}},
        "1l": {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["1", 0], "lora_name": QWEN_MODELS["lora"],
                          "strength_model": 1.0}},
        "1s": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1l", 0], "shift": 3.1}},
        "1n": {"class_type": "CFGNorm", "inputs": {"model": ["1s", 0], "strength": 1.0}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": QWEN_MODELS["clip"], "type": "qwen_image",
                         "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": QWEN_MODELS["vae"]}},
    }
    images = {}
    for i, name in enumerate(refs[:QWEN_MAX_REFS]):
        wf[f"r{i}l"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        wf[f"r{i}s"] = {"class_type": "ImageScaleToTotalPixels",
                        "inputs": {"image": [f"r{i}l", 0], "upscale_method": "lanczos",
                                   "megapixels": QWEN_REF_MEGAPIXELS, "resolution_steps": 16}}
        images[f"image{i + 1}"] = [f"r{i}s", 0]
    for key, text in (("p", prompt), ("n", "")):
        wf[f"t{key}"] = {"class_type": "TextEncodeQwenImageEditPlus",
                         "inputs": {"clip": ["2", 0], "prompt": text, "vae": ["3", 0], **images}}
        wf[f"m{key}"] = {"class_type": "FluxKontextMultiReferenceLatentMethod",
                         "inputs": {"conditioning": [f"t{key}", 0],
                                    "reference_latents_method": "index_timestep_zero"}}
    wf.update({
        "7": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": width or 1024, "height": height or 1024, "batch_size": 1}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["1n", 0], "positive": ["mp", 0], "negative": ["mn", 0],
                         "latent_image": ["7", 0], "seed": seed, "steps": steps, "cfg": 1.0,
                         "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": prefix}},
    })
    return wf


# ── --region: fix one part of a picture, leave every other pixel alone ─────────────────
# The model only ever sees a crop. Its output is scaled back to the crop's size and pasted
# onto the original through a mask that is 0 on the box's border and ramps up to 255 inside,
# so pixels outside the box are copied, never redrawn, and the seam fades. Pillow is needed
# for this mode only (the system python3 has it; the rest of this file stays stdlib).
REGION_MEGAPIXELS = 1.0


def parse_region(text: str) -> tuple[int, int, int, int]:
    """'X,Y,W,H' in pixels of the original picture."""
    parts = text.replace(" ", "").split(",")
    if len(parts) != 4:
        raise ValueError(f"--region {text!r}: want X,Y,W,H")
    try:
        x, y, w, h = (int(p) for p in parts)
    except ValueError:
        raise ValueError(f"--region {text!r}: want four whole numbers X,Y,W,H") from None
    if x < 0 or y < 0 or w < 32 or h < 32:
        raise ValueError(f"--region {text!r}: X and Y must be 0 or more, W and H at least 32")
    return x, y, w, h


def region_problem(region: tuple[int, int, int, int], size: tuple[int, int]) -> str | None:
    x, y, w, h = region
    if x + w > size[0] or y + h > size[1]:
        return (f"--region {x},{y},{w},{h} runs past the picture's edge "
                f"({size[0]}×{size[1]})")
    return None


def region_gen_size(w: int, h: int, megapixels: float = REGION_MEGAPIXELS) -> tuple[int, int]:
    """Size to generate the crop at: its aspect ratio, about `megapixels`, multiples of 16."""
    scale = (megapixels * 1e6 / (w * h)) ** 0.5
    return (max(256, round(w * scale / 16) * 16), max(256, round(h * scale / 16) * 16))


def default_feather(w: int, h: int) -> int:
    return max(4, min(w, h) // 8)


def feather_mask(w: int, h: int, feather: int):
    """L-mode mask: 0 on the border, rising linearly to 255 `feather` px in."""
    from PIL import Image, ImageChops

    def ramp(n: int) -> list[int]:
        if feather <= 0:
            return [255] * n
        return [min(255, round(255 * min(i, n - 1 - i) / feather)) for i in range(n)]
    cols = Image.new("L", (w, 1))
    cols.putdata(ramp(w))
    rows = Image.new("L", (1, h))
    rows.putdata(ramp(h))
    return ImageChops.darker(cols.resize((w, h), Image.NEAREST),
                             rows.resize((w, h), Image.NEAREST))


def crop_region(src: Path, region: tuple[int, int, int, int], dest: Path) -> Path:
    from PIL import Image
    x, y, w, h = region
    with Image.open(src) as im:
        im.convert("RGB").crop((x, y, x + w, y + h)).save(dest)
    return dest


def paste_region(original: Path, patch: Path, region: tuple[int, int, int, int],
                 feather: int, dest: Path) -> None:
    """Write original + patch (scaled to the box) to dest; refuse to overwrite."""
    from PIL import Image
    x, y, w, h = region
    if dest.exists():
        raise FileExistsError(f"{dest} exists; not overwriting it")
    with Image.open(original) as orig, Image.open(patch) as p:
        out = orig.copy()
        fitted = p.convert(out.mode).resize((w, h), Image.LANCZOS)
        out.paste(fitted, (x, y), feather_mask(w, h, feather))
        out.save(dest)


def outside_unchanged(a: Path, b: Path, region: tuple[int, int, int, int]) -> bool:
    """True when a and b have the same pixels everywhere outside the box."""
    from PIL import Image, ImageChops
    x, y, w, h = region
    with Image.open(a) as ia, Image.open(b) as ib:
        if ia.size != ib.size or ia.mode != ib.mode:
            return False
        diff = ImageChops.difference(ia.convert("RGBA"), ib.convert("RGBA"))
    diff.paste((0, 0, 0, 0), (x, y, x + w, y + h))
    # getbbox() on RGBA looks at alpha only by default, which would miss colour changes.
    return diff.getbbox(alpha_only=False) is None


def region_out_path(scene: Path, seed: int) -> Path:
    return scene.with_name(f"{scene.stem}.region-{seed}.png")


# One comfy_job at a time. Two runs waiting on the same Klarheit trial both passed the RAM
# gate together and shared one ComfyUI; the one that started it stopped it under the other.
LOCK_PATH = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "comfy_job.lock"


def hold_lock(path: Path | None = None):
    """Block until no other comfy_job run holds the lock; the returned file keeps it (the
    kernel releases it when this process exits, however it exits)."""
    f = open(path or LOCK_PATH, "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("waiting: another comfy_job run is using ComfyUI", file=sys.stderr)
        fcntl.flock(f, fcntl.LOCK_EX)
    return f


def ram_available_gib(meminfo: Path = Path("/proc/meminfo")) -> float | None:
    """MemAvailable in GiB, or None where /proc/meminfo can't be read (not Linux)."""
    try:
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 2**20
    except (OSError, ValueError, IndexError):
        pass
    return None


def ram_problem(model: str, available: float | None) -> str | None:
    """Why there isn't enough free RAM to start this model now, or None if it may start."""
    need = MIN_FREE_RAM_GIB.get(model)
    if need is None or available is None or available >= need:
        return None
    return (f"{model} needs {need} GiB of free RAM and only {available:.1f} GiB is available; "
            "stop other models (Ollama, llama-heretic) or try again after Klarheit's trial")


OLLAMA_URL = "http://127.0.0.1:11434"


def unload_ollama(url: str = OLLAMA_URL, http=None) -> list[str]:
    """Unload every model Ollama holds in memory (keep_alive 0); return their names.

    Ollama keeps Klarheit's 9B resident between trials (~7 GiB of RAM). The service keeps
    running and reloads the model on its next request, a few seconds. Callers must have
    checked that no Klarheit trial is running or due. [] if Ollama can't be reached."""
    http = http or _http
    try:
        names = [m["name"] for m in http(f"{url}/api/ps", timeout=5).get("models", [])]
        for name in names:
            http(f"{url}/api/generate", {"model": name, "keep_alive": 0}, timeout=30)
    except (urllib.error.URLError, OSError, KeyError, TypeError, ValueError):
        return []
    return names


def free_ram_for(model: str, unload=None, available=None, sleep=time.sleep,
                 wait: float = 15) -> str | None:
    """The RAM gate, unloading Ollama's idle models first if that's what it takes.

    Returns why the model still can't start, or None if it may."""
    unload = unload or unload_ollama
    available = available or ram_available_gib
    if not ram_problem(model, available()):
        return None
    freed = unload()
    if freed:
        print(f"unloaded Ollama's idle {', '.join(freed)} to free RAM "
              "(it reloads at its next request)", file=sys.stderr)
        for _ in range(int(wait)):
            if not ram_problem(model, available()):
                return None
            sleep(1)
    return ram_problem(model, available())


def pick_model(model: str, refs: list) -> str:
    """'auto' edits with klein when references are given, else Z-Image text-to-image."""
    if model != "auto":
        return model
    return "klein" if refs else "z-image"


def check_size(value: int | None) -> str | None:
    """Why a width/height is unusable for Z-Image, or None if it's fine."""
    if value is None:
        return None
    if not SIZE_MIN <= value <= SIZE_MAX or value % SIZE_STEP:
        return (f"{value} px: sides must be a multiple of {SIZE_STEP} "
                f"between {SIZE_MIN} and {SIZE_MAX}")
    return None


def check_ref(path: Path) -> str | None:
    """Why a reference image can't be used, or None if it can."""
    if path.suffix.lower() not in REF_SUFFIXES:
        return f"{path}: reference must be one of {', '.join(sorted(REF_SUFFIXES))}"
    if not path.is_file():
        return f"{path}: no such file"
    return None


def upload_image(url: str, path: Path, timeout: float = 60) -> str:
    """Copy a local image into ComfyUI's input folder (POST /upload/image); return its name.

    Named by content hash, so two jobs never swap references and a repeat upload is a no-op.
    """
    data = path.read_bytes()
    name = f"ref-{hashlib.sha256(data).hexdigest()[:12]}{path.suffix.lower()}"
    boundary = f"----comfyjob{uuid.uuid4().hex}"
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n"
        .encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n".encode(),
        data, f"\r\n--{boundary}--\r\n".encode()])
    req = urllib.request.Request(f"{url}/upload/image", data=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read() or b"{}")
    sub = out.get("subfolder") or ""
    return f"{sub}/{out['name']}" if sub else out["name"]


def video_workflow(prompt: str, seed: int, width: int = 832, height: int = 480,
                   frames: int = 81, fps: int = 16, steps: int = 4,
                   prefix: str = "video") -> dict:
    """Wan 2.2 T2V A14B: high-noise expert for the first half of the steps, low-noise after.

    Per the ComfyUI Wan 2.2 14B template with the lightx2v 4-step LoRAs (cfg 1, shift 5).
    """
    split = steps // 2
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": VIDEO_MODELS["high"]}},
        "2": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": VIDEO_MODELS["low"]}},
        "3": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["1", 0], "lora_name": VIDEO_MODELS["lora_high"],
                         "strength_model": 1.0}},
        "4": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["2", 0], "lora_name": VIDEO_MODELS["lora_low"],
                         "strength_model": 1.0}},
        "5": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["3", 0], "shift": 5.0}},
        "6": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["4", 0], "shift": 5.0}},
        "7": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": VIDEO_MODELS["clip"], "type": "wan", "device": "default"}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["7", 0]}},
        "9": {"class_type": "CLIPTextEncode", "inputs": {"text": WAN_NEGATIVE, "clip": ["7", 0]}},
        "10": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_MODELS["vae"]}},
        "11": {"class_type": "EmptyHunyuanLatentVideo",
               "inputs": {"width": width, "height": height, "length": frames, "batch_size": 1}},
        "12": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["5", 0], "add_noise": "enable", "noise_seed": seed,
                          "steps": steps, "cfg": 1.0, "sampler_name": "euler",
                          "scheduler": "simple", "positive": ["8", 0], "negative": ["9", 0],
                          "latent_image": ["11", 0], "start_at_step": 0, "end_at_step": split,
                          "return_with_leftover_noise": "enable"}},
        "13": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["6", 0], "add_noise": "disable", "noise_seed": seed,
                          "steps": steps, "cfg": 1.0, "sampler_name": "euler",
                          "scheduler": "simple", "positive": ["8", 0], "negative": ["9", 0],
                          "latent_image": ["12", 0], "start_at_step": split,
                          "end_at_step": 10000, "return_with_leftover_noise": "disable"}},
        "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["10", 0]}},
        "15": {"class_type": "CreateVideo", "inputs": {"images": ["14", 0], "fps": float(fps)}},
        "16": {"class_type": "SaveVideo",
               # format/codec are nested "dynamic combo" inputs, addressed as "parent.child"
               # in API format; auto + h264 writes an .mp4.
               "inputs": {"video": ["15", 0], "filename_prefix": prefix,
                          "format": "auto", "format.codec": "h264"}},
    }


def output_files(history: dict, prompt_id: str, root: Path = OUTPUT_ROOT) -> list[Path]:
    """Host paths of every saved output in a /history/<id> response.

    ComfyUI lists them per node under images/gifs/videos/... as {filename, subfolder, type};
    only type "output" lands in the mounted output directory.
    """
    entry = history.get(prompt_id) or {}
    paths = []
    for node_out in (entry.get("outputs") or {}).values():
        for items in node_out.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("type") == "output" and item.get("filename"):
                    paths.append(root / item.get("subfolder", "") / item["filename"])
    return paths


def job_finished(history: dict, prompt_id: str) -> bool:
    """ComfyUI adds the id to /history only when the job ends, success or error."""
    status = (history.get(prompt_id) or {}).get("status") or {}
    return bool(status.get("completed")) or status.get("status_str") == "error"


def job_error(history: dict, prompt_id: str) -> str | None:
    """The failure message of a finished job, or None if it succeeded."""
    status = (history.get(prompt_id) or {}).get("status") or {}
    if status.get("status_str") != "error":
        return None
    for kind, data in status.get("messages") or []:
        if kind == "execution_error":
            return f"{data.get('node_type')}: {data.get('exception_message', '').strip()}"
    return "job failed (no execution_error message)"


def _http(url: str, payload: dict | None = None, timeout: float = 30) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


# Klarheit's pre-registered trials call Ollama's qwen3.5:9b with a 120 s per-session timeout
# (Klarheit src/klarheit/rv/viewer.py). A video job overlapping the 16:05 trial on 2026-10-23
# pushed its slowest session to 101.4 s (45.6 s the hour before), so jobs keep out of the way:
# never start while a trial runs, and never start one that would still be running when the
# next trial begins. Trials: klarheit-rv hourly at :05, klarheit-m12 at 10:35 and 20:35.
KLARHEIT_UNITS = ("klarheit-rv.service", "klarheit-m12.service")
EXPECTED_MIN = {"image": 3, "video": 12, "qwen": 6}   # generous upper bounds, with model loading


def next_trial(now) -> "datetime.datetime":
    """The next Klarheit trial start strictly after `now` (naive local time)."""
    import datetime as dt
    base = now.replace(second=0, microsecond=0)
    hourly = base.replace(minute=5)
    if hourly <= now:
        hourly += dt.timedelta(hours=1)
    cands = [hourly]
    for day in (0, 1):
        for hh in (10, 20):
            t = (base + dt.timedelta(days=day)).replace(hour=hh, minute=35)
            if t > now:
                cands.append(t)
    return min(cands)


def klarheit_running(run=subprocess.run) -> bool:
    try:
        out = run(["systemctl", "--user", "is-active", *KLARHEIT_UNITS],
                  capture_output=True, text=True, timeout=10).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return False
    return any(s in ("active", "activating") for s in out)


def klarheit_wait_reason(kind: str, now, running: bool) -> str | None:
    """Why a job must wait for Klarheit now, or None if it may start."""
    if running:
        return "a Klarheit trial is running"
    start = next_trial(now)
    if (start - now).total_seconds() < EXPECTED_MIN[kind] * 60:
        return f"the next Klarheit trial starts at {start:%H:%M}"
    return None


def wait_for_klarheit(kind: str, max_wait: float, sleep=time.sleep, clock=None,
                      running=klarheit_running) -> bool:
    """Block until the job can run without overlapping a trial. False if max_wait passes."""
    import datetime as dt
    clock = clock or dt.datetime.now
    waited = 0.0
    while (reason := klarheit_wait_reason(kind, clock(), running())):
        if waited >= max_wait:
            return False
        if waited == 0:
            print(f"waiting: {reason} (Klarheit's calls time out at 120 s; "
                  "--ignore-klarheit skips this)", file=sys.stderr)
        sleep(30)
        waited += 30
    return True


def free_vram(url: str) -> bool:
    """Ask ComfyUI to unload its models and release cached VRAM (POST /free)."""
    try:
        req = urllib.request.Request(f"{url}/free", method="POST",
                                     data=json.dumps({"unload_models": True,
                                                      "free_memory": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError) as exc:
        print(f"warning: could not unload ComfyUI's models ({exc}); "
              "`just comfy down` frees the GPU", file=sys.stderr)
        return False


class VramSampler(threading.Thread):
    """Peak GPU memory in MiB, polled once a second: whole GPU and one host PID."""

    def __init__(self, pid: int | None):
        super().__init__(daemon=True)
        self.pid, self.peak_total, self.peak_proc = pid, 0, 0
        # Not `_stop`: Python 3.11's Thread.join() calls its own self._stop().
        self._halt = threading.Event()

    def run(self):
        if not shutil.which("nvidia-smi"):
            return
        while not self._halt.is_set():
            self.peak_total = max(self.peak_total, _gpu_used_mib())
            if self.pid:
                self.peak_proc = max(self.peak_proc, _proc_used_mib(self.pid))
            self._halt.wait(1)

    def stop(self):
        self._halt.set()
        self.join(timeout=5)


def _nvsmi(*args: str) -> str:
    try:
        return subprocess.run(["nvidia-smi", *args, "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _gpu_used_mib() -> int:
    out = _nvsmi("--query-gpu=memory.used").strip().splitlines()
    return int(out[0]) if out and out[0].strip().isdigit() else 0


def gpu_apps() -> dict[int, tuple[str, int]]:
    """{pid: (process name, MiB)} for every compute process on the GPU."""
    apps = {}
    for line in _nvsmi("--query-compute-apps=pid,process_name,used_memory").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[0].isdigit() and parts[2].isdigit():
            apps[int(parts[0])] = (parts[1], int(parts[2]))
    return apps


def _proc_used_mib(pid: int) -> int:
    return gpu_apps().get(pid, ("", 0))[1]


def container_pid(name: str = "comfyui") -> int | None:
    try:
        out = subprocess.run(["docker", "inspect", "-f", "{{.State.Pid}}", name],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return int(out) if out.isdigit() and out != "0" else None


def gpu_warnings(apps: dict[int, tuple[str, int]]) -> list[str]:
    """What else holds the GPU. Heretic can be stopped; Ollama serves Klarheit — leave it.

    (Qwen jobs may unload Ollama's idle model to free RAM — see free_ram_for — but never
    stop the service.)"""
    notes = []
    for name, mib in apps.values():
        if "llama-server" in name:
            notes.append(f"llama-heretic is awake on the GPU ({mib} MiB); it auto-fits to "
                         "free VRAM, so it is parked for this job and restarted after.")
        elif "ollama" in name:
            notes.append(f"Ollama holds {mib} MiB (Klarheit's trials); ComfyUI offloads around it.")
    return notes


def heretic_on_gpu(apps: dict[int, tuple[str, int]]) -> bool:
    return any("llama-server" in name for name, _ in apps.values())


def _docker(*args: str) -> bool:
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True,
                              timeout=120).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _exit_on_signal(signum: int, _frame) -> None:
    # SIGTERM/SIGHUP skip `finally` by default, which would leave Heretic parked for good
    # (its restart policy is unless-stopped).
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kind", choices=["image", "video"])
    ap.add_argument("prompt")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--steps", type=int)
    ap.add_argument("--frames", type=int, default=81, help="video only; 81 = 5 s at 16 fps")
    ap.add_argument("--ref", type=Path, action="append", default=[],
                    help=f"image only, repeatable (up to {MAX_REFS}): reference picture(s). With "
                         "klein the prompt calls them image 1, image 2, ... and can put their "
                         "characters in a new scene; with z-image (one ref) it is img2img")
    ap.add_argument("--model", choices=["auto", "z-image", "klein", "qwen"], default="auto",
                    help="auto (default): klein when --ref is given, else z-image. qwen: "
                         "Qwen-Image-Edit-2511, 1-3 refs called Picture 1-3, keeps several "
                         "characters apart better; ~3 min, needs 20 GiB free RAM and always "
                         "waits for Klarheit")
    ap.add_argument("--denoise", type=float, default=DEFAULT_DENOISE,
                    help=f"z-image with --ref: 0-1, how far to move from it "
                         f"(default {DEFAULT_DENOISE})")
    ap.add_argument("--region", metavar="X,Y,W,H",
                    help="qwen only: change just this box of the first --ref. The model sees "
                         "the crop as Picture 1 (later refs are Picture 2-3, e.g. a face "
                         "reference); the result is pasted back through a feathered mask and "
                         "every pixel outside the box is copied unchanged")
    ap.add_argument("--feather", type=int,
                    help="--region: px of fade inside the box's edge (default: 1/8 of its "
                         "shorter side)")
    ap.add_argument("--out", type=Path,
                    help="--region: where to write the result (default: next to the first "
                         "--ref as <name>.region-<seed>.png); never overwrites")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--timeout", type=float, default=3600, help="seconds to wait for the job")
    ap.add_argument("--keep-loaded", action="store_true",
                    help="leave the models in VRAM after the job (default: unload them, so an "
                         "idle ComfyUI doesn't crowd out Heretic and Ollama)")
    ap.add_argument("--ignore-klarheit", action="store_true",
                    help="start even if it would overlap a Klarheit trial (can make its "
                         "Ollama calls time out)")
    ap.add_argument("--keep-heretic", action="store_true",
                    help="don't stop llama-heretic for the job (it auto-fits to free VRAM, "
                         "so the job usually fails for lack of memory)")
    ap.add_argument("--keep-up", action="store_true",
                    help="leave ComfyUI running after the job if this job started it")
    ap.add_argument("--no-autostart", action="store_true",
                    help="exit 2 instead of starting ComfyUI when it isn't running")
    args = ap.parse_args(argv)

    seed = args.seed if args.seed is not None else random.randint(0, 2**32 - 1)
    sizes = {k: v for k, v in (("width", args.width), ("height", args.height),
                                ("steps", args.steps)) if v is not None}
    problems = []
    if not 0 <= seed < 2**64:
        problems.append(f"--seed {seed}: ComfyUI takes 0 to 2^64-1")
    if args.kind == "image":
        problems += [p for p in (check_size(args.width), check_size(args.height)) if p]
    region = None
    if args.region:
        if args.model in ("auto", "qwen"):
            args.model = "qwen"
        else:
            problems.append("--region works with --model qwen only")
        try:
            region = parse_region(args.region)
        except ValueError as exc:
            problems.append(str(exc))
        if not args.ref:
            problems.append("--region needs the picture to fix as the first --ref")
        elif region and not check_ref(args.ref[0]):
            try:
                from PIL import Image
                with Image.open(args.ref[0]) as im:
                    size = im.size
                problems += [p for p in [region_problem(region, size)] if p]
            except ImportError:
                problems.append("--region needs Pillow (python3-pil); the system python3 has it")
                region = None
            except OSError as exc:
                problems.append(f"--ref {args.ref[0]}: can't open it as a picture ({exc})")
        if region and args.ref:
            args.out = args.out or region_out_path(args.ref[0], seed)
            if args.out.exists():
                problems.append(f"--out {args.out} exists; not overwriting it")
            if args.width is None and args.height is None:
                sizes["width"], sizes["height"] = region_gen_size(region[2], region[3])
    elif args.feather is not None or args.out is not None:
        problems.append("--feather and --out go with --region")
    if args.feather is not None and args.feather < 0:
        problems.append(f"--feather {args.feather}: must be 0 or more")
    model = pick_model(args.model, args.ref)
    if args.ref:
        if args.kind != "image":
            problems.append("--ref works for images only")
        else:
            problems += [p for p in map(check_ref, args.ref) if p]
        if not 0 < args.denoise <= 1:
            problems.append(f"--denoise {args.denoise}: must be above 0 and at most 1")
    if model == "z-image" and len(args.ref) > 1:
        problems.append("z-image takes one --ref (img2img); use --model klein for several")
    if model == "klein" and not 1 <= len(args.ref) <= MAX_REFS:
        problems.append(f"klein edits from 1 to {MAX_REFS} --ref pictures")
    if model == "qwen" and (args.kind != "image" or not 1 <= len(args.ref) <= QWEN_MAX_REFS):
        problems.append(f"qwen edits images from 1 to {QWEN_MAX_REFS} --ref pictures")
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        return 2

    def build() -> dict:
        if args.kind == "video":
            return video_workflow(args.prompt, seed, frames=args.frames, prefix="video", **sizes)
        if not args.ref:
            return image_workflow(args.prompt, seed, prefix="image", **sizes)
        uploads = list(args.ref)
        if region:
            uploads[0] = crop_region(args.ref[0], region, Path(tmp.name) / "region-crop.png")
            print(f"region {region[2]}×{region[3]} at {region[0]},{region[1]}; generating it "
                  f"at {sizes['width']}×{sizes['height']}", file=sys.stderr)
        names = [upload_image(args.url, p) for p in uploads]
        for p, n in zip(uploads, names):
            print(f"reference {p} uploaded as {n}", file=sys.stderr)
        if model == "qwen":
            print(f"qwen edit from {len(names)} reference(s)", file=sys.stderr)
            return qwen_workflow(args.prompt, seed, names, prefix="qwen", **sizes)
        if model == "klein":
            print(f"klein edit from {len(names)} reference(s)", file=sys.stderr)
            return edit_workflow(args.prompt, seed, names, prefix="edit", **sizes)
        print(f"z-image img2img, denoise {args.denoise}", file=sys.stderr)
        return image_workflow(args.prompt, seed, prefix="image", ref_image=names[0],
                              denoise=args.denoise, **sizes)

    if args.no_autostart and not comfy_up(args.url):
        print(f"ComfyUI is not answering at {args.url}; start it: just comfy up -d", file=sys.stderr)
        return 2
    lock = hold_lock()  # noqa: F841 — held until this process exits
    if model == "qwen" and args.ignore_klarheit:
        print("note: qwen always waits for Klarheit (its RAM use froze the host on 11-17)",
              file=sys.stderr)
    must_wait = model == "qwen" or not args.ignore_klarheit
    if must_wait and not wait_for_klarheit("qwen" if model == "qwen" else args.kind,
                                           max_wait=3600):
        print("gave up after an hour waiting for Klarheit's trials", file=sys.stderr)
        return 1
    # Only after the Klarheit wait: unloading Ollama's model is safe while no trial is due.
    low_ram = free_ram_for(model)
    if low_ram:
        print(f"error: {low_ram}", file=sys.stderr)
        return 1
    started = False
    if not comfy_up(args.url):
        print("ComfyUI isn't running; starting it (just comfy up -d)…", file=sys.stderr)
        if not start_comfy(args.url):
            return 2
        started = True
    tmp = tempfile.TemporaryDirectory(prefix="comfy-region-")
    args.outputs = []
    try:
        try:
            wf = build()
        except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
            print(f"could not upload the reference to ComfyUI: {exc}", file=sys.stderr)
            return 1
        rc = _with_gpu(args, wf, seed)
        if rc != 0 or not region:
            return rc
        return finish_region(args.ref[0], args.outputs, region, args.feather, args.out)
    finally:
        tmp.cleanup()
        if started and not args.keep_up:
            stop_comfy()


def finish_region(scene: Path, outputs: list[Path], region: tuple[int, int, int, int],
                  feather: int | None, out: Path) -> int:
    """Paste the generated crop back into the scene and prove nothing outside it changed."""
    if not outputs:
        print("error: the job produced no image to paste back", file=sys.stderr)
        return 1
    feather = default_feather(region[2], region[3]) if feather is None else feather
    try:
        paste_region(scene, outputs[0], region, feather, out)
    except (OSError, FileExistsError) as exc:
        print(f"error: could not write {out}: {exc}", file=sys.stderr)
        return 1
    if not outside_unchanged(scene, out, region):
        print(f"error: {out} differs from {scene} outside the region; don't use it",
              file=sys.stderr)
        return 1
    print(out)
    print(f"region pasted (feather {feather} px); outside the box: identical to {scene.name}",
          file=sys.stderr)
    return 0


def comfy_up(url: str) -> bool:
    try:
        _http(f"{url}/system_stats", timeout=5)
        return True
    except (urllib.error.URLError, OSError):
        return False


def start_comfy(url: str, run=subprocess.run, up=comfy_up, sleep=time.sleep,
                wait: float = 240) -> bool:
    """`comfy.sh up -d`, then wait until /system_stats answers."""
    try:
        r = run([str(COMFY_SH), "up", "-d"], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"could not start ComfyUI: {exc}", file=sys.stderr)
        return False
    if r.returncode != 0:
        print(f"could not start ComfyUI:\n{(r.stdout + r.stderr).strip()[-800:]}", file=sys.stderr)
        return False
    for _ in range(int(wait // 3)):
        if up(url):
            return True
        sleep(3)
    print(f"ComfyUI started but didn't answer at {url} within {wait:.0f} s", file=sys.stderr)
    return False


def stop_comfy(run=subprocess.run) -> None:
    try:
        r = run([str(COMFY_SH), "down"], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print("could not stop ComfyUI; run: just comfy down", file=sys.stderr)
    except (OSError, subprocess.TimeoutExpired):
        print("could not stop ComfyUI; run: just comfy down", file=sys.stderr)


def _with_gpu(args: argparse.Namespace, wf: dict, seed: int) -> int:
    apps = gpu_apps()
    for note in gpu_warnings(apps):
        print(f"note: {note}", file=sys.stderr)
    parked = False
    if not args.keep_heretic and heretic_on_gpu(apps):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, _exit_on_signal)
        parked = _docker("stop", HERETIC_CONTAINER)
    try:
        return run_job(args, wf, seed)
    finally:
        if parked and not _docker("start", HERETIC_CONTAINER):
            print(f"could not restart {HERETIC_CONTAINER}; run: just heretic up -d",
                  file=sys.stderr)


def run_job(args: argparse.Namespace, wf: dict, seed: int) -> int:
    sampler = VramSampler(container_pid())
    sampler.start()
    t0 = time.monotonic()
    try:
        prompt_id = _http(f"{args.url}/prompt", {"prompt": wf})["prompt_id"]
    except urllib.error.HTTPError as exc:
        sampler.stop()
        print(f"ComfyUI rejected the workflow: {exc.read().decode(errors='replace')}",
              file=sys.stderr)
        return 1
    print(f"queued {args.kind} {prompt_id} (seed {seed})", file=sys.stderr)

    history: dict = {}
    while time.monotonic() - t0 < args.timeout:
        history = _http(f"{args.url}/history/{prompt_id}")
        if job_finished(history, prompt_id):
            break
        time.sleep(2)
    else:
        sampler.stop()
        print(f"timed out after {args.timeout:.0f} s; the job may still be running", file=sys.stderr)
        return 1
    elapsed = time.monotonic() - t0
    sampler.stop()
    if not args.keep_loaded:
        free_vram(args.url)

    err = job_error(history, prompt_id)
    if err:
        print(f"failed after {elapsed:.1f} s: {err}", file=sys.stderr)
        return 1
    files = output_files(history, prompt_id)
    args.outputs = files
    for f in files:
        print(f)
    print(f"{args.kind}: {elapsed:.1f} s ({elapsed / 60:.1f} min), peak VRAM "
          f"{sampler.peak_proc} MiB ComfyUI / {sampler.peak_total} MiB whole GPU, seed {seed}",
          file=sys.stderr)
    return 0 if files else 1


if __name__ == "__main__":
    sys.exit(main())
