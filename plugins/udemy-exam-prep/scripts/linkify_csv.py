"""quiz.csv の素の URL を <a href> に変えた、Udemy 一括アップロード用の CSV を作る。

Udemy の一括アップロードは、解説中の素の URL をテキストのまま保存するので受講者は
クリックできない。`<a href="URL">URL</a>` と書けばリンクとして保存される
（実測: target="_blank" rel="noopener noreferrer" は Udemy 側で付く。Markdown の
`[text](url)` は変換されずに文字のまま残る）。

quiz.csv（Source of Truth）は素の URL のまま残し、アップロードの直前にこのスクリプトで
別ファイルを作る。見た目の文字（innerText）は変わらないので、編集画面ヘルパーの
署名照合は quiz.csv のデータのまま使える。

使い方:
    python "${CLAUDE_PLUGIN_ROOT}/scripts/linkify_csv.py" section01-*/quiz.csv --out-dir .upload
    # → .upload/section01-.../quiz.csv を書き出す（入力と同じフォルダ名の下に置く）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import safe_stdout  # noqa: E402
from scripts.validate_quiz_csv import HEADER, read_rows, write_rows  # noqa: E402

# URL に使える半角文字だけを取る（直後に続く日本語やバッククォートを巻き込まない）。
# 末尾の句読点・閉じ括弧は URL に含めない
URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&()*+,;=%]+")
TRAIL_RE = re.compile(r"[.,;:!?)\]}]+$")
# リンクにするのは出典・参考の行だけ。本文中のスコープ値（https://…/.default）や
# audience 値のような「URL の形をした値」はリンクにしない
SOURCE_LINE_RE = re.compile(r"^\s*(出典|参考)\s*[:：]")
# 既にある <a ...>...</a> の中は触らない
ANCHOR_RE = re.compile(r"<a\s[^>]*>.*?</a>", re.S | re.I)
DOMAIN_COL = HEADER.index("Domain")


def linkify_text(text: str) -> str:
    """出典・参考の行にある素の URL だけを <a href> にする。既存のアンカーの中身は変えない。"""
    return "\n".join(_linkify_line(l) if SOURCE_LINE_RE.match(l) else l for l in text.split("\n"))


def _linkify_line(text: str) -> str:
    out, pos = [], 0
    for m in ANCHOR_RE.finditer(text):
        out.append(_linkify_plain(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_linkify_plain(text[pos:]))
    return "".join(out)


def _linkify_plain(s: str) -> str:
    def repl(m: re.Match) -> str:
        raw = m.group(0)
        url = TRAIL_RE.sub("", raw)
        tail = raw[len(url):]
        if len(url) <= len("https://"):
            return raw
        return f'<a href="{url}">{url}</a>{tail}'
    return URL_RE.sub(repl, s)


def linkify_rows(rows: list[list[str]]) -> tuple[list[list[str]], int]:
    out, n = [rows[0]], 0
    for row in rows[1:]:
        new = []
        for i, cell in enumerate(row):
            if i == DOMAIN_COL:
                new.append(cell)
                continue
            linked = linkify_text(cell)
            n += linked.count("<a href=") - cell.count("<a href=")
            new.append(linked)
        out.append(new)
    return out, n


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="素の URL を <a href> にした一括アップロード用 CSV を作る")
    ap.add_argument("csv_paths", nargs="+")
    ap.add_argument("--out-dir", required=True, help="書き出し先（入力の親フォルダ名の下に quiz.csv を置く）")
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)
    for p in map(Path, args.csv_paths):
        rows = read_rows(p)
        linked, n = linkify_rows(rows)
        dest = out_dir / p.parent.name / p.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_rows(dest, linked)
        print(f"OK   {p} -> {dest}: {n} 個の URL をリンクにした")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
