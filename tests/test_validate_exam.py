import textwrap
from scripts.validate_exam import (
    bank_rows, check_duplicates, check_quota, domain_counts, parse_question_bank,
)
from scripts.validate_quiz_csv import HEADER

PROFILE = {
    "questions_per_exam": 4,
    "mock_exams": 2,
    "domains": [
        {"id": "D1", "name": "Alpha", "ratio": "50%", "per_exam": 2},
        {"id": "D2", "name": "Beta", "ratio": "50%", "per_exam": 2},
    ],
}


def row(domain):
    r = ["Q?", "multiple-choice"]
    for i in range(6):
        r += ([f"OPT{i + 1}", f"EXP{i + 1}"] if i < 4 else ["", ""])
    return r + ["1", "overall", domain]


def test_domain_counts():
    rows = [list(HEADER), row("Alpha"), row("Alpha"), row("Beta")]
    assert domain_counts(rows) == {"Alpha": 2, "Beta": 1}


def test_check_quota_passes_when_counts_match():
    rows = [list(HEADER), row("Alpha"), row("Alpha"), row("Beta"), row("Beta")]
    assert check_quota(rows, PROFILE) == []


def test_check_quota_reports_a_shortfall():
    rows = [list(HEADER), row("Alpha"), row("Beta"), row("Beta"), row("Beta")]
    errs = check_quota(rows, PROFILE)
    assert any("Alpha" in e and "1" in e and "2" in e for e in errs)


def test_check_quota_reports_an_unknown_domain():
    rows = [list(HEADER), row("Gamma"), row("Alpha"), row("Beta"), row("Beta")]
    assert any("Gamma" in e for e in check_quota(rows, PROFILE))


BANK = textwrap.dedent("""\
    # Question Bank

    | section | q# | domain | task_statement | tested_concept | scenario | head |
    |---|---|---|---|---|---|---|
    | section01 | Q1 | D1 | 1.1 | stop_reason loop control | S1 | Your agent ... |
    | section01 | Q2 | D2 | 2.1 | tool description quality | S1 | Both tools ... |
    | section02 | Q1 | D1 | 1.1 | stop_reason loop control | S3 | The loop ... |
    """)


def test_parse_question_bank(tmp_path):
    p = tmp_path / "question-bank.md"
    p.write_text(BANK, encoding="utf-8")
    entries = parse_question_bank(p)
    assert len(entries) == 3
    assert entries[0]["task_statement"] == "1.1"
    assert entries[2]["scenario"] == "S3"


def test_parse_question_bank_returns_empty_when_absent(tmp_path):
    assert parse_question_bank(tmp_path / "nope.md") == []


def test_check_duplicates_allows_two_uses_in_different_scenarios(tmp_path):
    p = tmp_path / "question-bank.md"
    p.write_text(BANK, encoding="utf-8")
    assert check_duplicates(parse_question_bank(p)) == []


def test_check_duplicates_reports_a_third_use():
    entries = [
        {"section": f"section0{i}", "q": "Q1", "domain": "D1",
         "task_statement": "1.1", "tested_concept": "same concept",
         "scenario": f"S{i}", "head": "..."}
        for i in (1, 2, 3)
    ]
    assert any("3 times" in e for e in check_duplicates(entries))


def test_check_duplicates_honors_a_raised_cap():
    entries = [
        {"section": f"section0{i}", "q": "Q1", "domain": "D1",
         "task_statement": "1.1", "tested_concept": "same concept",
         "scenario": f"S{i}", "head": "..."}
        for i in (1, 2, 3)
    ]
    assert check_duplicates(entries, max_per_concept=3) == []


def test_check_duplicates_reports_same_section_repeat():
    entries = [
        {"section": "section01", "q": q, "domain": "D1",
         "task_statement": "1.1", "tested_concept": "same concept",
         "scenario": "S1", "head": "..."}
        for q in ("Q1", "Q2")
    ]
    assert any("same section" in e for e in check_duplicates(entries))


def test_check_duplicates_reports_same_scenario_reuse():
    entries = [
        {"section": f"section0{i}", "q": "Q1", "domain": "D1",
         "task_statement": "1.1", "tested_concept": "same concept",
         "scenario": "S1", "head": "..."}
        for i in (1, 2)
    ]
    assert any("same scenario" in e for e in check_duplicates(entries))


def test_bank_rows_emits_pipe_table_rows():
    entries = [{"section": "section01", "q": "Q1", "domain": "D1",
                "task_statement": "1.1", "tested_concept": "c",
                "scenario": "S1", "head": "h"}]
    line = bank_rows(entries)[0]
    assert line.startswith("| section01 | Q1 | D1 | 1.1 | c | S1 | h |")
