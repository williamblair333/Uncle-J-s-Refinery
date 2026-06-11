# scripts/audit/build_scorecard.py
"""Joins the three collector JSONs into state/payoff-scorecard.md.
Pure assembly — verdicts are intentionally blank; the judgment pass
(human + LLM, in-session) fills them in against the README Mission."""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "state/payoff-audit"


def _fmt_bsig(b: dict) -> str:
    """Format a benefit-signals dict into a readable cell string.

    Nested dicts are summarised as ``key_total=N`` (sum of values) so the
    table cell stays readable without inventing information.
    """
    parts = []
    for k, v in b.items():
        if isinstance(v, dict):
            if v and all(isinstance(x, (int, float)) for x in v.values()):
                parts.append(f"{k}_total={sum(v.values())}")
            else:
                parts.append(f"{k}={v}")
        else:
            parts.append(f"{k}={v}")
    return "; ".join(parts) or "—"


def render(token, maint, bene):
    ids = sorted(set(token.get("components", {})) | set(maint.get("components", {}))
                 | set(bene.get("components", {})))
    lines = [
        f"# Pay-for-itself scorecard — {date.today().isoformat()}",
        "",
        "Mission test: every component must pay for itself against "
        "Right > Cheap-in-total > Inventive > Local — or be removed.",
        "Token figures are estimates (bytes/4). Verdicts are filled by the judgment pass.",
        "",
        "| Component | Always-on est. tokens/session | Commits (90d) | Maint. share | Benefit signals | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for cid in ids:
        t = token.get("components", {}).get(cid, {})
        m = maint.get("components", {}).get(cid, {})
        b = bene.get("components", {}).get(cid, {})
        bsig = _fmt_bsig(b)
        lines.append(f"| {cid} | {t.get('est_tokens', '—')} | {m.get('commits', '—')} | "
                     f"{m.get('maintenance_share', '—')} | {bsig} | |")
    gaps = (token.get("missing") or []) + (bene.get("missing") or [])
    if gaps:
        lines += ["", "## Missing data (collect before judging affected rows)", ""]
        lines += [f"- {g}" for g in gaps]
    return "\n".join(lines) + "\n"


def main():
    inputs = {}
    for name in ("token-cost", "maintenance", "benefits"):
        p = AUDIT / f"{name}.json"
        inputs[name] = json.loads(p.read_text()) if p.exists() else {"components": {}, "missing": [f"{p} not generated"]}
    md = render(inputs["token-cost"], inputs["maintenance"], inputs["benefits"])
    out = REPO / "state/payoff-scorecard.md"
    out.write_text(md)
    print(f"scorecard: {out}")


if __name__ == "__main__":
    main()
