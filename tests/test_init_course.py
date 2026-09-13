import pytest
from scripts.init_course import InitError, PLACEHOLDERS, init_course, render
from scripts.profile import load_profile, validate_profile

VALUES = {
    "CERT_ID": "CCA-F",
    "CERT_NAME": "Claude Certified Architect - Foundations",
    "VENDOR": "anthropic",
    "STUDY_GUIDE_URL": "https://example.com/guide",
    "EXAM_MINUTES": "120",
    "PASS_SCORE": "720",
    "MOCK_EXAMS": "6",
    "QUESTIONS_PER_EXAM": "60",
}

EXPECTED_FILES = {
    "CLAUDE.md",
    "sections.md",
    "question-bank.md",
    "removed-questions.md",
    ".gitignore",
    "PracticeTestBulkQuestionUploadTemplate_v2.csv",
}


def test_placeholders_are_exactly_eight():
    assert len(PLACEHOLDERS) == 8
    assert set(PLACEHOLDERS) == set(VALUES)


def test_render_substitutes_known_keys():
    assert render("cert: {{CERT_ID}}", VALUES) == "cert: CCA-F"


def test_render_rejects_unreplaced_placeholder():
    with pytest.raises(InitError):
        render("x: {{NOT_A_KEY}}", VALUES)


def test_init_course_creates_all_files(tmp_path):
    result = init_course(tmp_path, VALUES)
    assert set(result["created"]) == EXPECTED_FILES
    assert result["skipped"] == []
    for name in EXPECTED_FILES:
        assert (tmp_path / name).is_file()


def test_no_placeholder_survives_expansion(tmp_path):
    init_course(tmp_path, VALUES)
    for name in EXPECTED_FILES:
        if name.endswith(".csv"):
            continue
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert "{{" not in text, f"{name} に未置換のプレースホルダが残っている"


def test_expanded_sections_md_has_a_valid_profile(tmp_path):
    init_course(tmp_path, VALUES)
    profile = load_profile(tmp_path / "sections.md")
    assert profile["cert"] == "CCA-F"
    assert profile["vendor"] == "anthropic"
    assert profile["exam"]["minutes"] == 120
    assert profile["mock_exams"] == 6
    assert profile["questions_per_exam"] == 60
    # ドメイン表はテンプレート段階では未確定なので domains 欠落エラーだけが出る
    errs = validate_profile(profile)
    assert all("domains" in e for e in errs), errs


def test_init_course_is_idempotent_and_never_overwrites(tmp_path):
    init_course(tmp_path, VALUES)
    (tmp_path / "CLAUDE.md").write_text("手で編集した内容", encoding="utf-8")
    result = init_course(tmp_path, VALUES)
    assert result["created"] == []
    assert set(result["skipped"]) == EXPECTED_FILES
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "手で編集した内容"


def test_csv_template_has_the_17_column_header(tmp_path):
    init_course(tmp_path, VALUES)
    header = (tmp_path / "PracticeTestBulkQuestionUploadTemplate_v2.csv").read_text(
        encoding="utf-8-sig"
    ).splitlines()[0]
    assert len(header.split(",")) == 17
    assert header.startswith("Question,Question Type,Answer Option 1,Explanation 1,")
    assert header.endswith("Correct Answers,Overall Explanation,Domain")


def test_written_files_have_no_bom(tmp_path):
    init_course(tmp_path, VALUES)
    for name in EXPECTED_FILES:
        raw = (tmp_path / name).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{name} に BOM がある"
