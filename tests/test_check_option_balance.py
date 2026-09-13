from scripts.check_option_balance import analyze, option_lengths, problems
from scripts.validate_quiz_csv import HEADER, write_rows


def row(lengths, correct, qt="multiple-choice"):
    """指定した文字数の選択肢を持つ行を作る。"""
    r = ["Q?", qt]
    for k in range(6):
        if k < len(lengths):
            r += ["x" * lengths[k], "解説"]
        else:
            r += ["", ""]
    r += [str(correct), "overall", "Domain 1"]
    return r


def build(tmp_path, rows, name="quiz.csv"):
    p = tmp_path / name
    write_rows(p, [list(HEADER)] + rows)
    return p


def test_option_lengths_counts_only_filled_options():
    assert option_lengths(row([10, 20, 30, 40], 1)) == {1: 10, 2: 20, 3: 30, 4: 40}


def test_balanced_file_passes(tmp_path):
    rows = [row([100, 102, 98, 101], c) for c in (1, 2, 3, 4)] * 3
    result = analyze(build(tmp_path, rows))
    assert result["longest_share"] <= 0.40
    assert problems(result, 0.30, 0.15) == []


def test_detects_correct_answer_always_longest(tmp_path):
    """内容を読まずに最長を選べば全問正解できる状態を検出する。"""
    rows = [row([160, 100, 100, 100], 1) for _ in range(12)]
    result = analyze(build(tmp_path, rows))
    assert result["longest_share"] == 1.0
    errs = problems(result, 0.30, 0.15)
    assert any("正解が最長の割合" in e for e in errs)


def test_detects_correct_answer_always_shortest(tmp_path):
    rows = [row([60, 150, 150, 150], 1) for _ in range(12)]
    result = analyze(build(tmp_path, rows))
    assert result["shortest_share"] == 1.0
    assert any("正解が最短の割合" in e for e in problems(result, 0.30, 0.15))


def test_detects_per_question_spread(tmp_path):
    """1問だけでも選択肢の長さが極端に散らばっていれば報告する。"""
    rows = [row([100, 100, 100, 100], c) for c in (1, 2, 3, 4)] * 3
    rows[0] = row([300, 100, 100, 100], 2)     # 正解は最長ではないが散らばりが大きい
    result = analyze(build(tmp_path, rows))
    errs = problems(result, 0.30, 0.15)
    assert any("Q1" in e and "散らばり" in e for e in errs)


def test_multi_select_is_ignored(tmp_path):
    """multi-select は正解が複数なので長さ比較の対象にしない。"""
    rows = [row([200, 100, 100, 100], "1,2", qt="multi-select") for _ in range(5)]
    assert analyze(build(tmp_path, rows))["n"] == 0


def test_expected_share_follows_option_count(tmp_path):
    """5択なら期待値は 20%、4択なら 25%。"""
    rows4 = [row([100, 100, 100, 100], 1) for _ in range(4)]
    rows5 = [row([100, 100, 100, 100, 100], 1) for _ in range(4)]
    assert abs(analyze(build(tmp_path, rows4, "a.csv"))["expected_share"] - 0.25) < 1e-9
    assert abs(analyze(build(tmp_path, rows5, "b.csv"))["expected_share"] - 0.20) < 1e-9


def test_mean_ratio_reports_how_much_longer_the_answer_is(tmp_path):
    rows = [row([200, 100, 100, 100], 1) for _ in range(4)]
    assert abs(analyze(build(tmp_path, rows))["mean_ratio"] - 2.0) < 1e-9
