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

front matter に `style` が無い（または空）ときも、**1. の正誤印の整合だけは既定の
印（先頭が `正解` / `不正解`、英語なら `Correct` / `Incorrect`）で検査する**。
正答の取り違えを落とす要なので、設定漏れで黙って素通りさせない（実績: ある講座で
`style: {}` のまま運用し、正誤印の欠落33件と「不正解。」「不正解です。」の混在が
全検査 OK のまま残った）。このとき WARN を出す（終了コードは変えない）。
既定の検査では印が1件も無いファイルは WARN にとどめ、一部にだけ印がある
ファイルは欠落を FAIL にする。明示的に止めるには `explanation_markers: false`。

加えて front matter の `glossary`（原語で書く用語と禁止訳語）があれば、
`Domain` 列を除く全カラムで禁止訳語を FAIL にする（`style` の有無と独立）。
散文の「原語のまま書く」は守られない（実績: ある講座の300問で約400件の
和訳・カタカナ化・直訳調が混入した）。

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
from collections import Counter
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import safe_stdout  # noqa: E402
from scripts.profile import ProfileError, glossary, load_profile  # noqa: E402
from scripts.validate_quiz_csv import (  # noqa: E402
    HEADER, OPTION_PAIRS, correct_indices, read_rows,
)

# 出典 URL。日本語（および全角括弧）で停止させる。停止させないと
# `出典: https://example.com/page【設問の訳】…` のような詰め書きで
# URL が訳文を飲み込む（実績: ある講座で27箇所）。
URL_RE = re.compile(r"https?://[^\s\u3000-\u9fff\uff00-\uffef【】]+")

# 文末の丸括弧（「（2つ選択）」など）。文体判定は述語そのものを見る必要がある。
TRAIL_PAREN_RE = re.compile(r"((?:（[^（）]*）|\([^()]*\))+)$")
SENTENCE_SPLIT_RE = re.compile(r"[。？]")

# style に explanation_markers が無いときの既定の正誤印（先頭一致・後続は任意）。
# 「不正解。」「不正解です。」のどちらも通す。表記の統一は style で明示したときだけ見る。
DEFAULT_MARKERS = (("正解", "不正解"), ("Correct", "Incorrect"))

# 禁止訳語の走査から外すカラム（Domain は sections.md の正式名をそのまま写すため）
GLOSSARY_SKIP_COLS = (16,)
# 集計用: check_glossary のエラー文から禁止訳語を取り出す
GLOSSARY_HIT_RE = re.compile(r'禁止訳語 "([^"]+)"')


def load_style(sections_md) -> dict:
    """front matter の `style` を返す。無ければ空 dict。"""
    profile = load_profile(sections_md)
    raw = profile.get("style")
    return raw if isinstance(raw, dict) else {}


def load_glossary(sections_md) -> list[dict]:
    """front matter の `glossary` を返す。無ければ空リスト。"""
    return glossary(load_profile(sections_md))


def marker_rule(style: dict) -> dict | None:
    """正誤印の検査規則。None なら検査しない（`explanation_markers: false` のときだけ）。

    style で印を明示していれば**その文字列との完全な先頭一致**（表記揺れも落とす）。
    明示が無ければ既定の印で**正誤だけ**を見る。
    """
    raw = (style or {}).get("explanation_markers")
    if raw is False:
        return None
    if isinstance(raw, dict) and raw.get("correct") and raw.get("incorrect"):
        return {"pairs": ((str(raw["correct"]), str(raw["incorrect"])),), "strict": True}
    return {"pairs": DEFAULT_MARKERS, "strict": False}


def read_verdict(text: str, pairs) -> bool | None:
    """解説冒頭の正誤印を読む。True=正解 / False=不正解 / None=印なし。"""
    t = text.lstrip()
    for ok, ng in pairs:
        # 「不正解」は「正解」を含まないが、印の包含関係に依らないよう不正解側を先に見る
        if t.startswith(ng):
            return False
        if t.startswith(ok):
            return True
    return None


