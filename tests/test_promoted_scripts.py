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
from scripts.merge_parts import head_mismatches, merge, read_meta
from scripts.profile import forbidden_sources, guide_citation, source_titles
from scripts.validate_quiz_csv import HEADER, write_rows

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "udemy-exam-prep" / "scripts"

# タブ区切り meta を組むときのエスケープ事故を避けるため定数で持つ
TAB = chr(9)
NL = chr(10)

PROMOTED = (
    "merge_parts.py", "finalize_section.py", "check_sources.py",
    "audit_course.py", "used_concepts.py", "make_sources_md.py",
    "check_style.py",
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


# --- merge_parts: meta の head と CSV の突き合わせ --------------------------
#
# 長さバイアスの是正や創作識別子のリネームで CSV を外科的に直すと、meta の
# head だけが古くなる（実績: ある講座で5本13ファイル）。head は CSV を正とし、
# ずれ（行の対応が壊れている）と古さ（編集されただけ）を区別して報告する。

def _body(*heads):
    out = []
    for h in heads:
        r = row()
        r[0] = h
        out.append(r)
    return out


def _meta(*heads):
    return [
        {"local_no": str(i), "domain": "D1", "task_statement": "1.1",
         "tested_concept": f"概念{i}", "scenario": "S1", "head": h}
        for i, h in enumerate(heads, 1)
    ]


def test_head_mismatches_is_quiet_when_meta_matches():
    body = _body("A bank's agent calls lookup_order first.", "A hospital pipeline extracts labs.")
    meta = _meta("A bank's agent calls lookup_order", "A hospital pipeline extracts")
    assert head_mismatches(body, meta) == ([], [])


def test_head_mismatches_tolerates_whitespace_and_case_and_ellipsis():
    """エージェントは冒頭を手で写すので揺れる。揺れでは警告しない。"""
    body = _body("A  Bank's Agent   calls lookup_order first.")
    meta = _meta("a bank's agent calls lookup_order...")
    assert head_mismatches(body, meta) == ([], [])


def test_head_mismatches_reports_a_stale_head_as_a_warning():
    """CSV だけ直した状態。CSV を採用するが、同じ行の概念も古い疑いを残す。"""
    body = _body("A bank's agent calls fetch_order first.")
    meta = _meta("A bank's agent calls lookup_order")
    misaligned, stale = head_mismatches(body, meta)
    assert misaligned == []
    assert len(stale) == 1
    assert "1 行目" in stale[0]


def test_head_mismatches_reports_a_row_shift_as_a_failure():
    """meta が1行ずれると tested_concept が別の問題に紐づく。致命的。"""
    body = _body("QUESTION ONE about tools.", "QUESTION TWO about retrieval.")
    meta = _meta("QUESTION TWO about retrieval", "QUESTION ONE about tools")
    misaligned, stale = head_mismatches(body, meta)
    assert len(misaligned) == 2
    assert "行がずれている" in misaligned[0]
    assert stale == []


def test_head_mismatches_ignores_an_empty_head():
    body = _body("Anything at all.")
    assert head_mismatches(body, _meta("")) == ([], [])


# --- merge() 本体への配線（head は CSV を正とする / ずれは止める） ----------

MERGE_PROFILE = {
    "mode": "mock-exam",
    "mock_exams": 1,
    "questions_per_exam": 2,
    "domains": [{"id": "D1", "name": "Domain 1", "ratio": "100%", "per_exam": 2}],
}


def _build_part(section, csv_heads, meta_heads):
    parts = section / "_parts"
    parts.mkdir(parents=True, exist_ok=True)
    write_rows(parts / "D1.csv", [list(HEADER)] + _body(*csv_heads))
    rows = [
        TAB.join([str(i), "D1", "1.1", f"概念{i}", "S1", h])
        for i, h in enumerate(meta_heads, 1)
    ]
    (parts / "D1-meta.tsv").write_text(
        NL.join(rows) + NL, encoding="utf-8", newline=NL,
    )
    return section


def test_merge_takes_the_question_head_from_the_csv_not_the_meta(tmp_path):
    """CSV を外科的に直しても question-bank の問題文が実物と一致する。"""
    section = _build_part(
        tmp_path / "section01-mock-exam-1",
        ["RENAMED calls fetch_order now.", "Second question stands."],
        ["OLD calls lookup_order now.", "Second question stands"],
    )
    result = merge(section, MERGE_PROFILE, keep_parts=True)
    bank = Path(result["bank_rows"]).read_text(encoding="utf-8")
    assert "RENAMED calls fetch_order now." in bank
    assert "lookup_order" not in bank
    assert len(result["warnings"]) == 1


def test_merge_stops_when_the_meta_rows_are_shifted(tmp_path):
    """tested_concept が別の問題に紐づく破損。通してはいけない。"""
    section = _build_part(
        tmp_path / "section01-mock-exam-1",
        ["QUESTION ONE about tools.", "QUESTION TWO about retrieval."],
        ["QUESTION TWO about retrieval", "QUESTION ONE about tools"],
    )
    with pytest.raises(SystemExit):
        merge(section, MERGE_PROFILE, keep_parts=True)


def test_merge_is_quiet_on_a_clean_section(tmp_path):
    section = _build_part(
        tmp_path / "section01-mock-exam-1",
        ["QUESTION ONE about tools.", "QUESTION TWO about retrieval."],
        ["QUESTION ONE about tools", "QUESTION TWO about retrieval"],
    )
    result = merge(section, MERGE_PROFILE, keep_parts=True)
    assert result["warnings"] == []
    assert result["total"] == 2
