import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "udemy-exam-prep"
AGENTS = PLUGIN / "agents"

EXPECTED = {"doc-researcher", "question-author", "exam-validator"}
# AI-103 に固定されている痕跡が残っていたら退行
FORBIDDEN = (
    "AI-103",
    "Foundry",
    "D1=14",
    "D1〜D5",
    "生成 AI とエージェント ソリューションの実装",
    "learn.microsoft.com/en-us",
)


def agent_files():
    return sorted(AGENTS.glob("*.md"))


def front_matter(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].strip() == "---", f"{path}: front matter がない"
    end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
    return "\n".join(lines[1:end])


def test_all_expected_agents_exist():
    assert {p.stem for p in agent_files()} == EXPECTED


def test_every_agent_declares_name_description_tools_model():
    for p in agent_files():
        fm = front_matter(p)
        for key in ("name", "description", "tools", "model"):
            assert re.search(rf"^{key}:\s*\S+", fm, re.M), f"{p}: {key} がない"


def test_agent_name_matches_filename():
    for p in agent_files():
        name = re.search(r"^name:\s*(\S+)", front_matter(p), re.M).group(1)
        assert name == p.stem, p


def test_no_cert_specific_leftovers():
    for p in agent_files():
        text = p.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            assert token not in text, f"{p}: 資格固有語 '{token}' が残っている"


def test_doc_researcher_tools_avoid_environment_specific_mcp_names():
    """MCP ツール名は環境依存なので tools に書かない（本文で機能名として言及する）。"""
    fm = front_matter(AGENTS / "doc-researcher.md")
    tools = re.search(r"^tools:\s*(.+)$", fm, re.M).group(1)
    assert "mcp__" not in tools, tools
    assert "WebFetch" in tools and "WebSearch" in tools


def test_doc_researcher_defers_source_priority_to_the_skill():
    text = (AGENTS / "doc-researcher.md").read_text(encoding="utf-8")
    assert "[[research-cert-docs]]" in text
    assert "primary_sources" in text


def test_doc_researcher_requires_urls_and_antipatterns():
    text = (AGENTS / "doc-researcher.md").read_text(encoding="utf-8")
    assert "URL が1つも無い digest は失敗" in text
    assert "アンチパターンを必ず1つ以上拾う" in text


def test_question_author_defers_csv_rules_to_the_skill():
    text = (AGENTS / "question-author.md").read_text(encoding="utf-8")
    assert "[[quiz-csv-format]]" in text
    # 17カラムの規約を再掲していない（定義元は quiz-csv-format ただ1つ）
    assert "Answer Option 5" not in text


def test_question_author_writes_incrementally():
    """接続断で一括生成が丸ごとロストした実績への歯止め。"""
    text = (AGENTS / "question-author.md").read_text(encoding="utf-8")
    assert "10問ごとに逐次ファイルへ追記" in text


def test_question_author_must_not_touch_the_question_bank():
    text = (AGENTS / "question-author.md").read_text(encoding="utf-8")
    assert "`question-bank.md` に追記・編集する" in text
    assert "[[exam-validator]] の責務" in text


def test_exam_validator_uses_the_validation_scripts():
    text = (AGENTS / "exam-validator.md").read_text(encoding="utf-8")
    assert "${CLAUDE_PLUGIN_ROOT}" in text
    assert "validate_exam.py" in text
    assert "validate_quiz_csv.py" in text


def test_exam_validator_checks_tag_against_content():
    """機械集計が通っても内容とタグの不一致は残るという知見。"""
    text = (AGENTS / "exam-validator.md").read_text(encoding="utf-8")
    assert "集計が一致していても安心しない" in text
    assert "中核事実" in text


def test_exam_validator_never_deletes_duplicates_automatically():
    text = (AGENTS / "exam-validator.md").read_text(encoding="utf-8")
    assert "自動削除" in text
    assert "報告" in text


def test_exam_validator_owns_the_question_bank():
    text = (AGENTS / "exam-validator.md").read_text(encoding="utf-8")
    assert "あなただけの責務" in text
    assert "BANK_FIELDS" in text


def test_question_author_obeys_the_glossary():
    """散文の「原語のまま」だけでは守られない（実績: 300問で約400件の和訳が混入）。"""
    text = (AGENTS / "question-author.md").read_text(encoding="utf-8")
    assert "glossary" in text and "forbid" in text
    assert "check_style.py" in text
