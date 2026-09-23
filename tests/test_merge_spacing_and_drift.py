"""merge_parts の2つの防御と、finalize_section への配線の検証。

1. 日本語と英数字の間の半角スペースの割れ
   実績: 分割作問の回ごとに癖が割れ、ある講座の1本で Q1-25 はスペース無し、
   Q26-50 はあり、という状態のまま全検査を通った。1パートの中で割れることも
   あるので、パート単位ではなく行単位で判定する。

2. 結合し直すと消える手直し
   実績: quiz.csv を後から手直ししたが quiz.raw.csv が古いまま残り、
   原本から作り直すと修正が消える罠があった。結合も quiz.csv を上書きするので
   同じ罠になる。
"""
import os
import time

import pytest

from scripts.merge_parts import (
    format_spacing_warning, merge, normalize_spacing, spacing_counts,
    spacing_report, unmerged_edits,
)
from scripts.shuffle_options import shuffle_file
from scripts.validate_quiz_csv import HEADER, read_rows, write_rows

TAB = chr(9)
NL = chr(10)

SPACED = "Widget の設定は API で行い、v2 の Endpoint に送ります。"
GLUED = "Widgetの設定はAPIで行い、v2のEndpointに送ります。"


def row(text, n=0, domain="Domain 1"):
    r = [f"Question {n}?", "multiple-choice"]
    for i in range(4):
        mark = "正解" if i == 0 else "不正解"
        r += [f"Option {i + 1}", f"{mark}です。{text}"]
    r += ["", "", "", ""]
    r += ["1", f"{text} 出典: https://example.com/docs/a 【設問の訳】訳", domain]
    return r


def _profile(quota):
    return {
        "mode": "mock-exam",
        "mock_exams": 1,
        "questions_per_exam": sum(quota.values()),
        "domains": [
            {"id": d, "name": f"Domain {d[1:]}", "ratio": "50%", "per_exam": n}
            for d, n in quota.items()
        ],
    }


def _part(section, did, rows_):
    parts = section / "_parts"
    parts.mkdir(parents=True, exist_ok=True)
    write_rows(parts / f"{did}.csv", [list(HEADER)] + rows_)
    meta = [
        TAB.join([str(i), did, "1.1", f"{did}概念{i}", "S1", r[0]])
        for i, r in enumerate(rows_, 1)
    ]
    (parts / f"{did}-meta.tsv").write_text(NL.join(meta) + NL, encoding="utf-8", newline=NL)


# --- 行ごとの判定 -----------------------------------------------------------

def test_spacing_counts_tell_the_two_habits_apart():
    s, g = spacing_counts(row(SPACED))
    assert s > 0 and g == 0
    s, g = spacing_counts(row(GLUED))
    assert g > 0 and s == 0


def test_spacing_counts_ignore_urls_backticks_and_the_domain_column():
    r = row("説明")
    r[3] = "正解です。`config値を設定` と https://example.com/aの説明"
    r[16] = "ドメインA名"
    before = spacing_counts(r)
    r[16] = "ドメイン A 名"
    assert spacing_counts(r) == before
    # バッククォート内・URL の端は数えない
    assert spacing_counts(["x", "multiple-choice", "", "`値A`", *[""] * 13]) == (0, 0)


def test_report_flags_a_split_inside_a_single_part():
    """drill は1パートなので、パート内で割れても検出できなければならない。"""
    entries = [("D1", i, row(GLUED if i <= 5 else SPACED, i)) for i in range(1, 11)]
    entries += [("D1", 11, row(SPACED, 11))]
    rep = spacing_report(entries)
    assert rep["split"] is True
    assert rep["majority"] == "spaced"
    assert rep["minority"] == {"D1": [1, 2, 3, 4, 5]}
    text = "\n".join(format_spacing_warning(rep))
    assert "D1" in text and "Q1-Q5" in text and "--normalize" in text


def test_report_is_quiet_when_consistent():
    entries = [("D1", i, row(SPACED, i)) for i in range(1, 11)]
    assert spacing_report(entries)["split"] is False


def test_report_ignores_one_or_two_stray_rows():
    entries = [("D1", i, row(SPACED, i)) for i in range(1, 11)]
    entries.append(("D2", 11, row(GLUED, 11)))
    assert spacing_report(entries)["split"] is False


# --- 正規化 -----------------------------------------------------------------

def test_normalize_to_spaced():
    got, n = normalize_spacing(GLUED, "spaced")
    assert got == SPACED and n > 0


