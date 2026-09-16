from scripts.validate_quiz_csv import HEADER, read_rows, validate_csv, write_rows


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


def test_in_cell_newline_is_an_error(tmp_path):
    """セル内改行は Udemy の一括取り込みでの破損要因なので落とす。

    csv としては正しく引用されるため、列数・ヘッダー・正解番号の検査は
    すべて通ってしまう。それでも落ちることを確認する。
    """
    r = base_row()
    r[15] = "1行目" + chr(10) + chr(10) + "2行目"
    errors = validate_csv(build(tmp_path, [r]))
    assert any("in-cell newline" in e for e in errors)
    assert any("Overall Explanation" in e for e in errors)


def test_carriage_return_in_cell_is_an_error(tmp_path):
    r = base_row()
    r[0] = "Question" + chr(13) + "continued"
    assert any("in-cell newline" in e for e in validate_csv(build(tmp_path, [r])))


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
