# tests/test_recall_bench.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "bench"))
import recall_lib

REPO = Path(__file__).parent.parent


def test_drawer_key_normalizes_path_and_chunk():
    assert recall_lib.drawer_key("/home/x/a.txt", 3) == "a.txt::3"
    assert recall_lib.drawer_key("/home/x/a.txt", None) == "a.txt::0"
    assert recall_lib.drawer_key("", 0) == "?::0"


def test_recall_at_k_hit_and_miss():
    # expected one of {a::0}, retrieved keys in order
    assert recall_lib.recall_at_k({"a::0"}, ["b::0", "a::0", "c::0"], k=3) == 1.0
    assert recall_lib.recall_at_k({"a::0"}, ["b::0", "c::0"], k=3) == 0.0
    # multi-target: 1 of 2 found within k -> 0.5
    assert recall_lib.recall_at_k({"a::0", "d::0"}, ["a::0", "x::0"], k=3) == 0.5


def test_recall_at_k_respects_k_cutoff():
    # target only at position 4; k=3 must not count it
    assert recall_lib.recall_at_k({"t::0"}, ["a::0", "b::0", "c::0", "t::0"], k=3) == 0.0


def test_validate_probe_accepts_well_formed():
    p = {"id": "p1", "query": "foo bar", "expect": ["a.txt::0"], "origin": "seed"}
    recall_lib.validate_probe(p)  # no raise


def test_validate_probe_rejects_missing_fields():
    import pytest
    for bad in [{"query": "x", "expect": ["a::0"]},          # no id
                {"id": "p", "expect": ["a::0"]},             # no query
                {"id": "p", "query": "x", "expect": []},     # empty expect
                {"id": "p", "query": "x", "expect": "a::0"}]: # expect not list
        with pytest.raises(recall_lib.ProbeError):
            recall_lib.validate_probe(bad)


def test_aggregate_computes_mean_and_perk():
    per_probe = [
        {"id": "p1", "recall": 1.0, "k": 5},
        {"id": "p2", "recall": 0.0, "k": 5},
        {"id": "p3", "recall": 0.5, "k": 5},
    ]
    agg = recall_lib.aggregate(per_probe)
    assert agg["n_probes"] == 3
    assert agg["recall_at_k_mean"] == 0.5
    assert agg["recall_at_k_min"] == 0.0
    assert agg["n_perfect"] == 1
    assert agg["n_zero"] == 1


def test_load_probes_roundtrip(tmp_path):
    f = tmp_path / "p.jsonl"
    f.write_text('{"id":"p1","query":"q","expect":["a::0"],"origin":"seed"}\n'
                 '\n'  # blank line tolerated
                 '{"id":"p2","query":"q2","expect":["b::0"],"origin":"hand"}\n')
    probes = recall_lib.load_probes(f)
    assert [p["id"] for p in probes] == ["p1", "p2"]


# append to tests/test_recall_bench.py
import seed_probes


def test_distinctive_phrase_picks_rare_multiword_run():
    # 'quantum flux capacitor' is rare; stopwords/common words avoided.
    text = ("the the the and of to a in\n"
            "quantum flux capacitor calibration sequence\n"
            "the and of to in a the and")
    phrase = seed_probes.distinctive_phrase(text, n_words=4)
    assert phrase is not None
    assert "quantum" in phrase
    # phrase is a contiguous run drawn from the text
    assert phrase in " ".join(text.split())


def test_distinctive_phrase_none_for_too_short():
    assert seed_probes.distinctive_phrase("hi there", n_words=4) is None


def test_distinctive_phrase_is_deterministic():
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
    a = seed_probes.distinctive_phrase(text, n_words=4)
    b = seed_probes.distinctive_phrase(text, n_words=4)
    assert a == b


def test_build_probe_record_shape():
    rec = seed_probes.build_probe_record(
        idx=2, query="quantum flux capacitor calibration",
        source_file="/x/notes.md", chunk_index=1)
    assert rec["id"] == "seed-0002"
    assert rec["query"] == "quantum flux capacitor calibration"
    assert rec["expect"] == ["notes.md::1"]
    assert rec["origin"] == "seed"
