import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_bench as cb  # noqa: E402


def _user(text):
    return {"type": "user", "message": {"content": text}}


def _tool_result():
    return {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}}


def _asst(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _write(tmp_path, entries):
    p = tmp_path / "proj" / "s.jsonl"
    p.parent.mkdir()
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n{broken")
    return p


def test_pairs_check_prompt_with_previous_answer(tmp_path):
    p = _write(tmp_path, [
        _user("what tools exist?"), _asst("Nothing covers step 4."),
        _tool_result(),
        _user("can you check yourself again?"), _asst("Checked: I found two mistakes."),
    ])
    pairs = cb.mine([p])
    assert len(pairs) == 1
    assert pairs[0]["checked"] == "Nothing covers step 4."
    assert pairs[0]["correction"] is True
    assert pairs[0]["project"] == "proj"


def test_confirmation_is_not_a_correction(tmp_path):
    p = _write(tmp_path, [
        _user("is it 370 ohms?"), _asst("370."),
        _user("are you sure"), _asst("Yes, it's right: 37 x 10."),
    ])
    pairs = cb.mine([p])
    assert len(pairs) == 1 and pairs[0]["correction"] is False


def test_first_prompt_and_skill_bodies_are_not_checks(tmp_path):
    p = _write(tmp_path, [
        _user("double check yourself"), _asst("No prior answer."),
        _user("Base directory for this skill: x\ncheck yourself"), _asst("I was wrong."),
    ])
    assert cb.mine([p]) == []


def test_admission_phrasings():
    for s in ["I got two things wrong", "found four mistakes", "Three corrections:",
              "Self-check found a mistake", "a constraint I'd skipped over", "I overstated it"]:
        assert cb.admits(s), s
    for s in ["Checked, all good.", "Yes, it's right.", "Merging now."]:
        assert not cb.admits(s), s


def test_summary_rate():
    pairs = [{"project": "a", "correction": True}, {"project": "a", "correction": False}]
    assert "rate: 50%" in cb.summary(pairs)
