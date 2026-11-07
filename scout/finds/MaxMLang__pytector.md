# MaxMLang/pytector

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/MaxMLang/pytector
- Stars: 45 (gh, 2026-11-05)
- Licence: Apache-2.0
- Last commit: 2026-08-10
- Source: discovered · Guardrails and prompt-injection defense (thin)

Easy to use LLM Prompt Injection Detection and Prompt Input Sanitization / Detector Python Package with support for local models, API-based safeguards, safeguard for tool calls, and LangChain guardrails.

## Take

Uncle J doesn't screen untrusted text for indirect prompt injection before it goes back into the model, and that text includes web pages, tool outputs, and the READMEs that scout reads.

Pytector is a Python library that detects prompt injection with local DeBERTa/DistilBERT/ONNX classifiers. Its framework-agnostic ToolOutputGuard and SecurityPipeline return an allow, redact or block decision without needing LangChain. It could sit in a small script or a hook in front of web2md, scout and delegate outputs, running fully offline on CPU. That screening is cheap and costs no Claude tokens.

Risk: Classifier injection detectors have real false-positive and false-negative rates. Treating it as a gate rather than one layer of defence-in-depth could block legitimate content or give false confidence.

Scores: tokens 4/5, accuracy 3/5, creativity 2/5, offline 5/5
