"""コンソール出力を、環境のエンコーディングで落ちないようにする。

日本語 Windows の既定コンソールは cp932 で、`—`（U+2014）のような文字を
印字できず `UnicodeEncodeError` で落ちる。検証スクリプトは**違反を報告する
瞬間**に大量の文字を印字するので、そこで落ちると診断が一切得られない。

各 CLI の main() 冒頭で safe_stdout() を呼ぶ。
"""
from __future__ import annotations

import sys


def safe_stdout() -> None:
    """印字できない文字を置換文字に落として、例外を出さないようにする。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            # reconfigure が無い環境・既に閉じられている場合は何もしない
            pass
