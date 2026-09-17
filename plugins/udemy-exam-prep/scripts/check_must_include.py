"""ユーザーが「必ず入れる」と指定した問題が、実際に収録されているかを照合する。

## なぜ必要か

受講者が持ち込む過去問・直前まとめを「この問題は必ず入れて」と渡されることがある。
これは**作問の自由度ではなく要件**なので、入っているかどうかを機械で確かめる必要がある。

> 実績: ある講座では128問の必須収録指定があった。指定元は短答形式のメモで、
> 4択化すると設問の言い回しが変わるため、**問題文だけを突き合わせると入っているのに
> 「入っていない」と誤判定する**。逆に人間が目視で数えると取りこぼす。

## 判定の仕組み

1. 指定ファイルから項目を1件ずつ切り出す（表の行・箇条書き・番号付きリスト）
2. 各項目から**特徴語**（カタカナ語・英数字の術語・漢語）を抽出する
3. 講座の各問について、**問題文側の被覆率と解答側の被覆率を別々に測り、高いほうを採る**

   4択化で設問の言い回しが変わっても、**答えになる用語は残る**。
   片側だけで測ると取りこぼす（実績: `RMSprop` の問題を設問側だけで測って誤検出した）。

4. 最も被覆率の高い問題を「対応する問題」として報告する

## これは screening である（自動 FAIL にしない）

被覆率は指標であって証明ではない。**閾値未満を一覧にして人が見る**ための道具で、
既定では終了コードを 0 のままにする。`--strict` を付けたときだけ落とす。

使い方:
    python check_must_include.py research/must-include.md
    python check_must_include.py research/must-include.md --threshold 0.6
    python check_must_include.py research/must-include.md --strict
"""
from __future__ import annotations

import argparse
import glob
import re
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

# 被覆率の既定の閾値。これ未満を「収録が疑わしい」として一覧にする
DEFAULT_THRESHOLD = 0.5

# 特徴語として拾うパターン: カタカナ語 / 英数字の術語 / 漢語
FEATURE_RES = (
    re.compile(r"[ァ-ヶー]{3,}"),
    re.compile(r"[A-Za-z][A-Za-z0-9._+-]{1,}"),
    re.compile(r"[一-龠]{2,}"),
)

# どの問題にも出るので特徴語にならない語
STOPWORDS = {
    "適切", "不適切", "最適", "説明", "記述", "特徴", "用語", "手法", "方法", "場合",
    "以下", "次の", "問題", "正解", "選択", "組み合", "組合", "理由", "目的", "内容",
    "上記", "該当", "関係", "状態", "結果", "対象", "実施", "利用", "使用", "必要",
    "可能", "重要", "一般", "基本", "代表", "具体", "全体", "部分", "以上", "以内",
}


def feature_words(text: str) -> list[str]:
    """項目から特徴語を抽出する。"""
    words: list[str] = []
    for pat in FEATURE_RES:
        words += pat.findall(text)
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        w = w.strip("._+-")
        if len(w) < 2 or w in STOPWORDS or w in seen:
            continue
        if any(s in w for s in STOPWORDS) and len(w) <= 4:
            continue
        seen.add(w)
        out.append(w)
    return out


# 設問側・解答側の行を見分ける印。
# **Q/A が別行に分かれている資料は1件として束ねる。**
# 束ねないと項目数が倍に数えられ、しかも解答行（数値や短い断片だけの行）が
# 単独項目として「収録されていない」と大量に誤検出される
# （実績: 128問の指定が 256 件と数えられ、うち66件が誤検出だった）。
Q_MARK_RE = re.compile(r"^(\*\*)?(Q|問)[.:：]?(\*\*)?\s*[.:：]?\s*")
A_MARK_RE = re.compile(r"^(\*\*)?(A|答|解答)[.:：]?(\*\*)?\s*[.:：]?\s*")


def parse_items(path: Path) -> list[tuple[str, str]]:
    """指定ファイルから必須項目を `(設問側, 解答側)` の対で切り出す。

    表の行（`|` 区切り）・箇条書き（`-` `・`）・番号付きリストに対応する。
    見出し・区切り線・空行は落とす。

    `Q:` と `A:` が別行の資料は**1件の対として束ねる**。
    **連結して1つの文字列にはしない。** 連結すると解答側の解説文まで特徴語に
    入って母数が膨らみ、実際は収録されている項目の被覆率が下がる
    （実測: 連結すると 128件中 63件しか閾値を超えなかった）。
    設問側・解答側それぞれで測って高いほうを採るために、対のまま持つ。
    """
    lines = path.read_text(encoding="utf-8-sig").splitlines()

    def is_separator(text: str) -> bool:
        cells = [c.strip() for c in text.strip().strip("|").split("|")]
        return bool(cells) and all(set(c) <= {"-", ":", " "} and c for c in cells)

    items: list[tuple[str, str]] = []
    pending_q = False
    for n, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(">"):
            continue
        if s.startswith("|"):
            if is_separator(s):
                continue
            # 次の行が区切り線ならこれは表のヘッダー行。項目ではない
            if n + 1 < len(lines) and is_separator(lines[n + 1]):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            body = " ".join(c for c in cells if c)
            pending_q = False
        elif re.match(r"^([-*・]|\d+[.)])\s+", s):
            body = re.sub(r"^([-*・]|\d+[.)])\s+", "", s)
            if A_MARK_RE.match(body) and pending_q and items:
                q, _ = items[-1]
                items[-1] = (q, A_MARK_RE.sub("", body, count=1))
                pending_q = False
                continue
            pending_q = bool(Q_MARK_RE.match(body))
            body = Q_MARK_RE.sub("", body, count=1)
        else:
            pending_q = False
            continue
        if len(body) >= 6:
            items.append((body, ""))
    return items


