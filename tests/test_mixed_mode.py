"""mixed モード（本ごとに問題数とドメイン配分が違う構成）の契約。

mock-exam モードは「N本すべて同じ問題数のフル模試」しか表現できない。
G検定のように「分野別演習3本 + フル模試3本」を作るには本ごとの仕様が必要で、
それを front matter の sections が持つ。

**mock-exam モードも section_specs() が同じ形で返す**ので、下流のスクリプトは
mode を意識しない。既存講座の挙動が変わらないことも併せて固定する。
"""
import textwrap

import pytest

from scripts.profile import (
    domain_quota, load_profile, resolve_section, section_specs, validate_profile,
)

HEAD = """\
cert: GTEST
cert_name: テスト試験
vendor: generic
study_guide: https://example.com/guide
exam:
  minutes: 100
  pass_score: 70
  language: ja
question_types:
  multiple-choice: "60-70%"
primary_sources: []
domains:
  - {id: D1, name: Domain One, ratio: "40%", per_exam: 40}
  - {id: D2, name: Domain Two, ratio: "60%", per_exam: 60}
"""

MIXED_SECTIONS = """\
mode: mixed
mock_exams: 3
questions_per_exam: 100
sections:
  - slug: section01-drill-1
    title: 分野別演習① D1
    kind: drill
    questions: 30
    minutes: 40
    domains: {D1: 30}
  - slug: section02-drill-2
    title: 分野別演習② D2
    kind: drill
    questions: 50
    minutes: 60
    domains: {D2: 50}
  - slug: section03-mock-exam-1
    title: 模擬試験 第1回
    kind: mock
    questions: 100
    minutes: 100
"""

UNIFORM = """\
mode: mock-exam
mock_exams: 2
questions_per_exam: 100
"""


def write(tmp_path, body, name="sections.md"):
    p = tmp_path / name
    p.write_text(f"---\n{body}---\n\n# 本文\n", encoding="utf-8")
    return p


def mixed(tmp_path, sections=MIXED_SECTIONS):
    return load_profile(write(tmp_path, HEAD + sections))


# --- 検証 -------------------------------------------------------------------

def test_a_valid_mixed_profile_passes(tmp_path):
    assert validate_profile(mixed(tmp_path)) == []


def test_mixed_requires_sections(tmp_path):
    p = load_profile(write(tmp_path, HEAD + "mode: mixed\nmock_exams: 3\nquestions_per_exam: 100\n"))
    assert any("sections が非空のリスト" in e for e in validate_profile(p))


def test_section_count_must_match_mock_exams(tmp_path):
    body = MIXED_SECTIONS.replace("mock_exams: 3", "mock_exams: 6")
    errs = validate_profile(mixed(tmp_path, body))
    assert any("sections が 3 件だが mock_exams は 6" in e for e in errs)


def test_section_domains_must_sum_to_its_questions(tmp_path):
    """本ごとの配分が本ごとの問題数と合わないのは落とす。"""
    body = MIXED_SECTIONS.replace("questions: 30\n    minutes: 40", "questions: 31\n    minutes: 40")
    errs = validate_profile(mixed(tmp_path, body))
    assert any("domains の合計 30 が questions 31 と一致しない" in e for e in errs)


def test_omitting_domains_means_all_domains_so_questions_must_match_the_total(tmp_path):
    """domains 省略は「全ドメイン横断」の意味。per_exam 合計と違えば落とす。"""
    body = MIXED_SECTIONS.replace(
        "    questions: 100\n    minutes: 100", "    questions: 90\n    minutes: 100"
    )
    errs = validate_profile(mixed(tmp_path, body))
    assert any("per_exam 合計の 100 でなければならない" in e for e in errs)


def test_unknown_domain_id_in_a_section_is_an_error(tmp_path):
    body = MIXED_SECTIONS.replace("domains: {D1: 30}", "domains: {D9: 30}")
    errs = validate_profile(mixed(tmp_path, body))
    assert any("未知の domain id ['D9']" in e for e in errs)


def test_duplicate_slug_is_an_error(tmp_path):
    body = MIXED_SECTIONS.replace("slug: section02-drill-2", "slug: section01-drill-1")
    errs = validate_profile(mixed(tmp_path, body))
    assert any("duplicate slug" in e for e in errs)


def test_unknown_kind_is_an_error(tmp_path):
    body = MIXED_SECTIONS.replace("kind: drill", "kind: warmup", 1)
    errs = validate_profile(mixed(tmp_path, body))
    assert any("kind 'warmup' は未対応" in e for e in errs)


@pytest.mark.parametrize("bad", ["questions: 0", "minutes: 0"])
def test_non_positive_questions_or_minutes_is_an_error(tmp_path, bad):
    key, _ = bad.split(": ")
    body = MIXED_SECTIONS.replace(f"{key}: 30", bad).replace(f"{key}: 40", bad)
    errs = validate_profile(mixed(tmp_path, body))
    assert any(f"{key} は 1 以上の整数" in e for e in errs)


# --- section_specs ----------------------------------------------------------

