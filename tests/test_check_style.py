from scripts.check_style import check_rows, contract_text, load_style
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


# --- style が無くても正誤印の整合だけは既定で検査する ----------------------
#
# 実績: `style: {}` のまま運用した講座で、正誤印の欠落33件と
# 「不正解。」「不正解です。」の混在が全検査 OK のまま素通りした。

def test_no_style_still_checks_markers_against_correct_answers():
    bad = row(correct="1")
    bad[3] = "不正解。"  # 正解肢に誤答の印
    errs = check_rows(rows(bad), {})
    assert any("Explanation 1" in e and "一致しません" in e for e in errs)


def test_no_style_accepts_either_wording_of_the_marker():
    """既定の検査は正誤だけを見る。表記の統一は style で明示したときだけ。"""
    r = row(correct="1")
    r[5] = "不正解です。" + r[5][len("不正解。"):]
    assert check_rows(rows(r), {}) == []


def test_no_style_ignores_translation_and_sentence_rules():
    r = row()
    r[3] = "正解です。これは常体である。"          # 訳マーカーなし・常体
    assert check_rows(rows(r), {}) == []


def test_no_style_fails_a_missing_marker_when_others_are_marked():
    r = row(correct="1")
    r[5] = "これは印のない解説です。"
    errs = check_rows(rows(r), {})
    assert any("Explanation 2" in e and "正誤印がありません" in e for e in errs)


def test_no_style_only_warns_when_no_row_is_marked():
    """印を書かない運用の講座は FAIL にしない（警告で知らせる）。"""
    from scripts.check_style import check_rows_with_warnings
    r = row(correct="1")
    for k in range(4):
        r[3 + k * 2] = "印のない解説です。"
    errs, warns = check_rows_with_warnings(rows(r), {})
    assert errs == []
    assert warns and "正誤印が1件もありません" in warns[0]


def test_markers_can_be_switched_off_explicitly():
    bad = row(correct="1")
    bad[3] = "不正解。"
    assert check_rows(rows(bad), {"explanation_markers": False}) == []


def test_style_without_markers_falls_back_to_the_default_markers():
    style = {k: v for k, v in STYLE.items() if k != "explanation_markers"}
    bad = row(correct="1")
    bad[3] = bad[3].replace("正解です。", "不正解。", 1)
    assert any("Explanation 1" in e for e in check_rows(rows(bad), style))


def test_explicit_markers_reject_wording_drift():
    """style で印を明示したら「不正解です。」は「不正解。」の揺れとして落とす。"""
    r = row(correct="1")
    r[5] = "不正解です。" + r[5][len("不正解。"):]
    errs = check_rows(rows(r), STYLE)
    assert any("Explanation 2" in e and "一致しません" in e for e in errs)


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


# --- --print-contract: 契約の定義元を検査と共有する ------------------------
#
# ブリーフに散文で書き写すと、検査側とブリーフ側がずれて「基準どおりに書いた
# つもりの問題」が担当ドメインごと全滅する（実績: 作問直前に発覚）。
# 契約文は front matter の style から生成する。

def test_contract_names_every_machine_checked_marker():
    t = contract_text(STYLE)
    for marker in ("正解です。", "不正解。", "【訳】", "【設問の訳】"):
        assert marker in t, marker


def test_contract_states_both_sentence_style_rules():
    t = contract_text(STYLE)
    assert STYLE["body_sentence_end"] in t
    assert "一致させる" in t
    assert "一致させない" in t


def test_contract_mentions_the_space_after_the_source_url():
    assert "半角スペース" in contract_text(STYLE)


def test_contract_omits_rules_that_are_switched_off():
    style = {k: v for k, v in STYLE.items() if k != "require_space_after_source_url"}
    style.pop("question_translation_marker")
    t = contract_text(style)
    assert "半角スペース" not in t
    assert "【設問の訳】" not in t
    assert "【訳】" in t          # 残したものは消えない


def test_contract_says_so_when_no_style_is_configured():
    t = contract_text({})
    assert "style" in t
    assert "無い" in t


def test_contract_without_style_still_states_the_default_marker_rule():
    """既定の印を検査するのにブリーフへ書かないと、検査と契約がずれる。"""
    t = contract_text({})
    assert "`正解`" in t and "`不正解`" in t
    assert "Correct Answers" in t


def test_contract_omits_markers_when_switched_off():
    t = contract_text({"explanation_markers": False, "require_space_after_source_url": True})
    assert "正誤印" not in t


def test_contract_is_safe_to_paste_into_the_brief():
    """ブリーフは Markdown なので、見出しと自己チェックのコマンドを含む。"""
    t = contract_text(STYLE)
    assert t.startswith("### ")
    assert "check_style.py" in t


# --- glossary: 原語で書く用語と禁止訳語 --------------------------------------
#
# 実績: 方針に「製品名・サービス名は原語のまま」と書いてあったのに、
# ある講座の300問で約400件の和訳・カタカナ化・直訳調が混入した。
# 散文では守られないので front matter の用語集で機械的に落とす。

GLOSS = [
    {"term": "Widget", "forbid": ["ウィジェット", "小道具"], "allow_context": []},
    {"term": "evaluator", "forbid": ["評価者"], "allow_context": ["人間の評価者"]},
]


