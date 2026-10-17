"""Telegram text and inline keyboards for the scout (parse_mode=HTML).

The facts line is built only from gh Facts. Every external string is HTML-escaped. When a
message runs long, the prose is trimmed; the header, facts line and score line never are.
"""
import html
import json
import re

MAX_LEN = 1200


_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)


def _e(s) -> str:
    return html.escape(str(s or ""), quote=False)


def _no_links(s) -> str:
    # The message carries no links (spec §5); a repo owner's description can.
    return _URL.sub("(link removed)", str(s or ""))


def _facts_line(f) -> str:
    lic = f.license or "no licence"
    date = (f.pushed_at or "")[:10] or "unknown"
    return f"<b>{_e(f.full_name)}</b> · ★{f.stars} · {_e(lic)} · last commit {date}"


def _trim(prose: str, budget: int) -> str:
    if len(prose) <= budget:
        return prose
    cut = prose[:max(budget - 1, 0)]
    m = re.search(r"^(.*[.!?])\s", cut, re.S)
    kept = m.group(1) if m else cut.rstrip()
    # Never end on half an HTML entity ("&am"), which Telegram rejects.
    kept = re.sub(r"&[a-z#0-9]*$", "", kept)
    return kept + "…"


def _assemble(head: list, prose: str, tail: list) -> str:
    fixed = "\n".join(head) + "\n\n" + "\n\n" + "\n".join(tail)
    body = _trim(prose, MAX_LEN - len(fixed))
    return "\n".join(head) + "\n\n" + body + "\n\n" + "\n".join(tail)


def render_find(category: str, status: str, facts, pick: dict, source: str) -> str:
    if source == "inbox":
        top = "🔭 Scout — 📥 from your inbox"
    elif source == "watchlist":
        top = "🔭 Scout — 🔁 new release since your maybe"
    else:
        top = f"🔭 Scout — {_e(category)} ({_e(status)})"
    s = pick["scores"]
    score = (f"Score: tokens {s['tokens']}/5 · accuracy {s['accuracy']}/5 · "
             f"creativity {s['creativity']}/5 · offline {s['offline']}/5")
    prose = "\n\n".join(x for x in (
        _e(_no_links(facts.description)),
        _e(" ".join(p for p in (pick.get("gap", ""), pick.get("take", "")) if p)),
        ("Risk: " + _e(pick["risk"])) if pick.get("risk") else "",
    ) if x)
    return _assemble([top, _facts_line(facts)], prose, [score])


def render_eval(facts, ev: dict) -> str:
    top = f"🔬 Scout evaluation — verdict: <b>{_e(ev['verdict'])}</b>"
    risks = "\n".join("• " + _e(r) for r in ev.get("risks", []))
    prose = "\n\n".join(x for x in (
        _e(ev["summary"]),
        "Trial: " + _e(ev["trial_sketch"]),
        ("Risks:\n" + risks) if risks else "",
    ) if x)
    return _assemble([top, _facts_line(facts)], prose, ["Hand it off for a trial in a session?"])


def send_payload(chat_id: str, text: str, keyboard: str) -> dict:
    """sendMessage body: HTML, buttons, and no link preview cards."""
    return {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "reply_markup": {"inline_keyboard": json.loads(keyboard)}}


def _kb(buttons: list) -> str:
    return json.dumps([[{"text": t, "callback_data": d} for t, d in buttons]],
                      ensure_ascii=False)


def keyboard_find(repo_id: int) -> str:
    return _kb([("✅ Yes, evaluate", f"scout:yes:{repo_id}"),
                ("🤔 Maybe", f"scout:maybe:{repo_id}"),
                ("❌ No", f"scout:no:{repo_id}")])


def keyboard_eval(repo_id: int) -> str:
    return _kb([("✅ Hand off for a trial", f"scout:e-yes:{repo_id}"),
                ("🤔 Maybe", f"scout:e-maybe:{repo_id}"),
                ("❌ No", f"scout:e-no:{repo_id}")])
