"""check_sources.py の source_scope（ドメインごとの出典の許可範囲）の検証。

ホストが同じでも別製品のドキュメントを出典にした問題は、出典欠落・禁止ホスト・
到達確認のどれにも引っかからない。front matter で許可範囲を宣言し、範囲外を
WARN（設定で FAIL）にする。
"""
import subprocess
import sys
from pathlib import Path

from scripts.check_sources import check_scope, in_prefix, load_scope, source_part, url_key
from scripts.validate_quiz_csv import HEADER, write_rows

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "udemy-exam-prep" / "scripts"

DOMAINS = [
    {"id": "D1", "name": "設計 ドメイン", "ratio": "50%", "per_exam": 1},
    {"id": "D2", "name": "運用ドメイン", "ratio": "50%", "per_exam": 1},
]


def profile(scope, **extra):
    p = {"domains": DOMAINS, "source_scope": scope}
    p.update(extra)
    return p


def row(url, domain="設計 ドメイン"):
    r = ["Q?", "multiple-choice"]
    for i in range(4):
        r += [f"opt{i}", f"exp{i}"]
    r += ["", "", "", ""]
    r += ["1", f"【要約】説明。\n\n出典: {url}", domain]
    return r


def rows(*rs):
    return [list(HEADER)] + list(rs)


# --- URL の比較 -------------------------------------------------------------

def test_locale_is_ignored_only_for_hosts_with_a_locale_rule():
    assert url_key("https://learn.microsoft.com/ja-jp/azure/x/") == (
        "learn.microsoft.com", ["azure", "x"])
    assert url_key("learn.microsoft.com/azure/x") == ("learn.microsoft.com", ["azure", "x"])
    # ロケール規則の無いホストでは2文字のセグメントを消さない
    assert url_key("https://docs.example.com/go/intro") == ("docs.example.com", ["go", "intro"])


def test_prefix_matches_on_segment_boundaries():
    assert in_prefix("https://docs.example.com/product-a/page", "docs.example.com/product-a/")
    assert in_prefix("https://docs.example.com/product-a", "https://docs.example.com/product-a")
    assert not in_prefix("https://docs.example.com/product-ab/page", "docs.example.com/product-a")
    assert not in_prefix("https://other.example.com/product-a/x", "docs.example.com/product-a")
    # ホストだけの接頭辞はそのホスト全体を許可する
    assert in_prefix("https://github.com/org/repo", "github.com")


def test_query_and_fragment_do_not_affect_the_match():
    assert in_prefix("https://docs.example.com/a/b?view=1#sec", "docs.example.com/a/b")


# --- 設定の読み込み ---------------------------------------------------------

def test_no_scope_means_no_check():
    assert load_scope({"domains": DOMAINS}) == (None, [])


def test_scope_config_errors_are_reported_not_ignored():
    scope, errs = load_scope(profile({"severity": "loud", "domains": {"D9": ["x.test"]}}))
    assert scope is not None
    assert any("severity" in e for e in errs)
    assert any("D9" in e for e in errs)


def test_primary_sources_urls_can_be_included():
    p = profile({"include_primary_sources": True}, primary_sources=[
        {"priority": 1, "tool": "local-file", "scope": "research/guide.txt"},
        {"priority": 2, "tool": "WebFetch",
         "scope": "https://docs.example.com/ja-jp/product-a/ - 製品Aのドキュメント"},
    ])
    scope, errs = load_scope(p)
    assert not errs
    assert scope["common"] == ["https://docs.example.com/ja-jp/product-a/"]


# --- 判定 -------------------------------------------------------------------

def test_out_of_scope_source_is_reported_with_its_domain():
    scope, _ = load_scope(profile({
        "common": ["docs.example.com/product-a/"],
        "domains": {"D2": ["docs.example.com/identity/"]},
    }))
    out = check_scope(rows(
        row("https://docs.example.com/product-a/overview"),
        row("https://docs.example.com/product-b/evaluate"),           # 別製品
        row("https://docs.example.com/identity/rbac", "運用ドメイン"),   # D2 には許可
        row("https://docs.example.com/identity/rbac"),                # D1 には不許可
    ), scope)
    assert len(out) == 2
    assert out[0].startswith("Q2 [D1]") and "product-b" in out[0]
    assert out[1].startswith("Q4 [D1]")


