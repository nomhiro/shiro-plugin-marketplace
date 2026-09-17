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

**この検査の基準は作問エージェントへ渡すブリーフの基準そのもの**なので、
`--print-contract` で front matter から契約文を生成できる。散文で書き写すと
ブリーフ側だけが古くなり、全問が落ちる（実績: ある講座で作問直前に発覚）。

使い方:
    python "${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py" section01-*/quiz.csv --sections sections.md
    python "${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py" --print-contract --sections sections.md
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


def contract_text(style: dict) -> str:
    """front matter の `style` から、ブリーフに貼る契約文を組み立てる。

    検査する当人が契約文も書くので、基準のずれが構造的に起きない。
    """
    if not style:
        return (
            "front matter に `style` が無いため、機械検査される解説の書式はありません。"
            "解説の体裁は講座の方針（`CLAUDE.md`）に従ってください。"
        )

    markers = style.get("explanation_markers") or {}
    ok = str(markers.get("correct") or "")
    ng = str(markers.get("incorrect") or "")
    opt_m = str(style.get("option_translation_marker") or "")
    q_m = str(style.get("question_translation_marker") or "")
    body_re = style.get("body_sentence_end") or ""
    tr_re = style.get("translation_sentence_end") or ""
    url_space = bool(style.get("require_space_after_source_url"))

    L = ["### 解説の書式（機械検査される・変更不可）", "",
         "`check_style.py` がこの書式どおりかを判定します。"
         "**1文字でも違うと担当ドメインの全問が落ちます。**", ""]

    shape = "<解説本体>"
    if ok and ng:
        shape = "<正誤印>" + shape
    if opt_m:
        shape += opt_m + "<その選択肢の訳>"
    L += ["**各 `Explanation N`（選択肢ごとの解説）:**", "", "```", shape, "```", ""]

    if ok and ng:
        L += [
            f"- 先頭の正誤印は `Correct Answers` と一致させる。"
            f"**正解の選択肢は `{ok}` で始め、不正解の選択肢は `{ng}` で始める**",
            "- 印と `Correct Answers` のずれは「正解番号が誤答肢を指している」欠陥として"
            "検出されます（形式検証では通ってしまう欠陥クラス）",
        ]
    if opt_m:
        L.append(f"- **`{opt_m}` は必須。** これより前が解説本体、これ以降がその選択肢の訳")

    q_shape = "<設問の要約>…<正解の理由>…<他の選択肢が破綻する理由>…出典: <URL>"
    if url_space:
        q_shape += " "
    if q_m:
        q_shape += q_m + "<設問文の訳>"
    L += ["", "**`Overall Explanation`:**", "", "```", q_shape, "```", ""]
    if q_m:
        L.append(f"- **`{q_m}` は必須。** これより前が解説本体、これ以降が設問文の訳")
    if url_space:
        L.append(
            "- **出典 URL の直後に半角スペースを1つ置く。** 詰めると URL の抽出が"
            "日本語を巻き込み、到達確認が失敗します"
        )

    if body_re or tr_re:
        L += ["", "**文体（本体と訳で書き分ける）:**", ""]
        if body_re:
            L.append(f"- 解説本体の文末は正規表現 `{body_re}` に**一致させる**")
        if tr_re:
            L.append(f"- 訳の文末は正規表現 `{tr_re}` に**一致させない**")
        skip = style.get("skip_sentence_pattern")
        if skip:
            L.append(f"- `{skip}` を含む文は文体の判定から外れます")
        ignores = style.get("ignore_sentences") or []
        if ignores:
            L.append("- 判定から外れる定型文: " + " / ".join(f"`{x}`" for x in ignores))

    L += ["", "自己チェック:", "", "```bash",
          'python "$P/check_style.py" <セクション>/_parts/<ドメイン>.csv --sections sections.md',
          "```"]
    return "\n".join(L)


def check_file(path, style: dict) -> list[str]:
    return check_rows(read_rows(path), style)


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="解説の整合・文体・訳を検査する")
    ap.add_argument("targets", nargs="*")
    ap.add_argument("--sections", default="sections.md")
    ap.add_argument(
        "--print-contract", action="store_true",
        help="front matter の style から、作問ブリーフに貼る契約文を出力する",
    )
    a = ap.parse_args(argv[1:])

    try:
        style = load_style(a.sections)
    except (ProfileError, FileNotFoundError) as e:
        print(f"FAIL {a.sections}: {e}", file=sys.stderr)
        return 2

    if a.print_contract:
        print(contract_text(style))
        return 0

    if not a.targets:
        ap.error("検査対象の CSV を1つ以上指定してください（または --print-contract）")

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