def test_specs_carry_per_section_questions_minutes_and_quota(tmp_path):
    specs = section_specs(mixed(tmp_path))
    assert [s["questions"] for s in specs] == [30, 50, 100]
    assert [s["minutes"] for s in specs] == [40, 60, 100]
    assert [s["kind"] for s in specs] == ["drill", "drill", "mock"]
    assert specs[0]["quota"] == {"D1": 30}
    assert specs[1]["quota"] == {"D2": 50}


def test_a_section_without_domains_gets_the_global_quota(tmp_path):
    assert section_specs(mixed(tmp_path))[2]["quota"] == {"D1": 40, "D2": 60}


def test_uniform_mode_is_returned_in_the_same_shape(tmp_path):
    """mock-exam モードも同じ形で返るので下流は mode を見なくてよい。"""
    specs = section_specs(load_profile(write(tmp_path, HEAD + UNIFORM)))
    assert len(specs) == 2
    assert [s["slug"] for s in specs] == ["section01-mock-exam-1", "section02-mock-exam-2"]
    assert all(s["kind"] == "mock" for s in specs)
    assert all(s["questions"] == 100 for s in specs)
    assert all(s["minutes"] == 100 for s in specs)
    assert all(s["quota"] == {"D1": 40, "D2": 60} for s in specs)


# --- resolve_section --------------------------------------------------------

@pytest.mark.parametrize("ref", [
    "section02-drill-2",
    "section02-drill-2/",
    "section02-drill-2/quiz.csv",
    "C:/work/GTEST/section02-drill-2/quiz.csv",
    "section02-drill-2" + chr(92) + "quiz.csv",
    2,
])
def test_a_section_resolves_from_slug_path_or_number(tmp_path, ref):
    assert resolve_section(mixed(tmp_path), ref)["slug"] == "section02-drill-2"


@pytest.mark.parametrize("ref", ["section99-nope", "", 0, 99])
def test_an_unresolvable_reference_returns_none(tmp_path, ref):
    assert resolve_section(mixed(tmp_path), ref) is None


# --- domain_quota -----------------------------------------------------------

def test_quota_is_per_section_when_a_section_is_given(tmp_path):
    p = mixed(tmp_path)
    assert domain_quota(p, "section01-drill-1") == {"D1": 30}
    assert domain_quota(p, "section03-mock-exam-1/quiz.csv") == {"D1": 40, "D2": 60}


def test_quota_falls_back_to_the_global_one(tmp_path):
    """section 無し・解決不能ならグローバル。既存の呼び出しが壊れないこと。"""
    p = mixed(tmp_path)
    assert domain_quota(p) == {"D1": 40, "D2": 60}
    assert domain_quota(p, "section99-nope") == {"D1": 40, "D2": 60}


def test_quota_is_unchanged_for_uniform_profiles(tmp_path):
    p = load_profile(write(tmp_path, HEAD + UNIFORM))
    assert domain_quota(p) == {"D1": 40, "D2": 60}
    assert domain_quota(p, "section01-mock-exam-1") == {"D1": 40, "D2": 60}


def test_mutating_a_returned_quota_does_not_corrupt_the_profile(tmp_path):
    p = mixed(tmp_path)
    domain_quota(p, "section01-drill-1")["D1"] = 999
    assert domain_quota(p, "section01-drill-1") == {"D1": 30}


# --- ノルマ外のドメインを明示的に落とす -------------------------------------

def _rows(pairs):
    """(ドメイン名, 件数) から Domain 列だけ意味のある行を作る。"""
    head = [""] * 17
    out = [head]
    for name, n in pairs:
        for _ in range(n):
            r = [""] * 17
            r[16] = name
            out.append(r)
    return out


def test_a_domain_outside_this_sections_quota_is_reported_explicitly(tmp_path):
    """drill に担当外ドメインが混ざったら、その事実を名指しで落とす。

    以前は「担当ドメインが N 問足りない」という間接的な報告しか出ず、
    原因が読めなかった（実績: drill の1問を D1 -> D2 に変えたケース）。
    """
    from scripts.validate_exam import check_quota
    errs = check_quota(
        _rows([("Domain One", 2), ("Domain Two", 1)]),
        mixed(tmp_path),
        section="section01-drill-1",
    )
    assert any("covers only ['D1']" in e and 'D2 "Domain Two"' in e for e in errs)


def test_a_full_mock_accepts_every_domain(tmp_path):
    """domains 省略の mock 枠では全ドメインが正常。"""
    from scripts.validate_exam import check_quota
    errs = check_quota(
        _rows([("Domain One", 40), ("Domain Two", 60)]),
        mixed(tmp_path),
        section="section03-mock-exam-1",
    )
    assert errs == []


def test_uniform_profiles_never_trigger_the_out_of_scope_check(tmp_path):
    """mock-exam モードは全ドメインがノルマに入るので、この検査は発火しない。"""
    from scripts.validate_exam import check_quota
    p = load_profile(write(tmp_path, HEAD + UNIFORM))
    errs = check_quota(
        _rows([("Domain One", 40), ("Domain Two", 60)]),
        p,
        section="section01-mock-exam-1",
    )
    assert errs == []
