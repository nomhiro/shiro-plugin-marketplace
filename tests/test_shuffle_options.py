import random
from scripts.shuffle_options import (
    balance_warnings, choose_seed, ensure_raw, position_balance,
    position_distribution, shuffle_file, shuffle_row, worst_relative_deviation,
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


def build(tmp_path, rows, name="quiz.csv"):
    p = tmp_path / name
    write_rows(p, [list(HEADER)] + rows)
    return p


# --- shuffle_row の不変条件 -------------------------------------------------

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


# --- 位置分布モデル ---------------------------------------------------------

def test_position_distribution_counts_only_the_requested_type():
    rows = [list(HEADER), row(correct="2"), row(correct="2"),
            row(correct="1,2", qt="multi-select")]
    assert position_distribution(rows) == {"2": 2}


def test_expected_votes_come_only_from_questions_offering_that_position():
    """4択2問 + 6択1問。位置5/6の期待票数は6択の1問だけから積まれる。"""
    rows = [list(HEADER), row(correct="1", nopt=4), row(correct="1", nopt=4),
            row(correct="5", nopt=6)]
    by_pos = {e["position"]: e for e in position_balance(rows)}
    assert by_pos[1]["expected"] == round(1 / 4 + 1 / 4 + 1 / 6, 1)
    assert by_pos[5]["expected"] == round(1 / 6, 1)
    assert by_pos[5]["actual"] == 1


def test_worst_relative_deviation_is_zero_for_a_perfect_spread():
    rows = [list(HEADER)] + [row(correct=str(p)) for p in (1, 2, 3, 4)]
    assert worst_relative_deviation(rows) == 0.0


def test_worst_relative_deviation_flags_a_fully_skewed_spread():
    rows = [list(HEADER)] + [row(correct="1") for _ in range(8)]
    assert worst_relative_deviation(rows) > 1.0


def test_balance_warnings_flags_a_skewed_file():
    rows = [list(HEADER)] + [row(correct="1") for _ in range(20)]
    assert balance_warnings(rows)


def test_balance_warnings_accepts_an_even_file():
    rows = [list(HEADER)] + [row(correct=str(p)) for p in (1, 2, 3, 4)] * 5
    assert balance_warnings(rows) == []


# --- 原本退避（再シャッフルの罠の防止） -------------------------------------

def test_ensure_raw_creates_the_original_once(tmp_path):
    p = build(tmp_path, [row()])
    raw = ensure_raw(p)
    assert raw.name == "quiz.raw.csv"
    assert raw.read_bytes() == p.read_bytes()


def test_ensure_raw_never_overwrites_an_existing_original(tmp_path):
    p = build(tmp_path, [row()])
    raw = ensure_raw(p)
    before = raw.read_bytes()
    p.write_text("clobbered", encoding="utf-8")
    assert ensure_raw(p).read_bytes() == before


def test_shuffle_file_always_reads_from_the_original(tmp_path):
    """2回続けて同じシードで回しても、原本から読むので結果が同一になる。"""
    p = build(tmp_path, [row(correct="1") for _ in range(12)])
    first = shuffle_file(p, seed=7)
    rows_after_first = read_rows(p)
    second = shuffle_file(p, seed=7)
    assert first["seed"] == second["seed"] == 7
    assert read_rows(p) == rows_after_first


# --- シード走査 -------------------------------------------------------------

def test_choose_seed_beats_a_pathological_fixed_seed(tmp_path):
    """固定シードの当たり外れを避けられること（seed=42 事故の再発防止）。"""
    base = [row(correct="1") for _ in range(40)]
    seed, worst = choose_seed(base, max_seed=200)
    assert worst <= 0.20, f"seed={seed} worst={worst}"


def test_shuffle_file_searches_a_seed_when_none_is_given(tmp_path):
    p = build(tmp_path, [row(correct="1") for _ in range(40)])
    result = shuffle_file(p)
    assert result["n"] == 40
    assert result["seed"] >= 1
    assert result["worst_relative_deviation"] <= 0.20
    assert result["warnings"] == []


def test_shuffle_file_output_still_validates(tmp_path):
    p = build(tmp_path, [row(correct=str(i % 4 + 1)) for i in range(20)])
    shuffle_file(p)
    assert validate_csv(p) == []


def test_shuffle_file_reports_the_original_path(tmp_path):
    p = build(tmp_path, [row() for _ in range(4)])
    assert shuffle_file(p)["raw"].endswith("quiz.raw.csv")


def test_combined_deviation_sees_both_question_types():
    """MC が完璧でも MS が偏っていれば combined は大きくなる。"""
    from scripts.shuffle_options import combined_worst_deviation
    rows = [list(HEADER)]
    rows += [row(correct=str(p)) for p in (1, 2, 3, 4)] * 4      # MC は完璧
    rows += [row(correct="1,2", qt="multi-select") for _ in range(12)]  # MS は位置1,2に固定
    assert worst_relative_deviation(rows, "multiple-choice") == 0.0
    assert combined_worst_deviation(rows) > 0.5


def test_seed_search_balances_multi_select_too(tmp_path):
    """MS だけを含むファイルでもシード走査が偏りを解消すること。

    MC だけを目的関数にしていた頃は MS に「位置1を必ず含む」偏りが残り、
    受講者が攻略できる状態になっていた。
    """
    p = build(tmp_path, [row(correct="1,2", qt="multi-select") for _ in range(16)])
    result = shuffle_file(p)
    ms = {e["position"]: e for e in result["ms_balance"]}
    assert all(e["within_tolerance"] for e in ms.values()), ms
    assert result["warnings"] == []