def check_markers(rows: list[list[str]], style: dict) -> tuple[list[str], list[str]]:
    """正誤印 x Correct Answers の整合。(エラー, 警告) を返す。"""
    rule = marker_rule(style)
    if rule is None:
        return [], []
    errors: list[str] = []
    missing: list[str] = []
    marked = 0
    for i, row in enumerate(rows[1:], 2):
        if len(row) != 17:
            continue
        correct = set(correct_indices(row[14]))
        for k, (opt, exp) in enumerate(OPTION_PAIRS, 1):
            if not row[opt].strip():
                continue
            is_correct = str(k) in correct
            if rule["strict"]:
                ok, ng = rule["pairs"][0]
                want = ok if is_correct else ng
                if not row[exp].startswith(want):
                    errors.append(
                        f"Row {i} Explanation {k}: 正誤印が Correct Answers と一致しません"
                        f'（"{want}" で始まるべき / 実際: "{row[exp][:12]}..."）'
                    )
                continue
            got = read_verdict(row[exp], rule["pairs"])
            if got is None:
                missing.append(
                    f'Row {i} Explanation {k}: 正誤印がありません（"{row[exp][:12]}..."）'
                )
                continue
            marked += 1
            if got != is_correct:
                want = "正解" if is_correct else "不正解"
                errors.append(
                    f"Row {i} Explanation {k}: 正誤印が Correct Answers と一致しません"
                    f'（{want}の印で始まるべき / 実際: "{row[exp][:12]}..."）'
                )
    if rule["strict"]:
        return errors, []
    if missing and marked == 0:
        # 印を書かない運用の講座。整合は検査できないので警告にとどめる
        return errors, [
            "解説の冒頭に正誤印が1件もありません。正答の取り違えを機械検査できないため、"
            "各 Explanation を「正解」/「不正解」で始める運用を推奨します"
        ]
    return errors + missing, []


def _mask(text: str, phrases) -> str:
    """許可する言い回しを同じ長さの NUL で潰す（位置を保ったまま検索対象から外す）。"""
    for ph in phrases:
        if ph and ph in text:
            text = text.replace(ph, "\0" * len(ph))
    return text


def check_glossary(rows: list[list[str]], gloss: list[dict]) -> list[str]:
    """禁止訳語の検出。`Domain` 列以外の全カラムを走査する。"""
    if not gloss:
        return []
    errors: list[str] = []
    for i, row in enumerate(rows[1:], 2):
        for c, cell in enumerate(row):
            if c in GLOSSARY_SKIP_COLS or not cell:
                continue
            label = HEADER[c] if c < len(HEADER) else f"列{c + 1}"
            for entry in gloss:
                masked = _mask(cell, entry["allow_context"])
                for word in entry["forbid"]:
                    n = masked.count(word)
                    if not n:
                        continue
                    pos = masked.find(word)
                    ctx = cell[max(0, pos - 8): pos + len(word) + 8]
                    times = f" x{n}" if n > 1 else ""
                    errors.append(
                        f'Row {i} {label}: 禁止訳語 "{word}"{times} → 原語 "{entry["term"]}" '
                        f"で書く（…{ctx}…）"
                    )
    return errors


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


def check_rows(
    rows: list[list[str]], style: dict, gloss: list[dict] | None = None
) -> list[str]:
    """1ファイル分の検査。エラー文字列のリストを返す。

    style が空でも正誤印の整合（既定の印）と glossary は検査する。
    警告も要るなら `check_rows_with_warnings` を使う。
    """
    return check_rows_with_warnings(rows, style, gloss)[0]


def check_rows_with_warnings(
    rows: list[list[str]], style: dict, gloss: list[dict] | None = None
) -> tuple[list[str], list[str]]:
    """1ファイル分の検査。(エラー, 警告) を返す。"""
    style = style or {}
    errors, warnings = check_markers(rows, style)
    errors = errors + _check_style_rows(rows, style) + check_glossary(rows, gloss or [])
    return errors, warnings


def _check_style_rows(rows: list[list[str]], style: dict) -> list[str]:
    """style で有効にした検査（訳マーカー・文体・出典 URL の空白）。"""
    if not style:
        return []

    markers = style.get("explanation_markers") or {}
    if not isinstance(markers, dict):
        markers = {}
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

        cells: list[tuple[str, str, str]] = []
        for k, (opt, exp) in enumerate(OPTION_PAIRS, 1):
            if not row[opt].strip():
                continue
            cells.append((f"Explanation {k}", row[exp], option_marker))
            # 1. 正誤印 x Correct Answers は check_markers が見る
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


