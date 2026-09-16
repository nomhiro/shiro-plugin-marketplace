"""コンソール出力を、環境のエンコーディングで落ちない・壊れないようにする。

日本語 Windows の既定コンソールは cp932 で、`—`（U+2014）のような文字を
印字できず `UnicodeEncodeError` で落ちる。検証スクリプトは**違反を報告する
瞬間**に大量の文字を印字するので、そこで落ちると診断が一切得られない。

さらに、**パイプやリダイレクトに繋がれたときは cp932 では済まない。**
`python validate_quiz_csv.py ... | grep` や `subprocess.run(..., encoding="utf-8")`
の受け側は UTF-8 を期待するので、cp932 のバイト列を渡すと日本語の診断が
文字化けして読めなくなる（実績: 講座の検証出力がすべて文字化けし、
`used_concepts.py` を subprocess で呼ぶテスト2本が失敗していた）。

そのため **端末に出すときは環境のエンコーディングのまま（errors="replace" で
落ちないようにするだけ）、端末でないときは UTF-8 に固定する。**
端末側だけ据え置くのは、レガシーコンソールで UTF-8 を流すと画面が
文字化けするのを避けるため。

各 CLI の main() 冒頭で safe_stdout() を呼ぶ。
"""
from __future__ import annotations

import sys


def _is_tty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def safe_stdout() -> None:
    """印字で落ちないようにし、非 tty では UTF-8 に固定する。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if _is_tty(stream):
                # 端末: 環境のエンコーディングを尊重し、印字できない文字だけ置換する
                stream.reconfigure(errors="replace")
            else:
                # パイプ・リダイレクト・subprocess の捕捉: 受け側は UTF-8 を期待する
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # reconfigure が無い環境・既に閉じられている場合は何もしない
            pass
