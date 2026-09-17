"""multi-select の長さバイアスと、短い選択肢の免除・字数稼ぎタグの検査。

旧版は `multiple-choice` 以外を丸ごとスキップしていたため、
**multi-select の長さバイアスが無検査で通っていた**（実績: 42問中14問で
正解肢がすべて最長、うち4問は「長い順に2つ選ぶ」で当たる本物の欠陥）。
"""
from scripts.check_option_balance import (
    analyze, analyze_multi_select, multi_select_problems, padding_tags, problems,
)
from scripts.validate_quiz_csv import HEADER, write_rows


def row(lengths, correct, qt="multi-select", texts=None):
    r = ["Q?", qt]
    for k in range(6):
        if texts is not None and k < len(texts):
            r += [texts[k], "解説"]
        elif k < len(lengths):
            r += ["x" * lengths[k], "解説"]
        else:
            r += ["", ""]
    r += [str(correct), "overall", "Domain 1"]
    return r


def build(tmp_path, rows, name="quiz.csv"):
    p = tmp_path / name
    write_rows(p, [list(HEADER)] + rows)
    return p


# --- multi-select の margin -------------------------------------------------

def test_margin_is_shortest_correct_over_longest_distractor(tmp_path):
    """正解の最短 120字・誤答の最長 100字なら margin は +20%。"""
    p = build(tmp_path, [row([140, 120, 100, 80], "1,2")])
    e = analyze_multi_select(p)["per_question"][0]
    assert abs(e["margin"] - 0.20) < 1e-9
    assert e["all_correct_longest"] is True


def test_margin_is_negative_when_a_distractor_is_longest(tmp_path):
    p = build(tmp_path, [row([200, 120, 100, 80], "2,3")])
    e = analyze_multi_select(p)["per_question"][0]
    assert e["margin"] < 0
    assert e["all_correct_longest"] is False


def test_detects_answers_that_can_be_picked_by_length(tmp_path):
    """長い順に2つ選ぶだけで当たる問題は報告する。"""
    p = build(tmp_path, [row([200, 180, 60, 50], "1,2")])
    errs = multi_select_problems(analyze_multi_select(p))
    assert len(errs) == 1
    assert "Q1" in errs[0] and "長い順に選ぶだけで当たる" in errs[0]


def test_balanced_multi_select_passes(tmp_path):
    p = build(tmp_path, [row([100, 98, 102, 101], "1,3")])
    assert multi_select_problems(analyze_multi_select(p)) == []


# --- 短い選択肢の免除 ------------------------------------------------------

def test_bare_term_names_are_exempt_even_if_correct_ones_are_longest(tmp_path):
    """実在の用語名が長いだけの問題は欠陥ではない。

    `Fast R-CNN`(10) / `SSD`(3) / `Faster R-CNN`(12) / `YOLO`(4) は
    正解2つが最長になるが、モデル名を改名することはできない。
    """
    p = build(tmp_path, [row([], "1,3",
                             texts=["Fast R-CNN", "SSD", "Faster R-CNN", "YOLO"])])
    result = analyze_multi_select(p)
    assert result["per_question"][0]["margin"] > 0.20   # margin は超えている
    assert multi_select_problems(result) == []          # が、報告しない


def test_long_prose_answers_are_not_exempt(tmp_path):
    """同じ margin でも、長い散文なら免除しない。"""
    p = build(tmp_path, [row([60, 55, 20, 18], "1,2")])
    assert multi_select_problems(analyze_multi_select(p)) != []


def test_short_options_are_exempt_from_spread_in_multiple_choice(tmp_path):
    """multiple-choice でも、全選択肢が短ければ散らばりを免除する。

    用語名を裸で並べた本番準拠の形を止めると、作問側が意味のないタグで
    字数を稼ぐという悪化を招く（実績20件）。
    """
    rows = [row([16, 8, 12, 6], c, qt="multiple-choice") for c in (1, 2, 3, 4)] * 3
    result = analyze(build(tmp_path, rows))
    assert result["per_question"][0]["spread"] > 0.30
    assert not any("散らばり" in e for e in problems(result))


# --- 字数稼ぎタグ ----------------------------------------------------------

def test_detects_padding_tags(tmp_path):
    p = build(tmp_path, [row([], "1", qt="multiple-choice",
                             texts=["FCN(モデル)", "SegNet", "U-Net", "PSPNet"])])
    errs = padding_tags(p)
    assert len(errs) == 1
    assert "字数稼ぎ" in errs[0] and "FCN(モデル)" in errs[0]


def test_meaningful_parenthetical_is_not_a_padding_tag(tmp_path):
    """略称や意味のある限定語は字数稼ぎではない。"""
    p = build(tmp_path, [row([], "1", qt="multiple-choice",
                             texts=["主成分分析(PCA)", "t-SNE", "多次元尺度構成法",
                                    "特異値分解"])])
    assert padding_tags(p) == []
