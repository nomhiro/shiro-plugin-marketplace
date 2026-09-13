import random
from scripts.shuffle_options import (
    distribution_warnings, position_distribution, shuffle_file, shuffle_row,
)
from scripts.validate_quiz_csv import HEADER, read_rows, validate_csv, write_rows


def row(correct="1", qt="multiple-choice", nopt=4):
    r = ["Q?", qt]
    for i in range(6):
        if i < nopt:
            r += [f"OPT{i + 1}", f"EXP{i + 1}"]
        else:
            r += ["", ""]
    r += [correct, "overall", "Domain 1"]
    return r


def test_shuffle_keeps_option_explanation_pairs():
    out = shuffle_row(row(), random.Random(1))
    for opt, exp in ((2, 3), (4, 5), (6, 7), (8, 9)):
        assert out[opt].replace("OPT", "") == out[exp].replace("EXP", "")


def test_shuffle_moves_correct_answer_to_its_new_position():
    out = shuffle_row(row(correct="1"), random.Random(1))
    idx = int(out[14])
    assert out[2 + (idx - 1) * 2] == "OPT1"


def test_shuffle_preserves_multi_select_correct_set():
    out = shuffle_row(row(correct="1,3", qt="multi-select"), random.Random(7))
    moved = {out[2 + (int(i) - 1) * 2] for i in out[14].split(",")}
    assert moved == {"OPT1", "OPT3"}


def test_shuffle_keeps_empty_pairs_at_the_end():
    out = shuffle_row(row(nopt=4), random.Random(3))
    assert out[10:14] == ["", "", "", ""]


def test_shuffle_is_deterministic_for_a_fixed_seed():
    a = shuffle_row(row(), random.Random(42))
    b = shuffle_row(row(), random.Random(42))
    assert a == b


def test_shuffle_file_output_still_validates(tmp_path):
    p = tmp_path / "quiz.csv"
    write_rows(p, [list(HEADER)] + [row(correct=str(i % 4 + 1)) for i in range(20)])
    result = shuffle_file(p, seed=42)
    assert result["n"] == 20
    assert validate_csv(p) == []


def test_shuffle_file_is_reproducible(tmp_path):
    def make():
        p = tmp_path / f"q{make.i}.csv"
        make.i += 1
        write_rows(p, [list(HEADER)] + [row(correct="1") for _ in range(10)])
        shuffle_file(p, seed=42)
        return read_rows(p)
    make.i = 0
    assert make() == make()


def test_position_distribution_counts_only_multiple_choice():
    rows = [list(HEADER), row(correct="2"), row(correct="2"),
            row(correct="1,2", qt="multi-select")]
    assert position_distribution(rows) == {"2": 2}


def test_distribution_warnings_flags_a_skewed_spread():
    assert distribution_warnings({"1": 40, "2": 0, "3": 0, "4": 0}, 40)


def test_distribution_warnings_accepts_an_even_spread():
    assert distribution_warnings({"1": 10, "2": 10, "3": 10, "4": 10}, 40) == []
