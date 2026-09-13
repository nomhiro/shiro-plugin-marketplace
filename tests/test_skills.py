import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "udemy-exam-prep"
SKILLS = PLUGIN / "skills"

EXPECTED = {
    "init-exam-course", "create-sections", "create-section", "create-udemy-course",
    "upload-practice-tests", "quiz-csv-format", "research-cert-docs",
    "udemy-bulk-upload",
}
# 汎用化したのに AI-103 固有の記述が残っていたら退行。
# ベンダー別レシピ表の中の製品名（例: "Azure AI Search hybrid search" という検索クエリ例）は
# 正当なので禁止しない。禁止するのは「この harness が特定資格に固定されている」痕跡のみ。
FORBIDDEN = (
    "AI-103",
    "Foundry",
    "Microsoft Learn が一次情報源",
    "D1=14",
    "生成 AI とエージェント ソリューションの実装",
    "コンピューター ビジョン ソリューションの実装",
    "情報抽出ソリューションの実装",
)


def skill_files():
    return sorted(SKILLS.glob("*/SKILL.md"))


def front_matter(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].strip() == "---", f"{path}: front matter がない"
    end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
    return "\n".join(lines[1:end])


def test_all_expected_skills_exist():
    assert {p.parent.name for p in skill_files()} == EXPECTED


def test_every_skill_has_name_and_description():
    for p in skill_files():
        fm = front_matter(p)
        assert re.search(r"^name:\s*\S+", fm, re.M), p
        assert re.search(r"^description:\s*\S+", fm, re.M), p


def test_skill_name_matches_its_directory():
    for p in skill_files():
        name = re.search(r"^name:\s*(\S+)", front_matter(p), re.M).group(1)
        assert name == p.parent.name, p


def test_no_cert_specific_leftovers():
    for p in skill_files():
        text = p.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            assert token not in text, f"{p}: 資格固有語 '{token}' が残っている"


def test_scripts_are_called_through_plugin_root():
    """スキルは Python を再掲せず CLAUDE_PLUGIN_ROOT 経由でスクリプトを呼ぶ。"""
    callers = {
        "quiz-csv-format": "validate_quiz_csv.py",
        "create-section": "shuffle_options.py",
        "init-exam-course": "init_course.py",
        "create-sections": "profile.py",
        "upload-practice-tests": "validate_quiz_csv.py",
        "udemy-bulk-upload": "validate_quiz_csv.py",
    }
    for skill, script in callers.items():
        text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "${CLAUDE_PLUGIN_ROOT}" in text, skill
        assert script in text, f"{skill} が {script} を呼んでいない"


def test_create_section_calls_the_whole_pipeline():
    text = (SKILLS / "create-section" / "SKILL.md").read_text(encoding="utf-8")
    for script in ("profile.py", "validate_quiz_csv.py", "validate_exam.py",
                   "normalize_urls.py", "shuffle_options.py"):
        assert script in text, script


def test_entrypoint_skills_document_the_namespaced_invocation():
    for skill in ("init-exam-course", "create-sections", "create-section",
                  "create-udemy-course", "upload-practice-tests"):
        text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert f"/udemy-exam-prep:{skill}" in text, skill


def test_research_skill_lists_every_supported_vendor():
    text = (SKILLS / "research-cert-docs" / "SKILL.md").read_text(encoding="utf-8")
    for vendor in ("anthropic", "microsoft", "github", "cloudflare", "ipa", "generic"):
        assert vendor in text, vendor


def test_shuffle_guidance_warns_against_a_single_fixed_seed():
    """固定シードの既知事故を退行させないための歯止め。"""
    text = (SKILLS / "create-section" / "SKILL.md").read_text(encoding="utf-8")
    assert "quiz.raw.csv" in text
    assert "seed=42" in text  # 事故の実績として明記されている
    assert "再シャッフルの罠" in text


def test_udemy_skills_record_the_six_test_limit():
    for skill in ("udemy-bulk-upload", "upload-practice-tests"):
        text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "最大6" in text, skill


def test_udemy_skills_refuse_to_enter_credentials():
    for skill in ("udemy-bulk-upload", "create-udemy-course",
                  "upload-practice-tests"):
        text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "資格情報を自分で入力してはいけない" in text, skill


def test_skills_do_not_press_publish():
    for skill in ("create-udemy-course", "upload-practice-tests"):
        text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "公開ボタンは押さない" in text, skill
