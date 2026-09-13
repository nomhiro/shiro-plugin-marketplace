"""quiz.csv の出典 URL のロケールセグメントを機械的に正規化する。

出典は「英語版のディープリンク」に揃えたい。しかしモデルは生成のたびに
ロケールを付け忘れたり `/ja-jp/` を混ぜたりする（実績あり）。記憶に頼らず
ここで機械的に保証する。冪等なので何度実行してもよい。

ホストごとの規則しか持たないので、未知のホストの URL は一切触らない。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import safe_stdout
from scripts.validate_quiz_csv import read_rows, write_rows

# host -> 強制するロケールセグメント
#
# 値を入れるのは「ロケールがホスト直後の第1パスセグメントにあるサイト」だけ。
#   OK:  https://docs.claude.com/en/docs/claude-code/...   <- 第1セグメントがロケール
#   NG:  https://code.claude.com/docs/en/agent-sdk/...     <- ロケールは第2セグメント
# 後者に規則を入れると code.claude.com/en/docs/en/... と URL を壊すため、
# ロケールが第1セグメントに来ないサイトは必ず None（= 一切触らない）にする。
LOCALE_RULES: dict[str, str | None] = {
    "learn.microsoft.com": "en-us",
    "docs.microsoft.com": "en-us",
    "docs.claude.com": "en",
    "docs.anthropic.com": "en",
    "docs.github.com": "en",
    # ロケールが /docs/ の下にあるので触らない
    "code.claude.com": None,
    "platform.claude.com": None,
    # ロケールセグメントを持たないサイト
    "developers.cloudflare.com": None,
    "modelcontextprotocol.io": None,
    "www.anthropic.com": None,
    "www.ipa.go.jp": None,
}

# 既存ロケール（xx / xx-xx）をロケールとして認識する。docs パス等と衝突しないよう厳密に
_LOCALE_SEG = r"(?:[a-z]{2}-[a-z]{2}|[a-z]{2})"


def _pattern(host: str) -> re.Pattern[str]:
    return re.compile(
        rf"(https?://{re.escape(host)})/(?:{_LOCALE_SEG}/)?", re.IGNORECASE
    )


def normalize_text(text: str) -> tuple[str, int]:
    """テキスト中の既知ホストの URL を正規化し、(結果, 実際に変更した件数) を返す。

    既に正しいロケールになっている URL は変更件数に数えない（冪等性の保証）。
    """
    changed = 0
    for host, locale in LOCALE_RULES.items():
        if locale is None or host not in text:
            continue

        def sub(m: re.Match[str]) -> str:
            nonlocal changed
            want = f"{m.group(1)}/{locale}/"
            if m.group(0) != want:
                changed += 1
            return want

        text = _pattern(host).sub(sub, text)
    return text, changed


def normalize_rows(rows: list[list[str]]) -> tuple[list[list[str]], int]:
    total = 0
    out: list[list[str]] = []
    for row in rows:
        new_row = []
        for cell in row:
            fixed, n = normalize_text(cell)
            total += n
            new_row.append(fixed)
        out.append(new_row)
    return out, total


def normalize_file(path) -> int:
    rows = read_rows(path)
    fixed, n = normalize_rows(rows)
    if n:
        write_rows(path, fixed)
    return n


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(
        description="quiz.csv の出典 URL のロケールを正規化する（冪等）"
    )
    ap.add_argument("csv_paths", nargs="+")
    a = ap.parse_args(argv[1:])

    for target in a.csv_paths:
        n = normalize_file(target)
        print(f"{target}: {n} URL(s) normalized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
