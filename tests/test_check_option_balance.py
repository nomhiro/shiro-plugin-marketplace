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


# --- margin の定義 -----------------------------------------------------------

def test_margin_is_how_much_the_answer_beats_the_runner_up(tmp_path):
    """正解120字・2位100字なら margin は +20%。"""
    p = build(tmp_path, [row([120, 100, 80, 60], 1)])
    e = analyze(p)["per_question"][0]
    assert abs(e["margin"] - 0.20) < 1e-9


def test_margin_is_negative_when_the_answer_is_not_longest(tmp_path):
    """正解80字・2位120字なら margin は負。"""
    p = build(tmp_path, [row([120, 80, 100, 60], 2)])
    e = analyze(p)["per_question"][0]
    assert e["margin"] < 0


def test_being_longest_by_a_hair_is_not_a_defect(tmp_path):
    """1文字差で最長になっても攻略できない。二値の「最長か」はこれを欠陥と誤報した。"""
    rows = [row([101, 100, 100, 100], 1) for _ in range(8)]
    result = analyze(build(tmp_path, rows))
    assert result["longest"] == 8            # 全問「最長」
    assert result["mean_margin"] < 0.02      # しかし margin はほぼ 0
    assert problems(result) == []            # 欠陥として報告しない


# --- 検出すべきもの ----------------------------------------------------------

def test_detects_a_conspicuously_long_answer(tmp_path):
    """正解が2位を大きく上回る問題は個別に報告する。"""
    rows = [row([100, 100, 100, 100], c) for c in (1, 2, 3, 4)] * 3
    rows[0] = row([200, 100, 100, 100], 1)
    result = analyze(build(tmp_path, rows))
    assert any("Q1" in e and "2位より" in e for e in problems(result))


def test_detects_systematically_long_answers(tmp_path):
    """全問で正解が長ければ、平均 margin の超過として報告する。"""
    rows = [row([160, 100, 100, 100], 1) for _ in range(12)]
    result = analyze(build(tmp_path, rows))
    assert result["mean_margin"] > 0.50
    errs = problems(result)
    assert any("margin の平均" in e for e in errs)
    assert any("超の問題が" in e for e in errs)


def test_detects_per_question_spread_even_when_margin_is_fine(tmp_path):
    """正解が最長でなくても、選択肢の長さが極端に散らばっていれば報告する。"""
    rows = [row([100, 100, 100, 100], c) for c in (1, 2, 3, 4)] * 3
    rows[0] = row([300, 100, 100, 100], 2)   # 正解は2位以下だが散らばりが大きい
    result = analyze(build(tmp_path, rows))
    assert result["per_question"][0]["margin"] < 0
    assert any("Q1" in e and "散らばり" in e for e in problems(result))


# --- 通すべきもの ------------------------------------------------------------

def test_balanced_file_passes(tmp_path):
    rows = [row([100, 102, 98, 101], c) for c in (1, 2, 3, 4)] * 3
    result = analyze(build(tmp_path, rows))
    assert abs(result["mean_margin"]) < 0.05
    assert problems(result) == []


def test_a_few_long_answers_are_tolerated(tmp_path):
    """12問中1問だけ margin 超過なら体系的な偏りではない。

    個別の報告は出るが、平均・割合の判定では落とさない。
    """
    rows = [row([100, 100, 100, 100], c) for c in (1, 2, 3, 4)] * 3
    rows[0] = row([130, 100, 100, 100], 1)
    result = analyze(build(tmp_path, rows))
    errs = problems(result)
    assert any("Q1" in e for e in errs)
    assert not any("margin の平均" in e for e in errs)
    assert not any("超の問題が" in e for e in errs)


def test_multi_select_is_ignored(tmp_path):
    """multi-select は正解が複数なので長さ比較の対象にしない。"""
    rows = [row([200, 100, 100, 100], "1,2", qt="multi-select") for _ in range(5)]
    assert analyze(build(tmp_path, rows))["n"] == 0


def test_reports_mean_ratio_for_context(tmp_path):
    """正解長が他の平均の何倍かも出す（報告用）。"""
    rows = [row([200, 100, 100, 100], 1) for _ in range(4)]
    assert abs(analyze(build(tmp_path, rows))["mean_ratio"] - 2.0) < 1e-9
