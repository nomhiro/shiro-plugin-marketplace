"""1セクションのシナリオ率が front matter の範囲に入っているかを検査する。

シナリオ率 = 非シナリオ型（`non_scenario_codes`。既定 `knowledge`）以外の問題の割合。
`_parts/bank-rows.md`（merge_parts.py が meta から作る）の `scenario` 列で数える。

範囲は front matter から本ごとに決まる（`profile.scenario_bounds`）。
優先順位は 本ごと（`sections[].scenario_ratio`）> 種類ごと（`scenario_ratio.<kind>`）
> 全体（`scenario_ratio_min` / `scenario_ratio_max`）。範囲の指定が無ければ SKIP。

> 実績: ある講座のフル模試1本目がシナリオ率 88% になった（下限しか無かったため
> 止まらなかった）。公式の練習評価は約 60% で、概念問題は短い定義型が中心だった。
> R3 のあとで 14 問を定義型に書き直した。

使い方:
    python check_scenario_ratio.py <section-folder> [--sections sections.md]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import safe_stdout
from scripts.profile import load_profile, resolve_section, scenario_bounds


def bank_scenarios(section: Path) -> list[str]:
    """`_parts/bank-rows.md` の scenario 列（6列目）を返す。"""
    path = section / "_parts" / "bank-rows.md"
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and cells[1].lstrip("Q").isdigit():
            out.append(cells[5])
    return out


def check(section: Path, profile: dict) -> tuple[str, str]:
    """(判定, メッセージ)。判定は OK / FAIL / SKIP。"""
    spec = resolve_section(profile, section.name)
    lo, hi = scenario_bounds(profile, spec)
    scen = bank_scenarios(section)
    if not scen:
        return "SKIP", f"{section.name}: bank-rows.md に行がない"
    non_codes = {str(x).strip() for x in (profile.get("non_scenario_codes") or ["knowledge"])}
    dist = Counter(scen)
    non = sum(n for s, n in dist.items() if s in non_codes)
    ratio = (len(scen) - non) / len(scen)
    head = (
        f"{section.name}: シナリオ率 {ratio:.1%}（{len(scen) - non}/{len(scen)}・"
        f"非シナリオ型 {non}）"
    )
    if lo is None and hi is None:
        return "SKIP", f"{head} / 範囲の指定なし"
    rng = f"{'' if lo is None else f'{lo:.0%}'}〜{'' if hi is None else f'{hi:.0%}'}"
    if lo is not None and ratio < lo:
        return "FAIL", f"{head} が下限を下回る（範囲 {rng}）- 概念問題の一部を業務場面のシナリオにする"
    if hi is not None and ratio > hi:
        return "FAIL", (
            f"{head} が上限を上回る（範囲 {rng}）"
            " - 概念問題を業種の設定の無い1〜2文の定義型にし、meta の scenario 列を非シナリオ型にする"
        )
    return "OK", f"{head} / 範囲 {rng}"


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="1セクションのシナリオ率を範囲で検査する")
    ap.add_argument("section")
    ap.add_argument("--sections", default="sections.md")
    a = ap.parse_args(argv[1:])
    profile = load_profile(a.sections)
    verdict, msg = check(Path(a.section), profile)
    print(f"{verdict:<4} {msg}")
    return 1 if verdict == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
