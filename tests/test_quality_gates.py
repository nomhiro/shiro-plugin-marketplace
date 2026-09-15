"""CCDV-F 講座（6本318問）の運用で見つかった欠陥に対する退行テスト。

いずれも「検証がすべて OK を返しているのに成果物が壊れている」型だったため、
検査そのものをテストで固定する。
"""
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.audit_course import (
    OPTION_SIMILARITY_FAIL, OPTION_SIMILARITY_THRESHOLD,
    CONCEPT_SIMILARITY_THRESHOLD, IDENT_RE, digest_corpus,
    invented_identifiers, scenario_policy,
)
from scripts.check_sources import URL_RE
from scripts.validate_quiz_csv import HEADER, write_rows

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "udemy-exam-prep" / "scripts"


def row(question="Question text?", opts=None, correct="1"):
    r = [question, "multiple-choice"]
    opts = opts or [f"Option {i + 1}" for i in range(4)]
    for i in range(4):
        r += [opts[i], f"選択肢{i + 1}の解説"]
    r += ["", "", "", ""]
    r += [correct, "【要約】説明。出典: https://example.com/docs ", "Domain 1"]
    return r


# --- 重複検査の閾値 ---------------------------------------------------------

def test_option_similarity_threshold_is_low_enough_for_observed_duplicates():
    """実測 48% / 50% の重複を拾える閾値であること。

    0.80 では1件も捕まらなかった（問い方が違うと文面が散るため）。
    """
    assert OPTION_SIMILARITY_THRESHOLD <= 0.45
    assert OPTION_SIMILARITY_THRESHOLD < OPTION_SIMILARITY_FAIL


def test_concept_similarity_threshold_exists():
    """ラベル類似は文面照合をすり抜けた重複を最も多く捕まえた（55〜85%）。"""
    assert 0.5 <= CONCEPT_SIMILARITY_THRESHOLD <= 0.6


# --- 創作識別子 -------------------------------------------------------------

def test_ident_re_finds_snake_case_names():
    found = IDENT_RE.findall("call lookup_warehouse_inventory then check_stock now")
    assert found == ["lookup_warehouse_inventory", "check_stock"]


def test_ident_re_ignores_plain_words():
    assert IDENT_RE.findall("just plain english words here") == []


def test_invented_identifiers_flags_only_names_absent_from_the_digest(tmp_path, monkeypatch):
    sec = tmp_path / "section01-mock-exam-1"
    sec.mkdir()
    quiz = sec / "quiz.csv"
    write_rows(quiz, [
        list(HEADER),
        row(question="use cache_control and fetch_shipment_eta"),
        row(question="use fetch_shipment_eta again"),
    ])
    monkeypatch.chdir(tmp_path)
    corpus = "公式の cache_control について"
    owner = invented_identifiers([quiz], corpus)
    # cache_control は digest にあるので創作ではない
    assert "cache_control" not in owner
    # fetch_shipment_eta は2問で共有されている
    assert owner["fetch_shipment_eta"] == {
        "section01-mock-exam-1/Q1", "section01-mock-exam-1/Q2",
    }


def test_invented_identifiers_detects_collisions_inside_one_exam(tmp_path, monkeypatch):
    """同一本の中での共有も検出する（受講者が2問を結び付けて見てしまう）。"""
    sec = tmp_path / "section01-mock-exam-1"
    sec.mkdir()
    quiz = sec / "quiz.csv"
    write_rows(quiz, [list(HEADER), row(question="a inventory_check_stock"),
                      row(question="b inventory_check_stock")])
    monkeypatch.chdir(tmp_path)
    owner = invented_identifiers([quiz], "無関係な digest")
    assert len(owner["inventory_check_stock"]) == 2


