import textwrap
import pytest
from scripts.profile import (
    ProfileError, load_profile, validate_profile, domain_quota, domain_names,
)

VALID = textwrap.dedent("""\
    ---
    cert: CCA-F
    cert_name: Claude Certified Architect - Foundations
    vendor: anthropic
    study_guide: https://example.com/guide
    mode: mock-exam
    exam:
      minutes: 120
      pass_score: 720
      max_score: 1000
      language: en
    mock_exams: 6
    questions_per_exam: 60
    question_types:
      multiple-choice: "70%"
      multi-select: "30%"
    primary_sources:
      - priority: 1
        tool: local-pdf
        scope: Exam Guide
    domains:
      - id: D1
        name: Agentic Architecture & Orchestration
        ratio: "27%"
        per_exam: 16
      - id: D2
        name: Tool Design & MCP Integration
        ratio: "18%"
        per_exam: 11
      - id: D3
        name: Claude Code Configuration & Workflows
        ratio: "20%"
        per_exam: 12
      - id: D4
        name: Prompt Engineering & Structured Output
        ratio: "20%"
        per_exam: 12
      - id: D5
        name: Context Management & Reliability
        ratio: "15%"
        per_exam: 9
    ---

    # 本文はここから
    """)


def write(tmp_path, text):
    p = tmp_path / "sections.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_profile_reads_front_matter(tmp_path):
    prof = load_profile(write(tmp_path, VALID))
    assert prof["cert"] == "CCA-F"
    assert prof["exam"]["minutes"] == 120
    assert len(prof["domains"]) == 5


def test_valid_profile_has_no_errors(tmp_path):
    assert validate_profile(load_profile(write(tmp_path, VALID))) == []


def test_missing_front_matter_raises(tmp_path):
    with pytest.raises(ProfileError):
        load_profile(write(tmp_path, "# front matter なし\n"))


def test_unterminated_front_matter_raises(tmp_path):
    with pytest.raises(ProfileError):
        load_profile(write(tmp_path, "---\ncert: X\n"))


def test_missing_required_key_is_reported(tmp_path):
    text = VALID.replace("cert_name: Claude Certified Architect - Foundations\n", "")
    errs = validate_profile(load_profile(write(tmp_path, text)))
    assert any("cert_name" in e for e in errs)


def test_per_exam_sum_mismatch_is_reported(tmp_path):
    text = VALID.replace("per_exam: 9", "per_exam: 8")
    errs = validate_profile(load_profile(write(tmp_path, text)))
    assert any("59" in e and "60" in e for e in errs)


def test_duplicate_domain_id_is_reported(tmp_path):
    text = VALID.replace("id: D5", "id: D4")
    errs = validate_profile(load_profile(write(tmp_path, text)))
    assert any("duplicate" in e.lower() for e in errs)


def test_non_mock_exam_mode_is_reported(tmp_path):
    text = VALID.replace("mode: mock-exam", "mode: topic-section")
    errs = validate_profile(load_profile(write(tmp_path, text)))
    assert any("mode" in e for e in errs)


def test_unknown_vendor_is_reported(tmp_path):
    text = VALID.replace("vendor: anthropic", "vendor: acme")
    errs = validate_profile(load_profile(write(tmp_path, text)))
    assert any("vendor" in e for e in errs)


def test_zero_mock_exams_is_reported(tmp_path):
    text = VALID.replace("mock_exams: 6", "mock_exams: 0")
    errs = validate_profile(load_profile(write(tmp_path, text)))
    assert any("mock_exams" in e for e in errs)


def test_domain_quota_and_names(tmp_path):
    prof = load_profile(write(tmp_path, VALID))
    assert domain_quota(prof) == {"D1": 16, "D2": 11, "D3": 12, "D4": 12, "D5": 9}
    assert domain_names(prof)["D3"] == "Claude Code Configuration & Workflows"