def test_normalize_to_glued():
    got, n = normalize_spacing(SPACED, "glued")
    assert got == GLUED and n > 0


def test_normalize_keeps_the_space_after_a_url():
    """URL 直後の半角スペースは check_style の規則で必須。消してはいけない。"""
    text = "出典: https://example.com/docs/a の説明"
    got, _ = normalize_spacing(text, "glued")
    assert "https://example.com/docs/a の" in got


def test_normalize_leaves_backtick_spans_alone():
    text = "`値A を設定` する"
    assert normalize_spacing(text, "spaced")[0] == text
    assert normalize_spacing("`値 A`", "glued")[0] == "`値 A`"


# --- merge への配線 ---------------------------------------------------------

def test_merge_warns_about_a_split_between_parts(tmp_path, capsys):
    section = tmp_path / "section01-mock-exam-1"
    _part(section, "D1", [row(GLUED, i) for i in range(1, 5)])
    _part(section, "D2", [row(SPACED, i, "Domain 2") for i in range(5, 11)])
    result = merge(section, _profile({"D1": 4, "D2": 6}), keep_parts=True)
    out = capsys.readouterr().out
    assert "WARN" in out and "半角スペース" in out
    assert "D1: スペース無しの行 Q1-Q4" in out
    assert result["spacing"]["split"] is True


def test_merge_normalize_rewrites_quiz_and_parts(tmp_path):
    section = tmp_path / "section01-mock-exam-1"
    _part(section, "D1", [row(GLUED, i) for i in range(1, 5)])
    _part(section, "D2", [row(SPACED, i, "Domain 2") for i in range(5, 11)])
    result = merge(section, _profile({"D1": 4, "D2": 6}), keep_parts=True, normalize=True)
    assert result["normalized"] > 0
    quiz = read_rows(section / "quiz.csv")
    assert all(spacing_counts(r)[1] == 0 for r in quiz[1:])
    # パートにも書き戻す（書き戻さないと次の結合で割れが戻る）
    part = read_rows(section / "_parts" / "D1.csv")
    assert SPACED in part[1][3]
    # Domain 列と URL 直後の空白は無傷
    assert quiz[1][16] == "Domain 1"
    assert "https://example.com/docs/a 【" in quiz[1][15]


# --- 結合し直すと消える手直し -----------------------------------------------

def _finalized(tmp_path):
    """結合 → シャッフルまで済んだセクション。"""
    section = tmp_path / "section01-mock-exam-1"
    _part(section, "D1", [row(SPACED, i) for i in range(1, 5)])
    profile = _profile({"D1": 4})
    merge(section, profile, keep_parts=True)
    shuffle_file(section / "quiz.csv", seed=3)
    return section, profile


def _touch_later(path):
    t = time.time() + 5
    os.utime(path, (t, t))


def test_remerge_is_allowed_when_nothing_was_hand_edited(tmp_path):
    section, profile = _finalized(tmp_path)
    merge(section, profile, keep_parts=True)


def test_remerge_is_allowed_after_editing_the_parts(tmp_path):
    """_parts を直して結合し直すのは正規の経路。止めてはいけない。"""
    section, profile = _finalized(tmp_path)
    part = section / "_parts" / "D1.csv"
    rows_ = read_rows(part)
    rows_[1][0] = "FIXED IN PARTS?"
    write_rows(part, rows_)
    _touch_later(part)
    merge(section, profile, keep_parts=True)
    assert read_rows(section / "quiz.csv")[1][0] == "FIXED IN PARTS?"


def test_remerge_stops_when_quiz_csv_was_hand_edited(tmp_path, capsys):
    section, profile = _finalized(tmp_path)
    quiz = section / "quiz.csv"
    rows_ = read_rows(quiz)
    rows_[2][0] = "FIXED IN QUIZ?"
    write_rows(quiz, rows_)
    with pytest.raises(SystemExit):
        merge(section, profile, keep_parts=True)
    assert read_rows(quiz)[2][0] == "FIXED IN QUIZ?"     # 上書きしていない
    out = capsys.readouterr().out
    assert "Row 3" in out and "--force" in out


def test_remerge_stops_when_only_correct_answers_were_fixed(tmp_path):
    """正答の取り違えの修正（Correct Answers だけの変更）も手直しとして守る。"""
    section, profile = _finalized(tmp_path)
    quiz = section / "quiz.csv"
    rows_ = read_rows(quiz)
    cur = rows_[1][14]
    rows_[1][14] = "2" if cur != "2" else "3"
    write_rows(quiz, rows_)
    assert unmerged_edits(section, [list(HEADER)] + read_rows(section / "_parts" / "D1.csv")[1:],
                          [section / "_parts" / "D1.csv"])