def test_domain_name_spacing_drift_still_resolves():
    scope, _ = load_scope(profile({"common": ["docs.example.com/a/"]}))
    out = check_scope(rows(row("https://docs.example.com/b/", "設計ドメイン")), scope)
    assert out and "[D1]" in out[0]


def test_unknown_domain_rows_and_unscoped_domains_are_skipped():
    scope, _ = load_scope(profile({"domains": {"D2": ["docs.example.com/ops/"]}}))
    out = check_scope(rows(
        row("https://docs.example.com/any/"),                    # D1: 許可リスト空 -> 検査しない
        row("https://docs.example.com/any/", "存在しないドメイン"),  # validate_exam の担当
    ), scope)
    assert out == []


def test_urls_in_the_body_are_not_treated_as_sources():
    overall = "本文で https://api.example.test/.default を指定する。\n\n出典: https://docs.example.com/a/x"
    assert "api.example.test" not in source_part(overall)
    scope, _ = load_scope(profile({"common": ["docs.example.com/a/"]}))
    r = row("")
    r[15] = overall
    assert check_scope(rows(r), scope) == []


# --- CLI: WARN と FAIL -------------------------------------------------------

def _sections(tmp_path, severity):
    text = (
        "---\n"
        "domains:\n"
        "  - {id: D1, name: 設計 ドメイン, ratio: '100%', per_exam: 1}\n"
        "source_scope:\n"
        f"  severity: {severity}\n"
        "  common:\n"
        "    - docs.example.com/product-a/\n"
        "---\n"
    )
    p = tmp_path / "sections.md"
    p.write_text(text, encoding="utf-8")
    return p


def _run(tmp_path, severity, *extra):
    quiz = tmp_path / "quiz.csv"
    write_rows(quiz, rows(row("https://docs.example.com/product-b/page")))
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "check_sources.py"), str(quiz),
         "--sections", str(_sections(tmp_path, severity)), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def test_cli_warns_by_default(tmp_path):
    proc = _run(tmp_path, "warn")
    assert proc.returncode == 0, proc.stdout
    assert "WARN" in proc.stdout and "product-b" in proc.stdout


def test_cli_fails_when_configured(tmp_path):
    proc = _run(tmp_path, "fail")
    assert proc.returncode == 1, proc.stdout
    assert "FAIL" in proc.stdout


def test_cli_scope_strict_flag_escalates(tmp_path):
    proc = _run(tmp_path, "warn", "--scope-strict")
    assert proc.returncode == 1, proc.stdout


# --- profile.py の validate_profile も同じ判定で落とす ------------------------
#
# check_sources.py を走らせるまで設定の誤りに気づかないと、打ち間違い1つで
# ドメインの検査が止まったまま作問が進む。front matter の検証（R1）で落とす。

def _valid_profile(scope):
    return {
        "cert": "X", "cert_name": "X", "vendor": "generic", "study_guide": "u",
        "mode": "mock-exam", "exam": {"minutes": 1, "pass_score": 1, "language": "ja"},
        "mock_exams": 1, "questions_per_exam": 2, "question_types": {},
        "primary_sources": [],
        "domains": [
            {"id": "D1", "name": "A", "ratio": "50%", "per_exam": 1},
            {"id": "D4", "name": "B", "ratio": "50%", "per_exam": 1},
        ],
        "source_scope": scope,
    }


def test_validate_profile_accepts_a_well_formed_scope():
    from scripts.profile import validate_profile
    scope = {"severity": "warn", "include_primary_sources": True,
             "common": ["docs.example.com/product-a/"],
             "domains": {"D4": ["docs.example.com/identity/"]}}
    assert validate_profile(_valid_profile(scope)) == []


def test_validate_profile_rejects_scope_errors():
    from scripts.profile import validate_profile
    errs = validate_profile(_valid_profile({"domains": {"D9": ["docs.example.com/x/"]}}))
    assert any("D9" in e for e in errs)
    errs = validate_profile(_valid_profile({"severity": "error"}))
    assert any("severity" in e for e in errs)
    errs = validate_profile(_valid_profile({"domains": {"D1": {"a": 1}}}))
    assert any("リストではない" in e for e in errs)
    errs = validate_profile(_valid_profile(["docs.example.com/"]))
    assert any("マッピングではない" in e for e in errs)
