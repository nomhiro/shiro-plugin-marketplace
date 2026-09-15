"""解説の整合・文体・訳の検査。形式検証では検出できない欠陥クラスを落とす。

`validate_quiz_csv.py` は形式（17カラム・正解の個数と範囲）を見るが、
**「正解番号が誤答肢を指している」を検出できない**。インデックスが範囲内で
個数が正しければ通るためである（実績: ある講座の1本目で1問、`Correct Answers`
が誤答肢を指していた）。

解説の冒頭に正誤の印を書く運用にしておけば、印と `Correct Answers` の
突き合わせでこの欠陥クラスを機械的に落とせる。同じ枠組みで訳の付け忘れ・
文体の混在・出典 URL の書き方も検査する。

検査する内容（front matter の `style` で有効・無効を切り替える）:

  1. 正誤印 × Correct Answers の整合
  2. 各 Explanation の訳マーカーの有無
  3. Overall Explanation の設問訳マーカーの有無
  4. 解説本体の文体（訳マーカーより前）
  5. 訳の文体（訳マーカー以降）
  6. 出典 URL の直後に半角スペースがあるか
     （詰めると URL 抽出が日本語を巻き込み `--check-urls` が失敗する）

front matter に `style` が無ければ**何も検査せず OK を返す**（資格非依存のため）。

使い方:
    python "${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py" section01-*/quiz.csv --sections sections.md
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

from scripts._console import safe_stdout  # noqa: E402
from scripts.profile import ProfileError, load_profile  # noqa: E402
from scripts.validate_quiz_csv import (  # noqa: E402
    OPTION_PAIRS, correct_indices, read_rows,
)

# 出典 URL。日本語（および全角括弧）で停止させる。停止させないと
# `出典: https://example.com/page【設問の訳】…` のような詰め書きで
# URL が訳文を飲み込む（実績: ある講座で27箇所）。
URL_RE = re.compile(r"https?://[^\s\u3000-\u9fff\uff00-\uffef【】]+")

# 文末の丸括弧（「（2つ選択）」など）。文体判定は述語そのものを見る必要がある。
TRAIL_PAREN_RE = re.compile(r"((?:（[^（）]*）|\([^()]*\))+)$")
SENTENCE_SPLIT_RE = re.compile(r"[。？]")


def load_style(sections_md) -> dict:
    """front matter の `style` を返す。無ければ空 dict。"""
    profile = load_profile(sections_md)
    raw = profile.get("style")
    return raw if isinstance(raw, dict) else {}


def _strip_trailing_parens(text: str) -> str:
    """末尾の括弧を外して述語そのものを露出させる。"""
    for _ in range(3):
        m = TRAIL_PAREN_RE.search(text)
        if not m or m.start() == 0:
            break
        text = text[: m.start()].rstrip()
    return text


def _tails(text: str, skip_re: re.Pattern | None, ignore: tuple[str, ...]) -> list[str]:
    """文末の述語を列挙する。出典・URL を含む断片と見出し語は除く。"""
    out = []
    for seg in SENTENCE_SPLIT_RE.split(text):
        t = seg.strip()
        if not t or t in ignore:
            continue
        if skip_re and skip_re.search(t):
            continue
        out.append(_strip_trailing_parens(t))
    return out


def check_rows(rows: list[list[str]], style: dict) -> list[str]:
    """1ファイル分の検査。エラー文字列のリストを返す。"""
    if not style:
        return []

    markers = style.get("explanation_markers") or {}
    ok_prefix = str(markers.get("correct") or "")
    ng_prefix = str(markers.get("incorrect") or "")
    option_marker = str(style.get("option_translation_marker") or "")
    question_marker = str(style.get("question_translation_marker") or "")
    body_re = re.compile(style["body_sentence_end"]) if style.get("body_sentence_end") else None
    tr_re = re.compile(style["translation_sentence_end"]) if style.get("translation_sentence_end") else None
    require_url_space = bool(style.get("require_space_after_source_url"))
    skip_re = re.compile(style["skip_sentence_pattern"]) if style.get("skip_sentence_pattern") else None
    ignore = tuple(
        str(x) for x in (style.get("ignore_sentences") or [])
    ) + tuple(p.rstrip("。") for p in (ok_prefix, ng_prefix) if p)

    errors: list[str] = []
    for i, row in enumerate(rows[1:], 2):
        if len(row) != 17:
            continue
        correct = set(correct_indices(row[14]))

        cells: list[tuple[str, str, str]] = []
        for k, (opt, exp) in enumerate(OPTION_PAIRS, 1):
            if not row[opt].strip():
                continue
            cells.append((f"Explanation {k}", row[exp], option_marker))

            # 1. 正誤印 × Correct Answers
            if ok_prefix and ng_prefix:
                want = ok_prefix if str(k) in correct else ng_prefix
                if not row[exp].startswith(want):
                    errors.append(
                        f"Row {i} Explanation {k}: 正誤印が Correct Answers と一致しません"
                        f'（"{want}" で始まるべき / 実際: "{row[exp][:12]}..."）'
                    )
        cells.append(("Overall Explanation", row[15], question_marker))

        for label, cell, marker in cells:
            # 2/3. 訳マーカーの有無
            if marker and marker not in cell:
                errors.append(f"Row {i} {label}: 訳マーカー {marker} がありません")

            body, _, tr = cell.partition(marker) if marker else (cell, "", "")

            # 4. 解説本体の文体
            if body_re:
                for t in _tails(body, skip_re, ignore):
                    if not body_re.search(t):
                        errors.append(
                            f"Row {i} {label}: 解説本体の文体が違います（…{t[-14:]}）"
                        )
            # 5. 訳の文体
            if tr_re and tr:
                for t in _tails(tr, skip_re, ignore):
                    if tr_re.search(t):
                        errors.append(
                            f"Row {i} {label}: 訳の文体が違います（…{t[-14:]}）"
                        )

        # 6. 出典 URL の直後に半角スペース
        if require_url_space:
            for m in URL_RE.finditer(row[15]):
                after = row[15][m.end(): m.end() + 1]
                if after and after != " ":
                    errors.append(
                        f"Row {i} Overall Explanation: 出典 URL の直後に半角スペースが"
                        f'ありません（"{m.group(0)[-24:]}{after}"）'
                    )
    return errors


def check_file(path, style: dict) -> list[str]:
    return check_rows(read_rows(path), style)


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="解説の整合・文体・訳を検査する")
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--sections", default="sections.md")
    a = ap.parse_args(argv[1:])

    try:
        style = load_style(a.sections)
    except (ProfileError, FileNotFoundError) as e:
        print(f"FAIL {a.sections}: {e}", file=sys.stderr)
        return 2

    if not style:
        print(
            f"SKIP {a.sections}: front matter に style が無いため文体検査は行いません"
        )
        return 0

    failed = False
    for target in a.targets:
        errors = check_file(target, style)
        if errors:
            failed = True
            print(f"FAIL {target}: {len(errors)} 件")
            for e in errors[:20]:
                print(f"  - {e}")
            if len(errors) > 20:
                print(f"  ... 他 {len(errors) - 20} 件")
        else:
            n = len(read_rows(target)) - 1
            print(f"OK   {target}: {n} 問すべて文体・整合とも適正")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