def answer_text(row: list[str]) -> str:
    """正解肢のテキストを連結して返す。"""
    idx = {int(c) for c in correct_indices(row[14]) if c.isdigit()}
    return " ".join(
        row[opt] for k, (opt, _) in enumerate(OPTION_PAIRS, 1) if k in idx
    )


def coverage(words: list[str], text: str) -> float:
    if not words:
        return 0.0
    return sum(1 for w in words if w in text) / len(words)


def best_match(item: tuple[str, str], rows: list[tuple[str, int, str, str]]) -> tuple:
    """最も被覆率の高い問題を返す。(被覆率, セクション, 問番号, 問題文)。

    **設問側の特徴語と解答側の特徴語で別々に測り、高いほうを採る。**

    4択化すると設問の言い回しは変わるが**答えになる用語は残る**ので、
    片側だけで測ると取りこぼす（実績: `RMSprop` の問題を設問側だけで
    測って「収録されていない」と誤検出した）。逆に、○×問題は設問側に
    用語が集まり解答側が「×。」だけになるので、解答側だけでも取りこぼす。
    """
    q_words = feature_words(item[0])
    a_words = feature_words(item[1]) if item[1] else []
    best = (0.0, "", 0, "")
    for section, no, question, haystack in rows:
        score = max(coverage(q_words, haystack), coverage(a_words, haystack))
        if score > best[0]:
            best = (score, section, no, question)
    return best


def load_course_rows(pattern: str) -> list[tuple[str, int, str, str]]:
    """(セクション, 問番号, 問題文, 照合用テキスト) を返す。

    照合用テキストは**問題文・全選択肢・全体解説を連ねたもの**にする。
    指定元の用語が問題文にあるか選択肢にあるかは作問時の判断で変わるため、
    どちらに置かれても拾えるようにしておく。
    """
    out: list[tuple[str, int, str, str]] = []
    for p in sorted(glob.glob(pattern)):
        path = Path(p)
        for i, row in enumerate(read_rows(path)[1:], 1):
            if len(row) != 17:
                continue
            options = " ".join(row[opt] for opt, _ in OPTION_PAIRS)
            haystack = f"{row[0]} {options} {row[15]}"
            out.append((path.parent.name, i, row[0], haystack))
    return out


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="必須収録の指定と講座の突き合わせ")
    ap.add_argument("must_include", help="必須収録を列挙したマークダウン")
    ap.add_argument("--glob", default="section0*/quiz.csv",
                    help="照合先の quiz.csv のパターン")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"被覆率の閾値（既定 {DEFAULT_THRESHOLD}）")
    ap.add_argument("--strict", action="store_true",
                    help="閾値未満が1件でもあれば終了コード 1 にする")
    a = ap.parse_args(argv[1:])

    items = parse_items(Path(a.must_include))
    if not items:
        print(f"FAIL: {a.must_include} から項目を読み取れませんでした")
        return 1
    rows = load_course_rows(a.glob)
    if not rows:
        print(f"FAIL: {a.glob} に問題がありません")
        return 1

    print(f"=== 必須収録の照合: 指定 {len(items)} 件 / 講座 {len(rows)} 問 ===")
    low: list[tuple[float, str, str]] = []
    for item in items:
        score, section, no, _ = best_match(item, rows)
        if score < a.threshold:
            label = (item[0] + (" / " + item[1] if item[1] else "")).strip()
            low.append((score, label, f"{section}/Q{no}" if section else "該当なし"))

    ok = len(items) - len(low)
    print(f"閾値 {a.threshold:.0%} 以上で対応が見つかった: {ok}/{len(items)} 件")
    if low:
        print(f"\n--- 収録が疑わしい {len(low)} 件（人が確認する）---")
        for score, item, where in sorted(low):
            print(f"  被覆 {score:.0%} 最も近い問題 {where}")
            print(f"    {item[:100]}")
    else:
        print("すべての指定に対応する問題が見つかりました")

    return 1 if (a.strict and low) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
