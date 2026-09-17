"""正解肢の「長さバイアス」を検出する。

LLM が問題を書くと、正解肢に根拠や仕組みの説明を書き込んでしまい、
**正解が一貫して長い選択肢になる**。受講者は内容を読まずに「長いものを選ぶ」
だけで正解できてしまい、模試の価値が失われる。

実績: ある講座の模試1本目（multiple-choice 45問）で、正解肢が2位の選択肢を
平均 +29%（最大 +111%）上回っていた。

位置バイアス（shuffle_options.py）と同じ「攻略可能な偏り」だが、
長さは位置を変えても付いてくるのでシャッフルでは解消できない。
**内容の修正が必要**なので、品質ゲートとしてシャッフル前に通す。

判定の中心は **margin**（正解肢が2位の選択肢をどれだけ上回るか）。
「最長かどうか」の二値では、長さがほぼ揃っている問題の統計的な同着まで
欠陥として報告してしまう（実測: 正解長が他の 1.03 倍でも 71% が「最長」になる）。
受講者が知覚できるのは差の大きさなので margin で測る。

  - 1問ごと: margin が margin_limit を超えていないか（既定 +20%）
             選択肢の長さの散らばり (max-min)/max が spread 以内か（既定 30%）
  - ファイル全体: margin の平均が mean_limit 以内か（既定 +8%）
                  margin_limit 超の問題の割合が share_limit 以内か（既定 15%）

## multi-select も検査する

旧版は `multiple-choice` 以外を**丸ごとスキップ**していた。正解が複数だと
「2位との差」が定義できないためだが、その結果 **multi-select の長さバイアスが
無検査で通っていた。**

> 実績: ある講座の multi-select 42問のうち **14問で正解肢がすべて最長**、
> うち4問は「長い順に2つ選ぶだけで当たる」本物の欠陥だった。
> 分量が少ない形式ほど1問の重みが大きいので、ここを空けておく理由はない。

multi-select は **最も短い正解肢が、最も長い誤答肢をどれだけ上回るか**で測る。
これが正なら「長い順に N 個選ぶ」で全問正解でき、受講者は問題文を読まずに済む。

## 短い選択肢だけの問題は散らばりを免除する

用語名を裸で並べる問題（本番でよくある形）は散らばりが大きく出るが、
**長い術語を選んでも正解にはならない**ので攻略可能性はない。

> 実績: この停止を通すために作問エージェントが `FCN(モデル)` のような
> **意味のないタグで字数を稼いだ**（20件）。検査のために内容を歪めさせては本末転倒。

そこで**全選択肢が `SHORT_OPTION_MAX_LEN` 以内なら散らばりは許容**し、
代わりに**字数稼ぎタグそのものを検出**する。

使い方:
    python check_option_balance.py <quiz.csv> [...]
    python check_option_balance.py <quiz.csv> --margin 0.20 --mean 0.08
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
from scripts.validate_quiz_csv import OPTION_PAIRS, correct_indices, read_rows

# 1問の選択肢の長さの散らばりの上限（(max-min)/max）
DEFAULT_SPREAD = 0.30
# 正解肢が2位をこれ以上上回ったら「目立って長い」= 攻略可能とみなす
DEFAULT_MARGIN = 0.20
# margin の平均の上限（0 に近いほど良い）
DEFAULT_MEAN = 0.08
# margin 超過問題の割合の上限
DEFAULT_SHARE = 0.15
# 「短い選択肢だけの問題」と見なす上限。これ以内なら散らばりを免除する。
#
# **英語の術語は日本語より長くなる。** `Contrastive Loss`(16字) と
# `交差エントロピー`(8字) を並べると散らばり 50% になるが、これは言語の違いで
# あって作問の偏りではない。本番も術語を裸で並べるのでこの形が正しい。
SHORT_OPTION_MAX_LEN = 18
# 意味のない字数稼ぎのタグ。選択肢の末尾に付けて長さを揃えた痕跡。
PADDING_TAG_RE = re.compile(r"[（(](手法|用語|モデル|技術|概念|方式|指標|名称|語)[）)]\s*$")


def option_lengths(row: list[str]) -> dict[int, int]:
    return {
        i + 1: len(row[opt])
        for i, (opt, _) in enumerate(OPTION_PAIRS)
        if row[opt].strip()
    }


def analyze(path) -> dict:
    """multiple-choice の各問について長さの指標を出す。

    multi-select は正解が複数なので長さ比較の対象にしない。
    """
    rows = read_rows(path)[1:]
    per_question: list[dict] = []
    for i, row in enumerate(rows, 1):
        if len(row) != 17 or row[1].strip() != "multiple-choice":
            continue
        lengths = option_lengths(row)
        if len(lengths) < 2:
            continue
        correct = correct_indices(row[14])
        if len(correct) != 1 or not correct[0].isdigit():
            continue
        c = int(correct[0])
        if c not in lengths:
            continue

        mx, mn = max(lengths.values()), min(lengths.values())
        others = [v for k, v in lengths.items() if k != c]
        second = max(others) if others else lengths[c]
        per_question.append({
            "q": i,
            "lengths": lengths,
            "correct": c,
            "spread": (mx - mn) / mx if mx else 0.0,
            "max_len": mx,
            # 正解肢が2位の選択肢をどれだけ上回るか。負なら最長ではない
            "margin": (lengths[c] - second) / second if second else 0.0,
            "is_longest": lengths[c] == mx,
            "is_shortest": lengths[c] == mn,
            "ratio": lengths[c] / (sum(others) / len(others)) if others else 1.0,
            "n_options": len(lengths),
        })

    n = len(per_question)
    if n == 0:
        return {"n": 0, "per_question": []}

    margins = [e["margin"] for e in per_question]
    return {
        "n": n,
        "longest": sum(1 for e in per_question if e["is_longest"]),
        "shortest": sum(1 for e in per_question if e["is_shortest"]),
        "mean_margin": sum(margins) / n,
        "max_margin": max(margins),
        "mean_ratio": sum(e["ratio"] for e in per_question) / n,
        "per_question": per_question,
    }


def analyze_multi_select(path) -> dict:
    """multi-select の長さバイアスを測る。

    **最も短い正解肢が、最も長い誤答肢をどれだけ上回るか**を margin とする。
    これが正なら「長い順に N 個選ぶ」だけで全問正解できてしまう。
    """
    rows = read_rows(path)[1:]
    per_question: list[dict] = []
    for i, row in enumerate(rows, 1):
        if len(row) != 17 or row[1].strip() != "multi-select":
            continue
        lengths = option_lengths(row)
        correct = {int(c) for c in correct_indices(row[14]) if c.isdigit()}
        cor = [v for k, v in lengths.items() if k in correct]
        inc = [v for k, v in lengths.items() if k not in correct]
        if len(cor) < 2 or not inc:
            continue

        mx, mn = max(lengths.values()), min(lengths.values())
        per_question.append({
            "q": i,
            "lengths": lengths,
            "correct": sorted(correct),
            "spread": (mx - mn) / mx if mx else 0.0,
            "max_len": mx,
            # 最短の正解肢が最長の誤答肢をどれだけ上回るか
            "margin": (min(cor) - max(inc)) / max(inc) if max(inc) else 0.0,
            "all_correct_longest": min(cor) > max(inc),
        })

    n = len(per_question)
    if n == 0:
        return {"n": 0, "per_question": []}
    margins = [e["margin"] for e in per_question]
    return {
        "n": n,
        "all_correct_longest": sum(1 for e in per_question if e["all_correct_longest"]),
        "mean_margin": sum(margins) / n,
        "max_margin": max(margins),
        "per_question": per_question,
    }


def multi_select_problems(
    result: dict,
    margin_limit: float = DEFAULT_MARGIN,
    short_max: int = SHORT_OPTION_MAX_LEN,
) -> list[str]:
    """multi-select の攻略可能な長さバイアスだけを報告する。

    全選択肢が短い問題は、長さで選んでも当たらないので免除する。
    """
    out: list[str] = []
    for e in result.get("per_question", []):
        if e["margin"] <= margin_limit:
            continue
        if e["max_len"] <= short_max:
            continue
        cor = [v for k, v in e["lengths"].items() if k in e["correct"]]
        inc = [v for k, v in e["lengths"].items() if k not in e["correct"]]
        out.append(
            f"Q{e['q']}: multi-select の正解肢が誤答肢より体系的に長い"
            f"（正解 {sorted(cor)} / 誤答 {sorted(inc)} / margin {e['margin']:+.0%}）"
            " - 長い順に選ぶだけで当たる。誤答肢を具体化して長さを揃える"
        )
    return out


def padding_tags(path) -> list[str]:
    """字数稼ぎのタグが付いた選択肢を報告する。

    検査を通すために付けられた `FCN(モデル)` のような接尾辞を拾う。
    本番はモデル名を裸で並べるので、この形は受講者に誤った表記を覚えさせる。
    """
    out: list[str] = []
    for i, row in enumerate(read_rows(path)[1:], 1):
        if len(row) != 17:
            continue
        for k, (opt, _) in enumerate(OPTION_PAIRS, 1):
            text = row[opt].strip()
            if text and PADDING_TAG_RE.search(text):
                out.append(
                    f"Q{i} 選択肢{k}: 字数稼ぎのタグが付いている「{text}」"
                    " - 意味のある限定語に置き換えるか、裸の用語名に戻す"
                )
    return out


def problems(
    result: dict,
    spread: float = DEFAULT_SPREAD,
    margin_limit: float = DEFAULT_MARGIN,
    mean_limit: float = DEFAULT_MEAN,
    share_limit: float = DEFAULT_SHARE,
    short_max: int = SHORT_OPTION_MAX_LEN,
) -> list[str]:
    if result["n"] == 0:
        return []

    out: list[str] = []
    over: list[dict] = []
    for e in result["per_question"]:
        if e["margin"] > margin_limit:
            over.append(e)
            out.append(
                f"Q{e['q']}: 正解肢が2位より {e['margin']:+.0%} 長い"
                f"（上限 {margin_limit:+.0%}）{e['lengths']}（正解 {e['correct']}）"
                " - 不正解肢を具体化して長さを揃える"
            )
        elif e["spread"] > spread and e.get("max_len", 0) > short_max:
            # 全選択肢が短い問題は免除する。用語名を裸で並べた形は
            # 散らばりが大きく出るが、長いものを選んでも正解にはならない
            out.append(
                f"Q{e['q']}: 選択肢の長さの散らばり {e['spread']:.0%} が"
                f"上限 {spread:.0%} を超える {e['lengths']}（正解 {e['correct']}）"
            )

    if result["mean_margin"] > mean_limit:
        out.append(
            f"margin の平均 {result['mean_margin']:+.1%} が上限 {mean_limit:+.0%} を超える"
            " - 正解肢が体系的に長い。内容を読まずに長いものを選べてしまう"
        )

    share = len(over) / result["n"]
    if share > share_limit:
        out.append(
            f"margin {margin_limit:+.0%} 超の問題が {len(over)}/{result['n']} 問"
            f"（{share:.0%}）で上限 {share_limit:.0%} を超える"
        )
    return out


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="正解肢の長さバイアスを検出する")
    ap.add_argument("csv_paths", nargs="+")
    ap.add_argument("--spread", type=float, default=DEFAULT_SPREAD,
                    help="1問の選択肢長の散らばりの上限（既定 0.30）")
    ap.add_argument("--margin", type=float, default=DEFAULT_MARGIN,
                    help="正解肢が2位を上回ってよい割合の上限（既定 0.20）")
    ap.add_argument("--mean", type=float, default=DEFAULT_MEAN,
                    help="margin の平均の上限（既定 0.08）")
    ap.add_argument("--share", type=float, default=DEFAULT_SHARE,
                    help="margin 超過問題の割合の上限（既定 0.15）")
    ap.add_argument("--short-max", type=int, default=SHORT_OPTION_MAX_LEN,
                    help="この字数以内の選択肢だけの問題は散らばりを免除する（既定 18）")
    a = ap.parse_args(argv[1:])

    failed = False
    for target in a.csv_paths:
        result = analyze(target)
        ms = analyze_multi_select(target)

        errs: list[str] = []
        if result["n"]:
            errs += problems(result, a.spread, a.margin, a.mean, a.share, a.short_max)
        errs += multi_select_problems(ms, a.margin, a.short_max)
        errs += padding_tags(target)

        if result["n"] == 0 and ms["n"] == 0:
            print(f"SKIP {target}: 判定対象の問題がない")
            continue

        parts = []
        if result["n"]:
            parts.append(
                f"MC {result['n']}問"
                f" / margin 平均 {result['mean_margin']:+.1%}"
                f" 最大 {result['max_margin']:+.0%}"
                f" / 正解長は他の平均の {result['mean_ratio']:.2f} 倍"
                f" / 最長だった問題 {result['longest']}（参考）"
            )
        if ms["n"]:
            parts.append(
                f"MS {ms['n']}問"
                f" / margin 平均 {ms['mean_margin']:+.1%}"
                f" 最大 {ms['max_margin']:+.0%}"
                f" / 正解肢が全部最長 {ms['all_correct_longest']}問（参考）"
            )
        head = f"{target}: " + " | ".join(parts)

        if errs:
            failed = True
            print(f"FAIL {head}")
            for e in errs[:20]:
                print(f"  - {e}")
            if len(errs) > 20:
                print(f"  ... 他 {len(errs) - 20} 件")
        else:
            print(f"OK   {head}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
