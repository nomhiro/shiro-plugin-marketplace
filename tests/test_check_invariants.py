"""check_invariants.py の検証。

精読レビューの文面修正で、正解・配分・選択肢数・出典・正誤印が動いていないことを
機械で保証するスクリプト。git の比較元モードと、比較元ファイルの直接指定モードの両方を見る。
"""
import copy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_invariants import compare, parse_selection, show
from scripts.validate_quiz_csv import HEADER, write_rows

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "udemy-exam-prep" / "scripts"


def row(correct="2", qtype="multiple-choice", nopt=4, url="https://docs.example.com/a"):
    r = ["問題文?", qtype]
    ok = {int(c) for c in correct.split(",")}
    for k in range(1, 7):
        if k <= nopt:
            verdict = "正解です。" if k in ok else "不正解です。"
            r += [f"選択肢{k}", f"{verdict}\n理由{k}"]
        else:
            r += ["", ""]
    r += [correct, f"【要約】説明。\n\n出典: {url}", "ドメイン1"]
    return r


def table(*rs):
    return [list(HEADER)] + [list(r) for r in rs]


BASE = table(row(), row("1,3", "multi-select", 5))


def test_text_only_edits_pass():
    new = copy.deepcopy(BASE)
    new[1][0] = "書き直した問題文?"
    new[1][3] = "不正解です。\n自然な日本語に直した理由"
    assert compare(BASE, new) == []


@pytest.mark.parametrize("col,val,needle", [
    (1, "multi-select", "Question Type"),
    (14, "3", "Correct Answers"),
    (16, "ドメイン2", "Domain"),
])
def test_fixed_columns_must_not_change(col, val, needle):
    new = copy.deepcopy(BASE)
    new[1][col] = val
    errs = compare(BASE, new, marks=None)
    assert any(needle in e for e in errs), errs


def test_removing_an_option_is_caught():
    new = copy.deepcopy(BASE)
    new[2][10] = ""
    new[2][11] = ""
    assert any("選択肢" in e for e in compare(BASE, new, marks=None))


def test_replacing_a_source_url_is_caught():
    new = copy.deepcopy(BASE)
    new[1][15] = new[1][15].replace("/a", "/other")
    errs = compare(BASE, new, marks=None)
    assert any("出典 URL" in e for e in errs), errs


def test_url_followed_by_japanese_is_not_swallowed():
    """URL の直後に訳文を詰め書きしても、日本語部分の修正は URL の変更に見えない。"""
    old = copy.deepcopy(BASE)
    old[1][15] = "出典: https://docs.example.com/a【訳】古い訳"
    new = copy.deepcopy(old)
    new[1][15] = "出典: https://docs.example.com/a【訳】新しい訳"
    assert compare(old, new, marks=None) == []


def test_verdict_mark_must_match_correct_answers():
    new = copy.deepcopy(BASE)
    new[1][3] = "不正解です。\n..."   # 選択肢1は誤答: OK
    new[1][5] = "不正解です。\n..."   # 選択肢2は正解なのに不正解印
    errs = compare(BASE, new)
    assert any("Explanation 2" in e for e in errs), errs


def test_verdict_marks_are_configurable():
    old = table(["Q", "multiple-choice", "a", "Correct. x", "b", "Incorrect. y",
                 "", "", "", "", "", "", "", "", "1", "o https://x.test/a", "D"])
    assert compare(old, copy.deepcopy(old), marks=("Correct.", "Incorrect.")) == []
    # 明示した印は完全な先頭一致（日本語の印を指定すれば落ちる）
    assert compare(old, copy.deepcopy(old), marks=("正解です。", "不正解です。")) != []


# --- 既定の正誤印は check_style.py と同じ緩い判定 ------------------------------
#
# 旧版はここだけ「正解です。」「不正解です。」の完全一致を既定にしていて、
# check_style.py が通した解説（「不正解。」など）をこちらが落とす食い違いがあった。

def test_default_marks_match_check_style_loosely():
    old = table(["Q", "multiple-choice", "a", "正解。x", "b", "不正解。y",
                 "c", "Correct. z", "", "", "", "", "", "", "1,3", "o https://x.test/a", "D"])
    assert compare(old, copy.deepcopy(old)) == []


def test_default_marks_still_catch_a_mismatch():
    old = table(["Q", "multiple-choice", "a", "正解。x", "b", "不正解。y",
                 "", "", "", "", "", "", "", "", "1", "o https://x.test/a", "D"])
    new = copy.deepcopy(old)
    new[1][14] = "2"
    assert any("Explanation" in e for e in compare(old, new))


