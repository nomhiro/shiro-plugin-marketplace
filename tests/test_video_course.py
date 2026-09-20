"""udemy-video-course プラグインの形だけを検証する。

ffmpeg / soffice / TTS を要する処理は CI では回せないので、ここでは
「宣言と実体がずれていないか」と「講座固有の記述が残っていないか」を見る。
唯一の例外は文体判定で、これは外部依存なしに単体で確かめられるため実際に呼ぶ。
"""
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "udemy-video-course"
SKILLS = PLUGIN / "skills"
AGENTS = PLUGIN / "agents"
SCRIPTS = PLUGIN / "scripts"

VERSION = "0.1.0"
MARKETPLACE_VERSION = "0.7.0"

EXPECTED_SKILLS = {"make-lecture-movie", "make-practice-movie", "record-practice-screen"}
EXPECTED_AGENTS = {"transcript-reviewer"}
EXPECTED_SCRIPTS = {
    "lecture_movie.py", "practice_movie.py",
    "build_rec.py", "redact.py", "stage_diagram.py",
    "qa_check.py", "leakcheck.py", "find_text_leak.py",
    "detect_events.py", "shift_lead.py",
}
# 特定の講座に固定されている痕跡が残っていたら退行
FORBIDDEN = ("AI-103", "Foundry", "GitHub Copilot 講座", "成果物規約.md", "カリキュラム設計書.md")


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def front_matter(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].strip() == "---", f"{path}: front matter がない"
    end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
    return "\n".join(lines[1:end])


def md_files():
    return sorted(SKILLS.glob("*/SKILL.md")) + sorted(AGENTS.glob("*.md"))


# ---------------------------------------------------------------- マニフェスト
def test_marketplace_lists_both_plugins():
    m = _load(REPO / ".claude-plugin" / "marketplace.json")
    names = [p["name"] for p in m["plugins"]]
    assert names == ["udemy-exam-prep", "udemy-video-course"]
    assert m["metadata"]["version"] == MARKETPLACE_VERSION


def test_plugin_entry_and_manifest_agree():
    m = _load(REPO / ".claude-plugin" / "marketplace.json")
    entry = next(p for p in m["plugins"] if p["name"] == "udemy-video-course")
    manifest = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    assert entry["source"] == "./plugins/udemy-video-course"
    assert entry["version"] == manifest["version"] == VERSION
    assert entry["description"].strip() and manifest["description"].strip()
    assert manifest["name"] == "udemy-video-course"


# ---------------------------------------------------------------- スキル/エージェント
def test_expected_skills_and_agents_exist():
    assert {p.parent.name for p in SKILLS.glob("*/SKILL.md")} == EXPECTED_SKILLS
    assert {p.stem for p in AGENTS.glob("*.md")} == EXPECTED_AGENTS


def test_front_matter_has_name_and_description():
    for p in md_files():
        fm = front_matter(p)
        assert re.search(r"^name:\s*\S+", fm, re.M), p
        assert re.search(r"^description:\s*\S+", fm, re.M), p


def test_name_matches_location():
    for p in SKILLS.glob("*/SKILL.md"):
        name = re.search(r"^name:\s*(\S+)", front_matter(p), re.M).group(1)
        assert name == p.parent.name, p
    for p in AGENTS.glob("*.md"):
        name = re.search(r"^name:\s*(\S+)", front_matter(p), re.M).group(1)
        assert name == p.stem, p


def test_no_course_specific_leftovers():
    for p in md_files():
        text = p.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            assert token not in text, f"{p}: 講座固有語 '{token}' が残っている"


def test_reviewer_agent_is_wired_into_the_pipeline():
    """第三者レビューを工程から外すと、機械チェックでは拾えない誤りが素通りする。"""
    practice = (SKILLS / "make-practice-movie" / "SKILL.md").read_text(encoding="utf-8")
    record = (SKILLS / "record-practice-screen" / "SKILL.md").read_text(encoding="utf-8")
    for text in (practice, record):
        assert "transcript-reviewer" in text
    assert "qa_check" in practice and "leakcheck" in practice


# ---------------------------------------------------------------- スクリプト
def test_expected_scripts_exist():
    assert EXPECTED_SCRIPTS <= {p.name for p in SCRIPTS.glob("*.py")}


def test_scripts_compile():
    import ast
    for p in SCRIPTS.glob("*.py"):
        ast.parse(p.read_text(encoding="utf-8"), filename=str(p))


# ---------------------------------------------------------------- 文体判定
@pytest.mark.parametrize("sentence", [
    "なぜこれを選ぶのか",          # 疑問
    "Foundry 版ですね",            # 終助詞つき
    "モデルだけ変えて2回投げる",    # 動詞の終止形
    "在り処を確かめる",
    "3つとも入っていますね",
    "押しません",
    "見ることになります",
    "そうでした",
    "やりましょう",
])
def test_predicate_endings_are_not_flagged(sentence):
    from qa_check import is_taigendome
    assert not is_taigendome(sentence)


@pytest.mark.parametrize("sentence", [
    "1つ目、グラウンディングの要否",   # 漢字＝名詞
    "権限もシンプル",                  # カタカナ
    "親リソース、リソースグループ、場所",
    "入力はテキストと画像、出力はテキスト",
    "同じ知識を2つの Bot で使い回したいこと",
])
def test_noun_endings_are_flagged(sentence):
    from qa_check import is_taigendome
    assert is_taigendome(sentence)


def test_transcript_parser_reads_both_segment_kinds(tmp_path):
    from qa_check import parse_transcript
    p = tmp_path / "x_transcript_rec.md"
    p.write_text(
        "# 台本\n\n"
        "## スライド1: はじめに\n\nこれは導入です。\n\n"
        "## 録画1 [00:00.00-00:30.50]: 開く\n\n画面を開きます。\n\n"
        "## スライド6: まとめ\n\nまとめます。\n", encoding="utf-8")
    segs = parse_transcript(p)
    kinds = [s["kind"] for s in segs]
    assert kinds == ["slide", "rec", "slide"]
    assert segs[1]["span"] == pytest.approx(30.5)
    assert segs[2]["n"] == 6
