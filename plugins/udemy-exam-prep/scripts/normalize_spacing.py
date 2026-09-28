"""quiz.csv の「日本語と英数字の間の半角スペース」を多数派に揃える。

merge_parts.py の `--normalize` はパートを結合するときにしか効かない。精読レビュー
（review-section）の修正は quiz.csv にだけ入るので、レビュー後の表記の割れは
パートを経由せずに quiz.csv へ直接かける必要がある。

> 実績: 精読の修正エージェントを本ごとに動かしたところ、空白の有無が本ごとに割れた
> （修正エージェントに一律の整形を任せると判断が割れる）。オーケストレータが
> 全本へ一括でかけ、判定は merge_parts.py と同じ関数を使った。

URL・バッククォート内・Question Type / Correct Answers / Domain 列は触らない。
正解・選択肢数・出典は変わらないので、実行後に check_invariants.py で確かめられる。

使い方:
    python normalize_spacing.py <quiz.csv> [...]            # 多数派に揃えて上書き
    python normalize_spacing.py <quiz.csv> --majority spaced # 向きを固定する
    python normalize_spacing.py <quiz.csv> --check           # 数えるだけ（書き込まない）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import safe_stdout
from scripts.merge_parts import normalize_row_spacing, spacing_counts
from scripts.validate_quiz_csv import read_rows, write_rows


def normalize_file(path, majority: str | None = None, check: bool = False) -> tuple[str, int]:
    """(採用した向き, 揃えた箇所数) を返す。check=True なら書き込まない。"""
    rows = read_rows(path)
    header, body = rows[0], rows[1:]
    if majority is None:
        spaced = glued = 0
        for r in body:
            s_, g_ = spacing_counts(r)
            spaced += s_
            glued += g_
        majority = "spaced" if spaced >= glued else "glued"
    out, total = [], 0
    for r in body:
        nr, n = normalize_row_spacing(r, majority)
        out.append(nr)
        total += n
    if total and not check:
        write_rows(path, [header] + out)
    return majority, total


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="quiz.csv の日本語と英数字の間の半角スペースを揃える")
    ap.add_argument("csv_paths", nargs="+")
    ap.add_argument("--majority", choices=("spaced", "glued"), default=None,
                    help="揃える向き（既定: ファイルごとの多数派）")
    ap.add_argument("--check", action="store_true", help="数えるだけで書き込まない")
    a = ap.parse_args(argv[1:])
    for p in a.csv_paths:
        maj, n = normalize_file(p, a.majority, a.check)
        label = "スペースあり" if maj == "spaced" else "スペース無し"
        verb = "揃えられる" if a.check else "揃えた"
        print(f"{'CHECK' if a.check else 'OK   '} {p}: {label}に {n} 箇所{verb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
