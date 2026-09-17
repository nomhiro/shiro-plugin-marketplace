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
    "MODE": "mock-exam",
}

# mixed モード（本ごとに問題数と配分が違う構成）で展開したときの値
MIXED_VALUES = {**VALUES, "MODE": "mixed"}

EXPECTED_FILES = {
    "CLAUDE.md",
    "sections.md",
    "question-bank.md",
    "removed-questions.md",
    ".gitignore",
    "PracticeTestBulkQuestionUploadTemplate_V2.2.csv",
    "AUTHOR-BRIEF.md",
    "research/AUTHORING-GUARDRAILS.md",
}


def test_placeholders_match_the_values_fixture():
    """プレースホルダの増減はここで検出する。

    個数のリテラル固定（8個）はプレースホルダを1つ足すたびに壊れる一方、
    「テンプレートとテストの値がずれた」という本当に見たい事故は
    この集合比較で捕まる。
    """
    assert set(PLACEHOLDERS) == set(VALUES)
    assert len(PLACEHOLDERS) == len(set(PLACEHOLDERS)), "重複がある"
    assert all(k.isupper() for k in PLACEHOLDERS)


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
    header = (tmp_path / "PracticeTestBulkQuestionUploadTemplate_V2.2.csv").read_text(
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


def test_expanded_sections_md_is_valid_in_mixed_mode(tmp_path):
    """mixed で展開した直後は sections が未記入（コメントのみ）。

    この時点では domains も未確定なので FAIL が正常。ただし
    「mode が未対応」のような**値の誤り**は出ていてはいけない。
    """
    init_course(tmp_path, MIXED_VALUES)
    profile = load_profile(tmp_path / "sections.md")
    assert profile["mode"] == "mixed"
    errs = validate_profile(profile)
    assert any("domains" in e for e in errs), errs
    assert not any("mode" in e for e in errs), errs


# --- 展開された雛形が「作問の前に埋めるべき穴」を明示しているか -------------
#
# 実績: ブリーフに機械検査される書式が1つも書かれておらず、6本378問が
# 全滅しかけた。ガードレールの所有表も雛形に節が無く、4本目で必要になって
# から遡って作った。どちらも雛形に差し込み口が無かったことが原因。

def test_brief_has_a_slot_for_the_machine_checked_style_contract(tmp_path):
    init_course(tmp_path, VALUES)
    text = (tmp_path / "AUTHOR-BRIEF.md").read_text(encoding="utf-8")
    assert "5-1" in text
    assert "--print-contract" in text, "契約の生成コマンドが書かれていない"
    assert "（未生成）" in text, "未生成であることが作問者に見えない"


def test_brief_self_check_runs_the_style_checker(tmp_path):
    """check_style.py を自己チェックから外すと、書式のずれが全問に乗って発覚する。"""
    init_course(tmp_path, VALUES)
    text = (tmp_path / "AUTHOR-BRIEF.md").read_text(encoding="utf-8")
    assert "check_style.py" in text


def test_brief_forbids_re_delegation(tmp_path):
    """作問エージェントが fork へ委譲すると、停止しても親から見えない。"""
    init_course(tmp_path, VALUES)
    text = (tmp_path / "AUTHOR-BRIEF.md").read_text(encoding="utf-8")
    assert "再委譲" in text


def test_guardrails_have_a_topic_ownership_table(tmp_path):
    """数値事実の重複はどの文面照合でも捕まらない。所有表だけが防げる。"""
    init_course(tmp_path, VALUES)
    text = (tmp_path / "research" / "AUTHORING-GUARDRAILS.md").read_text(encoding="utf-8")
    assert "## K. 論点の所有表" in text
    assert "所有ドメイン" in text


def test_guardrails_name_the_duplications_that_pass_every_check(tmp_path):
    init_course(tmp_path, VALUES)
    text = (tmp_path / "research" / "AUTHORING-GUARDRAILS.md").read_text(encoding="utf-8")
    assert "K-2" in text
    # 再利用が許容される4条件がそろっているか
    for cond in ("max_per_concept", "シナリオ", "構造から違う", "症状"):
        assert cond in text, cond
