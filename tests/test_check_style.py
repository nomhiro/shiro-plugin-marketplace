from scripts.check_style import check_rows, load_style
from scripts.validate_quiz_csv import HEADER

STYLE = {
    "explanation_markers": {"correct": "正解です。", "incorrect": "不正解。"},
    "option_translation_marker": "【訳】",
    "question_translation_marker": "【設問の訳】",
    "body_sentence_end": "(です|ます|ません|ました|でした|でしょう|ください)(か|ね|よ)?$",
    "translation_sentence_end": "(です|ます|ません|ました|でした|でしょう|ください)(か|ね|よ)?$",
    "require_space_after_source_url": True,
    "skip_sentence_pattern": "出典|参考|https?://",
}


def row(correct="1", nopt=4, overall=None):
    r = ["Q?", "multiple-choice" if len(correct.split(",")) == 1 else "multi-select"]
    for i in range(6):
        if i < nopt:
            mark = "正解です。" if str(i + 1) in correct.split(",") else "不正解。"
            r += [f"OPT{i + 1}", f"{mark}これは解説です。【訳】これは訳である。"]
        else:
            r += ["", ""]
    r += [
        correct,
        overall if overall is not None
        else "【要約】これは要約です。出典: https://example.com/a 【設問の訳】これは設問の訳である。",
        "Domain 1",
    ]
    return r


def rows(*body):
    return [list(HEADER), *body]


# --- style が無ければ何も検査しない ----------------------------------------

def test_no_style_means_no_checks():
    bad = row(correct="1")
    bad[3] = "不正解。"  # 正解肢に誤答の印
    assert check_rows(rows(bad), {}) == []


# --- 1. 正誤印 × Correct Answers -------------------------------------------

def test_clean_row_passes():
    assert check_rows(rows(row()), STYLE) == []


def test_detects_correct_answer_pointing_at_a_distractor():
    """形式検証では通ってしまう欠陥クラス（インデックスは範囲内・個数も正しい）。"""
    r = row(correct="1")
    r[14] = "2"
    errs = check_rows(rows(r), STYLE)
    assert any("正誤印が Correct Answers と一致しません" in e for e in errs)
    assert any("Explanation 1" in e for e in errs)


def test_detects_multi_select_marker_mismatch():
    r = row(correct="1,2")
    r[5] = r[5].replace("正解です。", "不正解。", 1)
    errs = check_rows(rows(r), STYLE)
    assert any("Explanation 2" in e for e in errs)


# --- 2/3. 訳マーカー --------------------------------------------------------

def test_detects_missing_option_translation_marker():
    r = row()
    r[3] = r[3].split("【訳】")[0]
    errs = check_rows(rows(r), STYLE)
    assert any("訳マーカー 【訳】 がありません" in e for e in errs)


def test_detects_missing_question_translation_marker():
    r = row(overall="【要約】これは要約です。出典: https://example.com/a ")
    errs = check_rows(rows(r), STYLE)
    assert any("訳マーカー 【設問の訳】 がありません" in e for e in errs)


# --- 4/5. 文体 --------------------------------------------------------------

def test_detects_plain_form_in_the_explanation_body():
    r = row()
    body, mk, tr = r[3].partition("【訳】")
    r[3] = body + "これは常体である。" + mk + tr
    errs = check_rows(rows(r), STYLE)
    assert any("解説本体の文体が違います" in e for e in errs)


def test_detects_polite_form_in_the_translation():
    r = row()
    r[3] = r[3] + "これはですます調です。"
    errs = check_rows(rows(r), STYLE)
    assert any("訳の文体が違います" in e for e in errs)


def test_verdict_prefix_itself_is_not_flagged_as_plain_form():
    """「不正解」は見出し語なので文体検査の対象外。"""
    r = row(correct="1")
    errs = [e for e in check_rows(rows(r), STYLE) if "文体" in e]
    assert errs == []


def test_source_sentence_is_skipped_by_style_checks():
    """出典行は URL を含むため文体判定から除外される。"""
    r = row(overall="【要約】これは要約です。出典: https://example.com/a 【設問の訳】訳である。")
    assert [e for e in check_rows(rows(r), STYLE) if "文体" in e] == []


# --- 6. 出典 URL の直後の半角スペース ---------------------------------------

def test_detects_url_glued_to_japanese():
    """詰めると URL 抽出が訳文を飲み込み --check-urls が失敗する。"""
    r = row(overall="【要約】要約です。出典: https://example.com/a【設問の訳】訳である。")
    errs = check_rows(rows(r), STYLE)
    assert any("半角スペースがありません" in e for e in errs)


def test_url_at_end_of_cell_is_not_flagged():
    r = row(overall="【設問の訳】訳である。出典: https://example.com/a")
    assert [e for e in check_rows(rows(r), STYLE) if "半角スペース" in e] == []


# --- front matter からの読み取り --------------------------------------------

def test_load_style_returns_empty_when_absent(tmp_path):
    p = tmp_path / "sections.md"
    p.write_text(
        "---\n"
        "cert: X\nvendor: v\nstudy_guide: u\nmode: mock-exam\n"
        "mock_exams: 1\nquestions_per_exam: 1\n"
        "exam:\n  minutes: 1\n  pass_score: 1\n  language: en\n"
        "domains:\n  - id: D1\n    name: N\n    ratio: \"100%\"\n    per_exam: 1\n"
        "---\n",
        encoding="utf-8",
    )
    assert load_style(p) == {}


def test_load_style_reads_the_block(tmp_path):
    p = tmp_path / "sections.md"
    p.write_text(
        "---\n"
        "cert: X\nvendor: v\nstudy_guide: u\nmode: mock-exam\n"
        "mock_exams: 1\nquestions_per_exam: 1\n"
        "exam:\n  minutes: 1\n  pass_score: 1\n  language: en\n"
        "style:\n"
        "  explanation_markers:\n    correct: \"正解です。\"\n    incorrect: \"不正解。\"\n"
        "  require_space_after_source_url: true\n"
        "domains:\n  - id: D1\n    name: N\n    ratio: \"100%\"\n    per_exam: 1\n"
        "---\n",
        encoding="utf-8",
    )
    style = load_style(p)
    assert style["explanation_markers"]["correct"] == "正解です。"
    assert style["require_space_after_source_url"] is True