def test_default_marks_catch_a_dropped_mark():
    new = copy.deepcopy(BASE)
    new[1][3] = "印を落とした解説"
    assert any("正誤印がない" in e for e in compare(BASE, new))


def test_default_marks_are_skipped_when_no_row_has_marks():
    """印を書かない運用の講座は検査しない（check_style.py は WARN にとどめる）。"""
    old = table(["Q", "multiple-choice", "a", "OK: x", "b", "NG: y",
                 "", "", "", "", "", "", "", "", "1", "o https://x.test/a", "D"])
    assert compare(old, copy.deepcopy(old)) == []


def test_row_count_change_is_caught():
    new = copy.deepcopy(BASE)[:-1]
    assert any("行数" in e for e in compare(BASE, new, marks=None))


def test_show_prints_every_nonempty_column():
    out = show(BASE, [2])
    assert "===== Q2 =====" in out
    assert "[Answer Option 5]" in out and "[Answer Option 6]" not in out
    assert "[Overall Explanation]" in out


def test_parse_selection():
    assert parse_selection("all", 3) == [1, 2, 3]
    assert parse_selection("1-2,5", 10) == [1, 2, 5]
    assert parse_selection("9", 3) == []


# --- CLI ---------------------------------------------------------------------

def run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "check_invariants.py"), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd,
    )


def test_cli_base_file_mode(tmp_path):
    base = tmp_path / "quiz.orig.csv"
    quiz = tmp_path / "quiz.csv"
    write_rows(base, BASE)
    new = copy.deepcopy(BASE)
    new[1][14] = "3"
    write_rows(quiz, new)
    proc = run(quiz, "--base", base, "--no-verdict")
    assert proc.returncode == 1, proc.stdout
    assert "Correct Answers" in proc.stdout

    write_rows(quiz, BASE)
    proc = run(quiz, "--base", base)
    assert proc.returncode == 0, proc.stdout


def test_cli_base_requires_a_single_csv(tmp_path):
    base = tmp_path / "b.csv"
    write_rows(base, BASE)
    assert run(base, base, "--base", base).returncode == 2


@pytest.mark.skipif(shutil.which("git") is None, reason="git が無い")
def test_cli_git_mode_compares_with_head_from_any_cwd(tmp_path):
    repo = tmp_path / "course"
    sec = repo / "section01-drill-1"
    sec.mkdir(parents=True)
    quiz = sec / "quiz.csv"
    write_rows(quiz, BASE)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(git[:3] + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "."], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "base"], check=True)

    new = copy.deepcopy(BASE)
    new[1][0] = "文面だけ直した?"
    write_rows(quiz, new)
    other = tmp_path / "elsewhere"
    other.mkdir()
    proc = run(quiz, cwd=other)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    new[2][15] = new[2][15].replace("/a", "/b")
    write_rows(quiz, new)
    proc = run(quiz, cwd=other)
    assert proc.returncode == 1 and "出典 URL" in proc.stdout


def test_cli_outside_git_says_to_use_base(tmp_path):
    quiz = tmp_path / "quiz.csv"
    write_rows(quiz, BASE)
    proc = run(quiz, "--ref", "HEAD")
    # tmp_path が偶然 git 管理下でも、未コミットのファイルなので取得できない
    assert proc.returncode == 1
    assert "--base" in proc.stdout


def _sections(tmp_path, style_yaml):
    p = tmp_path / "sections.md"
    p.write_text(f"---\nstyle:\n{style_yaml}\n---\n", encoding="utf-8")
    return p


def test_cli_reads_verdict_marks_from_front_matter(tmp_path):
    old = table(["Q", "multiple-choice", "a", "OK: x", "b", "NG: y",
                 "", "", "", "", "", "", "", "", "1", "o https://x.test/a", "D"])
    base, quiz = tmp_path / "b.csv", tmp_path / "quiz.csv"
    write_rows(base, old)
    write_rows(quiz, old)
    marks = _sections(tmp_path, "  explanation_markers: {correct: 'OK:', incorrect: 'NG:'}")
    assert run(quiz, "--base", base, "--sections", marks).returncode == 0
    off = _sections(tmp_path, "  explanation_markers: false")
    assert run(quiz, "--base", base, "--sections", off).returncode == 0
    # front matter が無ければ既定（緩い判定）。印が1件も無いファイルは検査しない
    assert run(quiz, "--base", base, "--sections", tmp_path / "none.md").returncode == 0
    # CLI 指定が最優先（front matter の印より強い）
    assert run(quiz, "--base", base, "--sections", marks,
               "--correct-mark", "X:", "--incorrect-mark", "Y:").returncode == 1
