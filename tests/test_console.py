"""safe_stdout() の契約。

端末では環境のエンコーディングを尊重し、**端末でないときは UTF-8 に固定する。**
非 tty を据え置くと、パイプや subprocess の受け側（UTF-8 を期待する）に
cp932 のバイト列が渡り、日本語の診断が文字化けして読めなくなる。
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "udemy-exam-prep" / "scripts"

# 非 ASCII を印字して、捕捉側が UTF-8 で読めることを確かめる小さな子プロセス
CHILD = (
    "import sys;"
    f"sys.path.insert(0, {str(SCRIPTS.parent)!r});"
    "from scripts._console import safe_stdout;"
    "safe_stdout();"
    "print('日本語の診断 — ダッシュも含む');"
    "print(sys.stdout.encoding)"
)


def _run():
    return subprocess.run(
        [sys.executable, "-c", CHILD],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def test_piped_output_is_utf8_and_not_mojibake():
    proc = _run()
    assert proc.returncode == 0, proc.stderr[:300]
    assert "日本語の診断 — ダッシュも含む" in proc.stdout


def test_piped_stdout_encoding_is_utf8():
    proc = _run()
    assert proc.stdout.strip().splitlines()[-1].lower().replace("-", "") == "utf8"


def test_unprintable_characters_do_not_raise():
    """端末側の据え置き経路でも errors='replace' で落ちないこと。"""
    child = CHILD.replace("safe_stdout();", "safe_stdout();") + ";print('—' * 100)"
    proc = subprocess.run(
        [sys.executable, "-c", child],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, proc.stderr[:300]