def test_remerge_stops_when_the_raw_was_hand_edited(tmp_path):
    section, profile = _finalized(tmp_path)
    raw = section / "quiz.raw.csv"
    rows_ = read_rows(raw)
    rows_[1][0] = "FIXED IN RAW?"
    write_rows(raw, rows_)
    _touch_later(raw)
    with pytest.raises(SystemExit):
        merge(section, profile, keep_parts=True)


def test_force_overwrites_hand_edits(tmp_path):
    section, profile = _finalized(tmp_path)
    quiz = section / "quiz.csv"
    rows_ = read_rows(quiz)
    rows_[2][0] = "FIXED IN QUIZ?"
    write_rows(quiz, rows_)
    merge(section, profile, keep_parts=True, force=True)
    assert read_rows(quiz)[2][0] == "Question 2?"


def test_remerge_before_shuffle_allows_part_fixes(tmp_path):
    """シャッフル前（原本なし）の「パートを直して結合し直す」反復は止めない。"""
    section = tmp_path / "section01-mock-exam-1"
    _part(section, "D1", [row(SPACED, i) for i in range(1, 5)])
    profile = _profile({"D1": 4})
    merge(section, profile, keep_parts=True)
    part = section / "_parts" / "D1.csv"
    rows_ = read_rows(part)
    rows_[1][0] = "FIXED IN PARTS?"
    write_rows(part, rows_)
    _touch_later(part)
    merge(section, profile, keep_parts=True)
    assert read_rows(section / "quiz.csv")[1][0] == "FIXED IN PARTS?"


def test_remerge_before_shuffle_stops_on_newer_quiz_edits(tmp_path):
    section = tmp_path / "section01-mock-exam-1"
    _part(section, "D1", [row(SPACED, i) for i in range(1, 5)])
    profile = _profile({"D1": 4})
    merge(section, profile, keep_parts=True)
    quiz = section / "quiz.csv"
    rows_ = read_rows(quiz)
    rows_[1][0] = "FIXED IN QUIZ?"
    write_rows(quiz, rows_)
    _touch_later(quiz)
    with pytest.raises(SystemExit):
        merge(section, profile, keep_parts=True)


# --- finalize_section への配線 ----------------------------------------------

def test_finalize_passes_adopt_to_the_shuffle_and_force_to_the_merge():
    """結合直後のシャッフルは quiz.csv を正とする（手直しの保護は結合前の検査が担う）。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "plugins" / "udemy-exam-prep"
           / "scripts" / "finalize_section.py").read_text(encoding="utf-8")
    assert '"--adopt"' in src
    assert "--force" in src
    assert "--normalize" in src


# --- --normalize と上書き検査の順序 -------------------------------------------

def _split_section(tmp_path):
    section = tmp_path / "section01-mock-exam-1"
    _part(section, "D1", [row(GLUED, i) for i in range(1, 5)])
    _part(section, "D2", [row(SPACED, i, "Domain 2") for i in range(5, 11)])
    return section, _profile({"D1": 4, "D2": 6})


def test_merge_then_normalize_does_not_trip_the_guard(tmp_path):
    """WARN を見て --normalize で結合し直す自然な流れを止めてはいけない。"""
    section, profile = _split_section(tmp_path)
    merge(section, profile, keep_parts=True)
    _touch_later(section / "quiz.csv")
    result = merge(section, profile, keep_parts=True, normalize=True)
    assert result["normalized"] > 0


def test_normalize_does_not_touch_parts_when_the_guard_stops(tmp_path):
    """止まるときはパートも書き換えない（書き換えると mtime で手直しを見逃す）。"""
    section, profile = _split_section(tmp_path)
    merge(section, profile, keep_parts=True)
    quiz = section / "quiz.csv"
    rows_ = read_rows(quiz)
    rows_[1][0] = "FIXED IN QUIZ?"
    write_rows(quiz, rows_)
    _touch_later(quiz)
    parts = sorted((section / "_parts").glob("*.csv"))
    before = [p.read_bytes() for p in parts]
    with pytest.raises(SystemExit):
        merge(section, profile, keep_parts=True, normalize=True)
    assert [p.read_bytes() for p in parts] == before
    assert read_rows(quiz)[1][0] == "FIXED IN QUIZ?"
