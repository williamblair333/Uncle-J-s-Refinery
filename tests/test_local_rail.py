"""scripts/local_rail.py — content-hash cache over the ask_local client. No model calls:
a fake client counts how often the backend would have been hit."""

import json

from scripts.local_rail import Rail, cache_key


class FakeClient:
    backend, model, http = "openai", "heretic", None

    def __init__(self, reply=None):
        self.calls = 0
        self.reply = reply or {"text": "ok", "model": "heretic", "tokens_in": 3, "tokens_out": 1}

    def chat(self, job, prompt, **kw):
        self.calls += 1
        return dict(self.reply)


def test_same_input_hits_the_cache(tmp_path):
    c = FakeClient()
    rail = Rail(client=c, cache_dir=tmp_path)
    first = rail.chat("job", "p", system="s")
    second = rail.chat("job", "p", system="s")
    assert c.calls == 1
    assert first["cached"] is False and second["cached"] is True
    assert second["text"] == "ok"


def test_any_input_change_misses(tmp_path):
    c = FakeClient()
    rail = Rail(client=c, cache_dir=tmp_path)
    rail.chat("job", "p")
    rail.chat("job", "p2")
    rail.chat("job", "p", system="other")
    rail.chat("job", "p", max_tokens=5)
    assert c.calls == 4


def test_model_change_misses():
    a = cache_key(backend="openai", model="heretic", system=None, prompt="p",
                  max_tokens=1, temperature=0)
    b = cache_key(backend="openai", model="other", system=None, prompt="p",
                  max_tokens=1, temperature=0)
    assert a != b


def test_errors_are_never_cached(tmp_path):
    c = FakeClient(reply={"error": "timeout"})
    rail = Rail(client=c, cache_dir=tmp_path)
    assert "error" in rail.chat("job", "p")
    assert "error" in rail.chat("job", "p")
    assert c.calls == 2
    assert not list(tmp_path.rglob("*.json"))


def test_corrupt_entry_is_replaced(tmp_path):
    c = FakeClient()
    rail = Rail(client=c, cache_dir=tmp_path)
    rail.chat("job", "p")
    (entry,) = tmp_path.rglob("*.json")
    entry.write_text("{not json")
    assert rail.chat("job", "p")["cached"] is False
    assert json.loads(entry.read_text())["text"] == "ok"
    assert not list(tmp_path.rglob(".tmp-*"))


def test_use_cache_false_always_calls(tmp_path):
    c = FakeClient()
    rail = Rail(client=c, cache_dir=tmp_path)
    rail.chat("job", "p", use_cache=False)
    rail.chat("job", "p", use_cache=False)
    assert c.calls == 2
