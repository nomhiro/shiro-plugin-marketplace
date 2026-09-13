"""スクリプトを `python <path>/x.py` の形で直接実行できることを担保する。

スキルはすべて `python "${CLAUDE_PLUGIN_ROOT}/scripts/x.py"` の形で呼ぶので、
パッケージ import 経由では通るのに直接実行では ModuleNotFoundError になる、
という壊れ方を防ぐ必要がある（実際に起きた）。
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "udemy-exam-prep" / "scripts"

sys.path.insert(0, str(REPO / "plugins" / "udemy-exam-prep"))
from scripts.validate_quiz_csv import HEADER, write_rows  # noqa: E402

SECTIONS = textwrap.dedent("""\
    ---
    cert: SMOKE
    cert_name: Smoke Cert
    vendor: generic
    study_guide: https://example.com
    mode: mock-exam
    exam:
      minutes: 90
      pass_score: 700
      language: en
    mock_exams: 1
    questions_per_exam: 4
    question_types:
      multiple-choice: "75%"
      multi-select: "25%"
    primary_sources:
      - priority: 1
        tool: WebFetch
        scope: https://example.com
    domains:
      - id: D1
        name: Alpha Domain
        ratio: "50%"
        per_exam: 2
      - id: D2
        name: Beta Domain
        ratio: "50%"
        per_exam: 2
    ---

    # 本文
    """)

BANK = textwrap.dedent("""\
    # Question Bank

    | section | q# | domain | task_statement | tested_concept | scenario | head |
    |---|---|---|---|---|---|---|
    | section01 | Q1 | D1 | 1.1 | concept-a | S1 | Q1 ... |
    | section01 | Q2 | D1 | 1.2 | concept-b | S2 | Q2 ... |
    | section01 | Q3 | D2 | 2.1 | concept-c | S3 | Q3 ... |
    | section01 | Q4 | D2 | 2.2 | concept-d | S4 | Q4 ... |
    """)


def run(script, *args):
    """スクリプトを直接実行する（プラグイン利用時と同じ呼び方）。"""
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *[str(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert "ModuleNotFoundError" not in (proc.stderr or ""), (
        f"{script} を直接実行できない:\n{proc.stderr}"
    )
    return proc


@pytest.fixture
def project(tmp_path):
    (tmp_path / "sections.md").write_text(SECTIONS, encoding="utf-8")
    (tmp_path / "question-bank.md").write_text(BANK, encoding="utf-8")
    folder = tmp_path / "section01-mock-exam-1"
    folder.mkdir()

    rows = [list(HEADER)]
    for i in range(4):
        domain = "Alpha Domain" if i < 2 else "Beta Domain"
        row = [f"Q{i + 1}: what is the most likely root cause?", "multiple-choice"]
        for k in range(6):
            row += ([f"Option {k + 1}", f"Why {k + 1}"] if k < 4 else ["", ""])
        row += ["1", f"Source: https://docs.claude.com/docs/topic-{i}", domain]
        rows.append(row)
    write_rows(folder / "quiz.csv", rows)
    return tmp_path


def test_profile_cli_accepts_a_valid_profile(project):
    proc = run("profile.py", project / "sections.md")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK: SMOKE" in proc.stdout


def test_profile_cli_rejects_a_broken_profile(tmp_path):
    (tmp_path / "sections.md").write_text("no front matter\n", encoding="utf-8")
    proc = run("profile.py", tmp_path / "sections.md")
    assert proc.returncode == 1
    assert "FAIL" in proc.stdout


def test_init_course_cli_creates_a_project(tmp_path):
    proc = run(
        "init_course.py", "--dest", tmp_path, "--cert", "SMOKE",
        "--cert-name", "Smoke Cert", "--vendor", "generic",
        "--study-guide", "https://example.com",
        "--exam-minutes", "90", "--pass-score", "700",
        "--mock-exams", "2", "--questions-per-exam", "10",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "6 created" in proc.stdout
    assert (tmp_path / "CLAUDE.md").is_file()
    assert (tmp_path / ".gitignore").is_file()


def test_validate_quiz_csv_cli(project):
    proc = run("validate_quiz_csv.py", project / "section01-mock-exam-1" / "quiz.csv")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "4 questions, all valid" in proc.stdout


def test_normalize_urls_cli(project):
    target = project / "section01-mock-exam-1" / "quiz.csv"
    first = run("normalize_urls.py", target)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "4 URL(s) normalized" in first.stdout
    second = run("normalize_urls.py", target)
    assert "0 URL(s) normalized" in second.stdout  # 冪等


def test_shuffle_options_cli(project):
    target = project / "section01-mock-exam-1" / "quiz.csv"
    proc = run("shuffle_options.py", target)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "shuffled 4 questions" in proc.stdout
    assert (project / "section01-mock-exam-1" / "quiz.raw.csv").is_file()


def test_validate_exam_cli(project):
    proc = run(
        "validate_exam.py",
        "--sections", project / "sections.md",
        "--bank", project / "question-bank.md",
        project / "section01-mock-exam-1" / "quiz.csv",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "domain quota satisfied" in proc.stdout
    assert "no duplication violations" in proc.stdout


def test_the_whole_pipeline_runs_in_order(project):
    """スキルが実行する順序どおりに6本を通す。"""
    quiz = project / "section01-mock-exam-1" / "quiz.csv"
    steps = [
        ("profile.py", [project / "sections.md"]),
        ("validate_quiz_csv.py", [quiz]),
        ("normalize_urls.py", [quiz]),
        ("shuffle_options.py", [quiz]),
        ("validate_exam.py", ["--sections", project / "sections.md",
                              "--bank", project / "question-bank.md", quiz]),
        ("validate_quiz_csv.py", [quiz]),
    ]
    for script, args in steps:
        proc = run(script, *args)
        assert proc.returncode == 0, f"{script} failed:\n{proc.stdout}{proc.stderr}"


def run_with_encoding(script, *args, encoding="cp932"):
    """コンソールのエンコーディングを指定して直接実行する。"""
    import os
    env = dict(os.environ, PYTHONIOENCODING=encoding)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *[str(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )


def test_every_cli_starts_on_a_cp932_console():
    """日本語 Windows の既定コンソール（cp932）で起動時に落ちないこと。"""
    for script in ("profile.py", "init_course.py", "validate_quiz_csv.py",
                   "normalize_urls.py", "shuffle_options.py", "validate_exam.py"):
        proc = run_with_encoding(script)
        combined = proc.stdout + proc.stderr
        assert "UnicodeEncodeError" not in combined, f"{script} が cp932 で落ちる: {combined}"
        assert "Traceback" not in combined, f"{script} が traceback を出した: {combined}"


def test_validation_failures_print_on_a_cp932_console(tmp_path):
    """違反を報告する瞬間に落ちないこと。

    検証スクリプトは FAIL 時に大量の文字を印字する。ここで UnicodeEncodeError に
    なると診断が一切得られない（実際に em dash U+2014 で発生した）。
    """
    p = tmp_path / "quiz.csv"
    row = ["Q", "multi-select"]
    for k in range(6):
        row += (["opt", "exp"] if k < 4 else ["", ""])
    row += ["1", "overall", "Domain"]          # multi-select なのに正解1個 -> FAIL
    write_rows(p, [list(HEADER), row])

    proc = run_with_encoding("validate_quiz_csv.py", p)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "UnicodeEncodeError" not in combined
    assert "Traceback" not in combined
    assert "multi-select" in proc.stdout       # 診断が実際に出ている


def test_no_script_message_uses_characters_cp932_cannot_encode():
    """出力文字列に cp932 で表現できない文字を入れない（根本の予防）。"""
    offenders = {}
    for script in sorted(SCRIPTS.glob("*.py")):
        if script.name == "_console.py":       # 説明のため意図的に U+2014 を含む
            continue
        text = script.read_text(encoding="utf-8")
        bad = set()
        for ch in set(text):
            if ord(ch) > 127:
                try:
                    ch.encode("cp932")
                except UnicodeEncodeError:
                    bad.add("U+%04X" % ord(ch))
        if bad:
            offenders[script.name] = sorted(bad)
    assert not offenders, f"cp932 で印字できない文字がある: {offenders}"