def test_glossary_flags_a_forbidden_rendering_with_row_column_and_term():
    r = row()
    r[3] = r[3].replace("これは解説です。", "ウィジェットを使う解説です。")
    errs = check_rows(rows(r), STYLE, GLOSS)
    hit = [e for e in errs if "禁止訳語" in e]
    assert len(hit) == 1
    assert "Row 2" in hit[0] and "Explanation 1" in hit[0]
    assert '"ウィジェット"' in hit[0] and '"Widget"' in hit[0]


def test_glossary_scans_question_options_and_overall_explanation():
    r = row()
    r[0] = "小道具を使う設問"
    r[4] = "ウィジェット option"
    r[15] = r[15].replace("これは要約です。", "評価者が見る要約です。")
    labels = {e.split(":")[0] for e in check_rows(rows(r), STYLE, GLOSS) if "禁止訳語" in e}
    assert labels == {"Row 2 Question", "Row 2 Answer Option 2", "Row 2 Overall Explanation"}


def test_glossary_skips_the_domain_column():
    r = row()
    r[16] = "ウィジェット の設計"
    assert [e for e in check_rows(rows(r), STYLE, GLOSS) if "禁止訳語" in e] == []


def test_glossary_allow_context_permits_the_listed_phrase_only():
    r = row()
    r[3] = r[3].replace("これは解説です。", "人間の評価者が確認する解説です。")
    assert [e for e in check_rows(rows(r), STYLE, GLOSS) if "禁止訳語" in e] == []
    r[3] = r[3] + "評価者"
    assert [e for e in check_rows(rows(r), STYLE, GLOSS) if "禁止訳語" in e]


def test_glossary_runs_without_style():
    r = row()
    r[0] = "ウィジェットの設問"
    assert any("禁止訳語" in e for e in check_rows(rows(r), {}, GLOSS))


def test_glossary_counts_repeats_in_one_cell():
    r = row()
    r[0] = "ウィジェットとウィジェット"
    hit = [e for e in check_rows(rows(r), STYLE, GLOSS) if "禁止訳語" in e]
    assert len(hit) == 1 and "x2" in hit[0]


def test_contract_lists_the_glossary():
    t = contract_text(STYLE, GLOSS)
    assert "`Widget`" in t and "ウィジェット" in t
    assert "原語" in t


def test_contract_without_glossary_has_no_glossary_table():
    assert "用語集" not in contract_text(STYLE)


def _sections(tmp_path, extra=""):
    p = tmp_path / "sections.md"
    p.write_text(
        "---\n"
        "cert: X\nvendor: v\nstudy_guide: u\nmode: mock-exam\n"
        "mock_exams: 1\nquestions_per_exam: 1\n"
        "exam:\n  minutes: 1\n  pass_score: 1\n  language: en\n"
        + extra +
        "domains:\n  - id: D1\n    name: N\n    ratio: \"100%\"\n    per_exam: 1\n"
        "---\n",
        encoding="utf-8",
    )
    return p


def test_load_glossary_reads_the_block(tmp_path):
    from scripts.check_style import load_glossary
    p = _sections(
        tmp_path,
        "glossary:\n"
        "  - term: Widget\n    forbid: [ウィジェット]\n"
        "    allow_context: [ウィジェット一般]\n",
    )
    assert load_glossary(p) == [
        {"term": "Widget", "forbid": ["ウィジェット"], "allow_context": ["ウィジェット一般"]}
    ]


def test_profile_validation_rejects_a_malformed_glossary():
    from scripts.profile import validate_profile
    errs = validate_profile({"glossary": [{"term": "Widget", "forbid": "ウィジェット"}]})
    assert any("forbid" in e for e in errs)
    errs = validate_profile({"glossary": [{"forbid": ["x"]}]})
    assert any("term" in e for e in errs)
    errs = validate_profile({"glossary": [{"term": "W", "forbid": ["x"], "allow_context": "y"}]})
    assert any("allow_context" in e for e in errs)
    ok = validate_profile({"glossary": [{"term": "W", "forbid": ["x"]}]})
    assert not any("glossary" in e for e in ok)


# --- CLI: style が無いときは WARN を出して既定検査を続ける --------------------

def _write_quiz(tmp_path, body):
    from scripts.validate_quiz_csv import write_rows
    q = tmp_path / "quiz.csv"
    write_rows(q, rows(*body))
    return q


def test_cli_warns_instead_of_skipping_when_style_is_absent(tmp_path, capsys):
    from scripts.check_style import main
    p = _sections(tmp_path)
    q = _write_quiz(tmp_path, [row()])
    assert main(["x", str(q), "--sections", str(p)]) == 0
    out = capsys.readouterr().out
    assert "WARN" in out and "SKIP" not in out
    assert "OK" in out


def test_cli_fails_a_marker_mismatch_even_without_style(tmp_path, capsys):
    from scripts.check_style import main
    p = _sections(tmp_path, "style: {}\n")
    bad = row(correct="1")
    bad[14] = "2"
    q = _write_quiz(tmp_path, [bad])
    assert main(["x", str(q), "--sections", str(p)]) == 1
    assert "一致しません" in capsys.readouterr().out


def test_cli_fails_on_forbidden_glossary_terms(tmp_path, capsys):
    from scripts.check_style import main
    p = _sections(tmp_path, "glossary:\n  - term: Widget\n    forbid: [ウィジェット]\n")
    r = row()
    r[0] = "ウィジェットの設問"
    q = _write_quiz(tmp_path, [r])
    assert main(["x", str(q), "--sections", str(p)]) == 1
    out = capsys.readouterr().out
    assert "禁止訳語" in out and "Widget" in out and "内訳" in out
