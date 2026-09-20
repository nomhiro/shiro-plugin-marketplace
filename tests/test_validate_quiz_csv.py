from scripts.validate_quiz_csv import (
    HEADER, layout_warnings, read_rows, validate_csv, write_rows,
)


def base_row():
    return [
        "What is the correct approach?", "multiple-choice",
        "Option A", "A is correct because ...",
        "Option B", "B is wrong because ...",
        "Option C", "C is wrong because ...",
        "Option D", "D is wrong because ...",
        "", "", "", "",
        "1", "A is correct. Source: https://example.com", "Domain 1",
    ]


def build(tmp_path, rows, *, bom=False, header=None):
    p = tmp_path / "quiz.csv"
    write_rows(p, [list(header or HEADER)] + rows)
    if bom:
        p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
    return p


def test_header_is_17_columns():
    assert len(HEADER) == 17
    assert HEADER[0] == "Question"
    assert HEADER[-1] == "Domain"


def test_valid_file_passes(tmp_path):
    assert validate_csv(build(tmp_path, [base_row()])) == []


def test_write_rows_emits_no_bom(tmp_path):
    p = build(tmp_path, [base_row()])
    assert not p.read_bytes().startswith(b"\xef\xbb\xbf")


def test_write_rows_emits_no_blank_lines(tmp_path):
    p = build(tmp_path, [base_row(), base_row()])
    assert p.read_text(encoding="utf-8").count("\n\n") == 0


def test_round_trip_preserves_embedded_comma_and_quote(tmp_path):
    row = base_row()
    row[0] = 'He said "yes", then left'
    p = build(tmp_path, [row])
    assert validate_csv(p) == []
    assert read_rows(p)[1][0] == 'He said "yes", then left'


def test_bom_is_reported(tmp_path):
    errs = validate_csv(build(tmp_path, [base_row()], bom=True))
    assert any("BOM" in e for e in errs)


def test_bad_header_is_reported(tmp_path):
    bad = list(HEADER)
    bad[1] = "QuestionType"
    errs = validate_csv(build(tmp_path, [base_row()], header=bad))
    assert any("col 2" in e for e in errs)


def test_no_data_rows_is_reported(tmp_path):
    assert any("No data rows" in e for e in validate_csv(build(tmp_path, [])))


def test_invalid_question_type_is_reported(tmp_path):
    row = base_row()
    row[1] = "true-false"
    errs = validate_csv(build(tmp_path, [row]))
    assert any("invalid Question Type" in e for e in errs)


def test_multiple_choice_with_two_correct_is_reported(tmp_path):
    row = base_row()
    row[14] = "1,2"
    errs = validate_csv(build(tmp_path, [row]))
    assert any("multiple-choice" in e for e in errs)


def test_multi_select_with_one_correct_is_reported(tmp_path):
    row = base_row()
    row[1] = "multi-select"
    errs = validate_csv(build(tmp_path, [row]))
    assert any("must be" in e for e in errs)


def test_multi_select_without_distractor_is_reported(tmp_path):
    row = base_row()
    row[1] = "multi-select"
    row[14] = "1,2,3,4"
    errs = validate_csv(build(tmp_path, [row]))
    assert any("no distractor" in e for e in errs)


def test_correct_answer_out_of_range_is_reported(tmp_path):
    row = base_row()
    row[14] = "5"
    errs = validate_csv(build(tmp_path, [row]))
    assert any("out of range" in e for e in errs)


def test_empty_required_column_is_reported(tmp_path):
    row = base_row()
    row[15] = ""
    errs = validate_csv(build(tmp_path, [row]))
    assert any("column 16 is empty" in e for e in errs)


def test_option_without_explanation_is_reported(tmp_path):
    row = base_row()
    row[10] = "Option E"  # 選択肢だけ埋めて解説を空にする
    errs = validate_csv(build(tmp_path, [row]))
    assert any("option/explanation pair" in e for e in errs)


def test_in_cell_newlines_are_accepted(tmp_path):
    """セル内改行は段落区切りとして表示されるので、読みやすさのために書いてよい。

    Udemy の一括取り込みは実改行を段落に変換し、編集画面・受講画面のどちらでも
    正しく表示される（実績: 300問の解説を段落分けして反映し、破損しなかった）。
    """
    r = base_row()
    r[3] = "Correct." + chr(10) + "It works because ..."
    r[15] = "1st paragraph" + chr(10) + chr(10) + "2nd paragraph"
    assert validate_csv(build(tmp_path, [r])) == []


def test_carriage_return_in_cell_is_accepted(tmp_path):
    r = base_row()
    r[0] = "Question" + chr(13) + chr(10) + "continued"
    assert validate_csv(build(tmp_path, [r])) == []


def test_single_line_cells_pass(tmp_path):
    assert validate_csv(build(tmp_path, [base_row()])) == []