def test_digest_corpus_excludes_the_guardrails_document(tmp_path, monkeypatch):
    """ガードレール文書は過去事故の創作名を引用するため除外する。

    含めるとその創作名が「公式名」と誤判定されてブロックリストから消える。
    """
    research = tmp_path / "research"
    research.mkdir()
    (research / "B1-api.md").write_text("公式の cache_control", encoding="utf-8")
    (research / "AUTHORING-GUARDRAILS.md").write_text(
        "実績: 創作ツール名 inventory_check_stock を2問で使っていた", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    corpus = digest_corpus()
    assert "cache_control" in corpus
    assert "inventory_check_stock" not in corpus


# --- シナリオ検査の方針 -----------------------------------------------------

def test_scenario_policy_uses_ratio_when_there_is_no_scenario_bank():
    """`scenario` 列を問い方の型に転用している資格では均等配分を要件にしない。

    8-12 問という固定の帯を当てると、実測で6本すべてが FAIL になった。
    """
    pol = scenario_policy({"scenario_ratio_min": "50%"})
    assert pol["mode"] == "ratio"
    assert pol["ratio_min"] == pytest.approx(0.5)
    assert pol["non_scenario"] == {"knowledge"}


def test_scenario_policy_uses_the_bank_when_one_is_declared():
    pol = scenario_policy({"scenarios": [{"id": "S1"}], "scenario_ratio_min": "50%"})
    assert pol["mode"] == "bank"


def test_scenario_policy_tolerates_a_missing_ratio():
    pol = scenario_policy({})
    assert pol["mode"] == "ratio"
    assert pol["ratio_min"] is None


def test_scenario_policy_honours_custom_non_scenario_codes():
    pol = scenario_policy({"non_scenario_codes": ["knowledge", "definition"]})
    assert pol["non_scenario"] == {"knowledge", "definition"}


# --- 出典 URL の切り出し ----------------------------------------------------

def test_url_re_stops_before_japanese_even_without_a_space():
    """旧版は 】 だけを除外し 【 を含めていたため訳文を飲み込んでいた。"""
    got = URL_RE.findall("出典: https://example.com/page【設問の訳】ある開発者が")
    assert got == ["https://example.com/page"]


def test_url_re_keeps_normal_urls_intact():
    got = URL_RE.findall("出典: https://example.com/a/b?x=1 【設問の訳】ほか")
    assert got == ["https://example.com/a/b?x=1"]


# --- used_concepts の --all / --out -----------------------------------------

BANK_HEADER = "| section | q# | domain | task_statement | tested_concept | scenario | 冒頭 |"
BANK_SEP = "|---|---|---|---|---|---|---|"


def bank(tmp_path):
    p = tmp_path / "question-bank.md"
    p.write_text(
        BANK_HEADER + "\n" + BANK_SEP + "\n"
        "| section01 | Q1 | D1 | 1.1 | 概念A | design | head |\n"
        "| section01 | Q2 | D2 | 2.1 | 概念B | root-cause | head |\n",
        encoding="utf-8",
    )
    return p


def sections(tmp_path):
    p = tmp_path / "sections.md"
    p.write_text(
        "---\n"
        "cert: X\nvendor: v\nstudy_guide: u\nmode: mock-exam\n"
        "mock_exams: 1\nquestions_per_exam: 2\nmax_per_concept: 3\n"
        "exam:\n  minutes: 1\n  pass_score: 1\n  language: en\n"
        "domains:\n"
        "  - id: D1\n    name: N1\n    ratio: \"50%\"\n    per_exam: 1\n"
        "  - id: D2\n    name: N2\n    ratio: \"50%\"\n    per_exam: 1\n"
        "---\n",
        encoding="utf-8",
    )
    return p


def run_used(tmp_path, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "used_concepts.py"), *args,
         "--bank", str(bank(tmp_path)), "--sections", str(sections(tmp_path))],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=tmp_path,
    )


def test_all_mode_covers_every_domain(tmp_path):
    """担当ドメインだけ渡すと他ドメインの重複が構造的に見えない。"""
    proc = run_used(tmp_path, "--all")
    assert proc.returncode == 0, proc.stderr[:300]
    assert "D1 の使用済み概念" in proc.stdout
    assert "D2 の使用済み概念" in proc.stdout


def test_single_domain_mode_still_works(tmp_path):
    proc = run_used(tmp_path, "D1")
    assert proc.returncode == 0, proc.stderr[:300]
    assert "D1 の使用済み概念" in proc.stdout
    assert "D2 の使用済み概念" not in proc.stdout


def test_out_writes_utf8_not_the_console_codepage(tmp_path):
    """シェルのリダイレクトに頼ると Windows で cp932 になる（実績あり）。"""
    out = tmp_path / ".work" / "used-all.md"
    proc = run_used(tmp_path, "--all", "--out", str(out))
    assert proc.returncode == 0, proc.stderr[:300]
    raw = out.read_bytes()
    assert raw.decode("utf-8")           # cp932 なら例外になる
    assert "概念A" in raw.decode("utf-8")


def test_requires_a_domain_or_all(tmp_path):
    proc = run_used(tmp_path)
    assert proc.returncode != 0
