"""講座リポジトリから昇格させた6本のスクリプトの検証。

いずれも「資格固有の情報は sections.md front matter だけが持つ」という
harness の原則を守れているかが検証の中心。ホスト名や試験コードが
スクリプト側にハードコードされていないことを確かめる。
"""
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_sources import check, load_policy
from scripts.merge_parts import read_meta
from scripts.profile import forbidden_sources, guide_citation, source_titles
from scripts.validate_quiz_csv import HEADER, write_rows

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "udemy-exam-prep" / "scripts"

PROMOTED = (
    "merge_parts.py", "finalize_section.py", "check_sources.py",
    "audit_course.py", "used_concepts.py", "make_sources_md.py",
)


def row(overall="【要約】説明。出典: https://example.com/docs", qtype="multiple-choice", correct="1"):
    r = ["Question text?", qtype]
    for i in range(4):
        r += [f"Option {i + 1}", f"選択肢{i + 1}の解説"]
    r += ["", "", "", ""]
    r += [correct, overall, "Domain 1"]
    return r


def build(tmp_path, rows, name="quiz.csv"):
    p = tmp_path / name
    write_rows(p, [list(HEADER)] + rows)
    return p


# --- 昇格したこと自体の確認 -------------------------------------------------

def test_all_promoted_scripts_exist():
    for n in PROMOTED:
        assert (SCRIPTS / n).is_file(), n


@pytest.mark.parametrize("name", PROMOTED)
def test_no_absolute_paths(name):
    """講座リポジトリ側では絶対パスでプラグインを参照していた。昇格後は残っていないこと。"""
    text = (SCRIPTS / name).read_text(encoding="utf-8")
    assert "Path(r\"C:" not in text, name
    assert "C:\\Users" not in text, name


@pytest.mark.parametrize("name", PROMOTED)
def test_runs_standalone(name):
    """`python .../scripts/x.py --help` が通る（__package__ ブートストラップの確認）。"""
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / name), "--help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, f"{name}: {proc.stderr[:300]}"


# --- 出典ポリシーが front matter 由来であること -----------------------------

def test_forbidden_hosts_come_from_the_profile(tmp_path):
    """禁止ホストはスクリプトに埋め込まず front matter から来る。"""
    bad = "example-store.test"
    rows = [row(overall=f"【要約】説明。出典: https://{bad}/buy")]
    p = build(tmp_path, rows)

    errs, _, _ = check(p, False, {}, None)
    assert not any(bad in e for e in errs), "禁止指定がないのに落としてはいけない"

    errs, _, _ = check(p, False, {bad: "製品ページで本文を含まない"}, None)
    assert any(bad in e and "製品ページ" in e for e in errs)


def test_subdomains_of_a_forbidden_host_are_caught(tmp_path):
    p = build(tmp_path, [row(overall="出典: https://sub.bad.test/x")])
    errs, _, _ = check(p, False, {"bad.test": "理由"}, None)
    assert any("bad.test" in e for e in errs)


def test_missing_citation_is_always_detected(tmp_path):
    """禁止ホストの指定が無くても、出典の欠落は必ず落とす。"""
    p = build(tmp_path, [row(overall="【要約】出典を書き忘れた解説。")])
    errs, _, _ = check(p, False, {}, None)
    assert any("出典がない" in e for e in errs)


def test_exam_guide_reference_counts_as_a_citation(tmp_path):
    p = build(tmp_path, [row(overall="【要約】説明。出典: 公式 Exam Guide（X-999）§6 Task Statement 1.1")])
    errs, _, _ = check(p, False, {}, None)
    assert not any("出典がない" in e for e in errs)


def test_load_policy_tolerates_a_missing_sections_file(tmp_path):
    """sections.md が無くても落ちない（出典欠落の検査だけは効かせたい）。"""
    forbidden, guide_re = load_policy(tmp_path / "no-such-sections.md")
    assert forbidden == {}
    assert guide_re.search("公式 Exam Guide（X-999）")


# --- profile のアクセサ ------------------------------------------------------

def test_profile_accessors_default_to_empty():
    assert forbidden_sources({}) == {}
    assert source_titles({}) == {}


def test_forbidden_sources_accepts_plain_strings():
    got = forbidden_sources({"forbidden_sources": ["a.test", {"host": "b.test", "reason": "理由"}]})
    assert got == {"a.test": "", "b.test": "理由"}


def test_guide_citation_falls_back_to_the_exam_code():
    assert guide_citation({"exam_code": "X-999"}) == "公式 Exam Guide（X-999）"
    assert guide_citation({"cert": "Y-1"}) == "公式 Exam Guide（Y-1）"
    assert guide_citation({"guide_citation": "Official Guide"}) == "Official Guide"


# --- merge_parts の meta 読み取り -------------------------------------------

def test_read_meta_skips_a_header_row(tmp_path):
    """エージェントがヘッダー行を付けてくることがある（実績あり）。捨てる。"""
    p = tmp_path / "D1-meta.tsv"
    p.write_text(
        "no\tdomain\ttask\tconcept\tscenario\thead\n"
        "1\tD1\t1.1\t概念A\tS1\t問題文の冒頭\n"
        "2\tD1\t1.2\t概念B\tS3\t問題文の冒頭\n",
        encoding="utf-8", newline="\n",
    )
    rows = read_meta(p)
    assert len(rows) == 2
    assert rows[0]["task_statement"] == "1.1"
    assert rows[1]["tested_concept"] == "概念B"


def test_read_meta_rejects_too_few_columns(tmp_path):
    p = tmp_path / "D1-meta.tsv"
    p.write_text("1\tD1\t1.1\n", encoding="utf-8", newline="\n")
    with pytest.raises(SystemExit):
        read_meta(p)