def test_angle_bracket_tags_are_an_error(tmp_path):
    """`<単語>` 形は Udemy のサニタイザが中身ごと消すので落とす。

    CSV としては何もおかしくないため、列数・正解番号・改行の検査は
    すべて通る。実績: `Wrap the request in <role>, <context>, and <output>
    tags` が投入後に `Wrap the request in , , and tags` になり、
    選択肢が解けない文になった。
    """
    r = base_row()
    r[8] = "Wrap the request in <role>, <context>, and <output> tags"
    errors = validate_csv(build(tmp_path, [r]))
    assert any("tag-like text" in e for e in errors)
    assert any("Answer Option 4" in e for e in errors)
    assert any("<role>" in e and "<context>" in e and "<output>" in e
               for e in errors)


def test_closing_and_self_closing_tags_are_caught(tmp_path):
    r = base_row()
    r[15] = "See </example> and <br/> in the draft"
    errors = validate_csv(build(tmp_path, [r]))
    assert any("tag-like text" in e for e in errors)


def test_comparisons_and_arrows_are_not_flagged_as_tags(tmp_path):
    """`a < b` や `->` を誤検知しないこと（比較や矢印は正当な本文）。"""
    r = base_row()
    r[0] = "If latency < 200 ms and cost > budget, what applies? A -> B"
    r[15] = "Correct: 3 < 5 and 10 > 2. Source: https://example.com"
    assert validate_csv(build(tmp_path, [r])) == []


def test_markdown_bold_is_an_error(tmp_path):
    """Udemy は Markdown を解釈しないので `**` が記号のまま表示される。"""
    r = base_row()
    r[3] = "This is **important** because ..."
    errors = validate_csv(build(tmp_path, [r]))
    assert any("Markdown" in e and "Explanation 1" in e for e in errors)


def test_markdown_heading_and_bullet_are_errors(tmp_path):
    r = base_row()
    r[15] = "# Summary" + chr(10) + "- point one" + chr(10) + "Source: https://example.com"
    errors = validate_csv(build(tmp_path, [r]))
    assert any("Markdown" in e and "Overall Explanation" in e for e in errors)


def test_code_like_double_asterisks_are_not_flagged(tmp_path):
    """`**kwargs` や `a ** b` は正当な本文。対にならない・前後が空白の `**` は拾わない。"""
    r = base_row()
    r[0] = "What does def f(**kwargs) accept, and what is 2 ** 3?"
    r[15] = "Both f(**a, **b) and glob patterns like src/**/*.py work. Source: https://example.com"
    assert validate_csv(build(tmp_path, [r])) == []


def test_referring_to_an_option_by_number_is_an_error(tmp_path):
    """シャッフルで番号の指す先が変わる。"""
    r = base_row()
    r[5] = "選択肢2が正解です。"
    errors = validate_csv(build(tmp_path, [r]))
    assert any("by number" in e and "Explanation 2" in e for e in errors)


def test_the_word_option_without_a_number_is_fine(tmp_path):
    r = base_row()
    r[5] = "この選択肢は誤りです。"
    assert validate_csv(build(tmp_path, [r])) == []


def _warn(tmp_path, **cells):
    r = base_row()
    for idx, val in cells.items():
        r[int(idx.lstrip("c"))] = val
    return layout_warnings(build(tmp_path, [r]))


def test_a_long_overall_explanation_without_a_line_break_warns(tmp_path):
    warns = _warn(tmp_path, c15="あ" * 250 + "。")
    assert any("Overall Explanation" in w and "no line break" in w for w in warns)


def test_paragraphs_separated_by_blank_lines_do_not_warn(tmp_path):
    body = ("あ" * 120 + "。") + chr(10) + chr(10) + ("い" * 120 + "。")
    warns = _warn(tmp_path, c15=body + chr(10) + chr(10) + "出典: https://example.com")
    assert warns == []


def test_a_long_single_paragraph_warns_even_with_a_break(tmp_path):
    body = ("あ" * 250 + "。") + chr(10) + "短い段落。"
    warns = _warn(tmp_path, c15=body)
    assert any("paragraph over" in w for w in warns)


def test_a_long_option_explanation_on_one_line_warns(tmp_path):
    warns = _warn(tmp_path, c3="あ" * 160 + "。")
    assert any("Explanation 1" in w and "one line" in w for w in warns)


def test_a_source_on_the_same_line_or_without_a_blank_line_warns(tmp_path):
    same_line = _warn(tmp_path, c15="短い本文です。出典: https://example.com")
    single_break = _warn(tmp_path, c15="短い本文です。" + chr(10) + "出典: https://example.com")
    assert any("blank line before the source" in w for w in same_line)
    assert any("blank line before the source" in w for w in single_break)
    ok = _warn(tmp_path, c15="短い本文です。" + chr(10) + chr(10) + "出典: https://example.com")
    assert ok == []


def test_layout_warnings_never_fail_the_cli(tmp_path):
    """警告は表示するが exit code は 0 のまま（既存の講座を一括で落とさない）。"""
    import subprocess, sys
    from pathlib import Path
    r = base_row()
    r[15] = "あ" * 300 + "。"
    p = build(tmp_path, [r])
    script = Path(__file__).resolve().parents[1] / "plugins" / "udemy-exam-prep" / "scripts" / "validate_quiz_csv.py"
    proc = subprocess.run([sys.executable, str(script), str(p)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "WARN" in proc.stdout and "OK" in proc.stdout
