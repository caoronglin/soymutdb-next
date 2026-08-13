from soymutdb_worker.tasks.ingest import _pick_mutant_line, _surrogate_id


def test_surrogate_id_is_unsigned_uint32():
    surrogate_id = _surrogate_id("gene-with-a-stable-id")

    assert 0 <= surrogate_id <= 0xFFFFFFFF
    assert surrogate_id == _surrogate_id("gene-with-a-stable-id")


def test_pick_mutant_line_uses_first_non_reference_known_sample():
    sample_names = ["control", "mutant-a", "mutant-b"]

    assert _pick_mutant_line(sample_names, [0, 1, 2], 0) == (
        "mutant-a",
        _surrogate_id("mutant-a"),
    )
    assert _pick_mutant_line(sample_names, [0, 1, 2], 1) == (
        "mutant-a",
        _surrogate_id("mutant-a"),
    )


def test_pick_mutant_line_returns_empty_for_missing_or_unknown_samples():
    assert _pick_mutant_line([], [], 0) == ("", 0)
    assert _pick_mutant_line(["unknown"], [3], 0) == ("", 0)
