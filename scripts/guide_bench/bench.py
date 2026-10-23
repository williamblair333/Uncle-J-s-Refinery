#!/usr/bin/env python3
"""Benchmark: does a smaller jcodemunch guide still route requests to the right tool?

Three variants of the `jcodemunch-mcp claude-md --generate` snippet (the same text
`jcodemunch_guide` returns):
  full     — as shipped
  compact  — deterministic: the "### All tools" catalogue removed (the MCP tool
             registry already gives the model every name)
  llm      — the full snippet compressed by the local model (ask_local backend)

For each variant, the local model acts as router on 20 requests (queries.json): it
gets the tool-name registry, the guide variant and one request, and must answer with
one tool name. Every variant gets the same registry, because a real session always
has it. Tokens are counted with the local model's tokenizer.

    .venv/bin/python scripts/guide_bench/bench.py [--out results.json]

Needs the ask_local backend up (`just ask-local-up`). Exit 2 if it isn't.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import httpx  # noqa: E402

from scripts.ask_local.server import OLLAMA_URL, LocalClient  # noqa: E402

QUERIES = Path(__file__).with_name("queries.json")
JCODEMUNCH = REPO / ".venv" / "bin" / "jcodemunch-mcp"
TOOL_RE = re.compile(r"`([a-z][a-z0-9_]+)`")

COMPRESS_SYSTEM = (
    "You compress technical instructions for an AI coding agent. Keep every rule and "
    "every tool name exactly as written (backticked). Drop filler words, repetition and "
    "formatting that carries no meaning. Output only the compressed text."
)
ROUTE_SYSTEM = (
    "You route a developer request to one tool. Reply with exactly one tool name from "
    "the registry and nothing else."
)


def full_guide() -> str:
    return subprocess.run([str(JCODEMUNCH), "claude-md", "--generate"], check=True,
                          capture_output=True, text=True).stdout


def compact_guide(full: str) -> str:
    """Drop the '### All tools' section: header through the line before the closing note."""
    out, skipping = [], False
    for line in full.splitlines():
        if line.startswith("### All tools"):
            skipping = True
            continue
        if skipping and (line.startswith("### ") or line.startswith("The built-in tools")):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out).rstrip() + "\n"


def registry(full: str) -> list[str]:
    seen: list[str] = []
    for name in TOOL_RE.findall(full):
        if name not in seen:
            seen.append(name)
    return seen


def count_tokens(http: httpx.Client, text: str) -> int | None:
    try:
        r = http.post("/tokenize", json={"content": text}, timeout=30)
        r.raise_for_status()
        return len(r.json()["tokens"])
    except (httpx.HTTPError, KeyError, ValueError):
        return None  # Ollama has no /tokenize; reported as unknown, never guessed


def missing_names(text: str, names: list[str]) -> list[str]:
    return [n for n in names if n not in text]


def route(rail: LocalClient, names: list[str], guide: str, q: str) -> str:
    prompt = (f"Tool registry: {', '.join(names)}\n\nGuide:\n{guide}\n\n"
              f"Request: {q}\nTool:")
    res = rail.chat("guide_bench_route", prompt, system=ROUTE_SYSTEM, max_tokens=24,
                    temperature=0)
    if "error" in res:
        return f"ERROR:{res['error']}"
    words = re.findall(r"[a-z][a-z0-9_]+", res["text"].lower())
    return next((w for w in words if w in names), res["text"].strip()[:40])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    rail = LocalClient(httpx.Client(base_url=OLLAMA_URL))
    if "error" in rail.chat("guide_bench_ping", "Reply OK.", max_tokens=4):
        print("ask_local backend is down — run `just ask-local-up`", file=sys.stderr)
        return 2

    full = full_guide()
    names = registry(full)
    comp = rail.chat("guide_bench_compress", full, system=COMPRESS_SYSTEM, max_tokens=900,
                     temperature=0)
    if "error" in comp:
        print(f"compression failed: {comp}", file=sys.stderr)
        return 1
    variants = {"full": full, "compact": compact_guide(full), "llm": comp["text"].strip() + "\n"}

    queries = json.loads(QUERIES.read_text())
    results: dict = {"registry_size": len(names), "variants": {}}
    for label, text in variants.items():
        picks = [route(rail, names, text, item["q"]) for item in queries]
        correct = [p in item["ok"] for p, item in zip(picks, queries)]
        results["variants"][label] = {
            "chars": len(text),
            "tokens": count_tokens(rail.http, text),
            "tool_names_missing": missing_names(text, names) if label == "llm" else [],
            "correct": sum(correct),
            "of": len(queries),
            "misses": [{"q": item["q"], "picked": p, "ok": item["ok"]}
                       for p, item, c in zip(picks, queries, correct) if not c],
        }
    results["llm_text"] = variants["llm"]

    blob = json.dumps(results, indent=2)
    if args.out:
        args.out.write_text(blob + "\n")
    print(json.dumps({k: {kk: v[kk] for kk in ("chars", "tokens", "correct", "of")}
                      for k, v in results["variants"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
