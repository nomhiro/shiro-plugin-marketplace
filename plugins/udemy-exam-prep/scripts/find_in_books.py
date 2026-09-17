"""確定済みの本を横断して、あるキーワードが「どう問われたか」を出す。

## なぜ必要か

2本目以降を書くとき、**既に出した論点を同じ角度で再出題する事故**が起きる。
`used_concepts.py` は `tested_concept` のラベルを出すが、
**「どんな問題文で、どんな正解肢だったか」は見えない。** そこが事故の本体。

> 実績: ある講座のフル模試1本目で差し戻した6件のうち、`オープン・イノベーション` は
> 分野別演習で「説明として最も適切なものはどれか」で出ていたのに、
> フル模試でも**まったく同じ問題文**で出してしまった（問題文の類似度100%）。
> ラベル上は別概念に見えていたため、`used_concepts.py` では防げなかった。

**作問前に、扱うキーワードでこれを実行し、出てきた問題文・正解肢とは違う角度にする。**

## 出力の読み方

`出現: 問題文 / ★正解肢` のように、どこに出たかを示す。

- **★正解肢** に出ている = その用語が答えになった。**同じ答えを2回作らない**
- 誤答肢・解説だけ = まだ主役にしていない。**主役にするのは可**

使い方:
    python find_in_books.py オープン・イノベーション
    python find_in_books.py Actor-Critic --answers-only
    python find_in_books.py 正則化 --glob 'section0[123]*/quiz.csv'
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import safe_stdout  # noqa: E402
from scripts.validate_quiz_csv import (  # noqa: E402
    OPTION_PAIRS, correct_indices, read_rows,
)


def split_options(row: list[str]) -> tuple[list[str], list[str]]:
    """(正解肢, 誤答肢) を返す。"""
    idx = {int(c) for c in correct_indices(row[14]) if c.isdigit()}
    cor, inc = [], []
    for k, (opt, _) in enumerate(OPTION_PAIRS, 1):
        text = row[opt].strip()
        if not text:
            continue
        (cor if k in idx else inc).append(text)
    return cor, inc


def find(keyword: str, pattern: str, answers_only: bool) -> list[dict]:
    hits: list[dict] = []
    for p in sorted(glob.glob(pattern)):
        path = Path(p)
        for i, row in enumerate(read_rows(path)[1:], 1):
            if len(row) != 17:
                continue
            cor, inc = split_options(row)
            explanations = [row[e] for _, e in OPTION_PAIRS] + [row[15]]
            where = []
            if keyword in row[0]:
                where.append("問題文")
            if any(keyword in o for o in cor):
                where.append("★正解肢")
            elif any(keyword in o for o in inc):
                where.append("誤答肢")
            if any(keyword in e for e in explanations):
                where.append("解説")
            if not where:
                continue
            if answers_only and "★正解肢" not in where:
                continue
            hits.append({
                "section": path.parent.name, "q": i, "domain": row[16],
                "where": where, "question": row[0], "correct": cor,
            })
    return hits


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="キーワードが過去にどう問われたかを出す")
    ap.add_argument("keyword")
    ap.add_argument("--glob", default="section0*/quiz.csv",
                    help="対象の quiz.csv のパターン（既定は確定済みの全本）")
    ap.add_argument("--answers-only", action="store_true",
                    help="正解肢に含まれるものだけを出す")
    a = ap.parse_args(argv[1:])

    hits = find(a.keyword, a.glob, a.answers_only)
    if not hits:
        print(f"'{a.keyword}' はどの本にも出ていません（未使用）")
        return 0

    for h in hits:
        print(f"[{h['section']} Q{h['q']}] ({h['domain']}) 出現: {' / '.join(h['where'])}")
        print(f"    問題文: {h['question']}")
        print(f"    正解肢: {' / '.join(h['correct'])}")
        print()

    as_answer = sum(1 for h in hits if "★正解肢" in h["where"])
    print(f"'{a.keyword}' は {len(hits)} 問で使われています"
          f"（うち {as_answer} 問で正解肢）。"
          "**この問題文・この正解肢とは違う角度にしてください。**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