def contract_text(style: dict, gloss: list[dict] | None = None) -> str:
    """front matter の `style` と `glossary` から、ブリーフに貼る契約文を組み立てる。

    検査する当人が契約文も書くので、基準のずれが構造的に起きない。
    style が空でも既定の正誤印の検査は効くので、その規則は必ず書き出す
    （書かないと「検査はあるのにブリーフに無い」ずれが再発する）。
    """
    style = style or {}
    rule = marker_rule(style)
    markers = style.get("explanation_markers")
    markers = markers if isinstance(markers, dict) else {}
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
    if not style:
        L += ["front matter に `style` が無いため、機械検査されるのは**正誤印の整合**"
              "（と下記の用語集）だけです。それ以外の体裁は講座の方針（`CLAUDE.md`）に従ってください。", ""]

    shape = "<解説本体>"
    if rule:
        shape = "<正誤印>" + shape
    if opt_m:
        shape += opt_m + "<その選択肢の訳>"
    L += ["**各 `Explanation N`（選択肢ごとの解説）:**", "", "```", shape, "```", ""]

    if rule and rule["strict"]:
        L.append(
            f"- 先頭の正誤印は `Correct Answers` と一致させる。"
            f"**正解の選択肢は `{ok}` で始め、不正解の選択肢は `{ng}` で始める**"
            "（表記揺れも不可）"
        )
    elif rule:
        L.append(
            "- 先頭の正誤印は `Correct Answers` と一致させる。"
            "**正解の選択肢は `正解` で始め、不正解の選択肢は `不正解` で始める**"
            "（英語の解説なら `Correct` / `Incorrect`）。全選択肢に付ける"
        )
    if rule:
        L.append(
            "- 印と `Correct Answers` のずれは「正解番号が誤答肢を指している」欠陥として"
            "検出されます（形式検証では通ってしまう欠陥クラス）"
        )
    if opt_m:
        L.append(f"- **`{opt_m}` は必須。** これより前が解説本体、これ以降がその選択肢の訳")

    if style:
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

    if gloss:
        L += ["", "**用語集（原語で書く・禁止訳語は使わない）:**", "",
              "左の用語は**原語のまま**書く。右の表記は問題文・選択肢・解説のどこにも"
              "書かない（`Domain` 列以外の全カラムを部分一致で検査します）。", "",
              "| 原語で書く | 使ってはいけない表記 |", "|---|---|"]
        for e in gloss:
            L.append(f"| `{e['term']}` | " + " / ".join(e["forbid"]) + " |")

    L += ["", "自己チェック:", "", "```bash",
          'python "$P/check_style.py" <セクション>/_parts/<ドメイン>.csv --sections sections.md',
          "```"]
    return "\n".join(L)


def check_file(path, style: dict, gloss: list[dict] | None = None) -> list[str]:
    return check_rows(read_rows(path), style, gloss)


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="解説の整合・文体・訳・用語を検査する")
    ap.add_argument("targets", nargs="*")
    ap.add_argument("--sections", default="sections.md")
    ap.add_argument(
        "--print-contract", action="store_true",
        help="front matter の style / glossary から、作問ブリーフに貼る契約文を出力する",
    )
    ap.add_argument(
        "--max-errors", type=int, default=20,
        help="1ファイルあたり表示するエラーの上限（既定 20。0 で全件）",
    )
    a = ap.parse_args(argv[1:])

    try:
        style = load_style(a.sections)
        gloss = load_glossary(a.sections)
    except (ProfileError, FileNotFoundError) as e:
        print(f"FAIL {a.sections}: {e}", file=sys.stderr)
        return 2

    if a.print_contract:
        print(contract_text(style, gloss))
        return 0

    if not a.targets:
        ap.error("検査対象の CSV を1つ以上指定してください（または --print-contract）")

    if not style:
        # 黙って SKIP すると設定漏れに誰も気づかない（実績: 正誤印の欠落33件が素通り）
        print("=" * 72)
        print(
            f"WARN {a.sections}: front matter に style が無い（または空）。"
            "正誤印 x Correct Answers の整合だけを既定の印（正解 / 不正解）で検査します。"
        )
        print(
            "     訳マーカー・文体・出典 URL 直後の空白・正誤印の表記統一は検査されません。"
            "雛形の style を有効にしてください。"
        )
        print("=" * 72)

    failed = False
    limit = a.max_errors if a.max_errors > 0 else None
    for target in a.targets:
        rows = read_rows(target)
        errors, warnings = check_rows_with_warnings(rows, style, gloss)
        for w in warnings:
            print(f"WARN {target}: {w}")
        if errors:
            failed = True
            print(f"FAIL {target}: {len(errors)} 件")
            for e in errors[:limit]:
                print(f"  - {e}")
            if limit and len(errors) > limit:
                print(f"  ... 他 {len(errors) - limit} 件（--max-errors 0 で全件）")
            hits = Counter(
                m.group(1) for e in errors for m in [GLOSSARY_HIT_RE.search(e)] if m
            )
            if hits:
                print("  禁止訳語の内訳: " + " / ".join(f"{w} {n}" for w, n in hits.most_common()))
        else:
            print(f"OK   {target}: {len(rows) - 1} 問すべて文体・整合・用語とも適正")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
