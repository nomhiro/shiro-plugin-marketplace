"""問う中身が細かすぎる問題（上限値・課金・API の版など）を拾う。

入門・中級の認定試験は、公式の練習評価を見ると「用途 → 機能名・サービス名」
「要件 → 何を使うか」が中心で、件数の上限や API の版、課金の規則は正解の争点に
ならない。ところが作問エージェントは、既出の論点を避けようとすると周辺の細部
（上限値・例外規則・課金）へ流れる。

> 実績: ある講座のフル模試3本で、差し戻した問題の多くが「〜件まで」「〜枚」
> 「FPS」「課金」「api-version」「ロール名」を正解の争点にしていた。
> 形式・文体・重複の検査はすべて通っていたので、機械では止まらなかった。

**問題文と正解肢だけを見る**（解説は見ない）。解説に上限値が書いてあるのは
補足として正当だが、答えがそれで決まるなら細かすぎる。

既定は WARN（exit 0）。front matter の `granularity` で調整できる:

    granularity:
      severity: warn            # warn（既定）| fail
      patterns: ["プレビュー API"]   # 追加で拾う正規表現
      allow: ["temperature は 0 から 2"]  # これを含む問題は拾わない（学習ガイド直結の数値など）

使い方:
    python check_granularity.py <quiz.csv> [...] [--sections sections.md]
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

UNITS = r"(?:件|枚|個|文字|トークン|秒|分|時間|日|ページ|言語|回|MB|GB|KB|fps|FPS|px|ピクセル)"
DEFAULT_PATTERNS = (
    # 数値の上限・下限で答えが決まる
    rf"\d[\d,]*\s*{UNITS}\s*(?:まで|以内|以下|未満|を超え|が上限|が最大)",
    r"(?:上限|最大)(?:は|が|で)?\s*\d",
    r"\d[\d,]*\s*" + UNITS + r"\s*(?:の上限|の制限)",
    # API の版・課金
    r"api-version|API バージョン|API の版",
    r"課金|料金体系|従量課金|価格レベル",
)


def granularity_config(profile: dict | None) -> dict:
    cfg = (profile or {}).get("granularity") or {}
    return {
        "severity": str(cfg.get("severity") or "warn"),
        "patterns": [re.compile(p) for p in (*DEFAULT_PATTERNS, *(cfg.get("patterns") or []))],
        "allow": [str(a) for a in (cfg.get("allow") or [])],
    }


def scan(path, cfg: dict) -> list[str]:
    out: list[str] = []
    for i, row in enumerate(read_rows(path)[1:], 1):
        if len(row) != 17:
            continue
        correct = {int(c) for c in correct_indices(row[14]) if c.isdigit()}
        targets = [("問題文", row[0])] + [
            (f"正解肢{k}", row[opt]) for k, (opt, _) in enumerate(OPTION_PAIRS, 1)
            if k in correct and row[opt].strip()
        ]
        joined = " ".join(t for _, t in targets)
        if any(a in joined for a in cfg["allow"]):
            continue
        for where, text in targets:
            hit = next((m for p in cfg["patterns"] if (m := p.search(text))), None)
            if hit:
                s = max(0, hit.start() - 15)
                out.append(
                    f"Q{i} {where}: 「…{text[s:hit.end() + 15]}…」"
                    " - 上限値・課金・API の版などの細部が答えを決めていないか確かめる"
                )
                break
    return out


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="細かすぎる問題（上限値・課金・API の版）を拾う")
    ap.add_argument("csv_paths", nargs="+")
    ap.add_argument("--sections", default=None)
    a = ap.parse_args(argv[1:])
    profile = None
    if a.sections and Path(a.sections).exists():
        from scripts.profile import load_profile
        profile = load_profile(a.sections)
    cfg = granularity_config(profile)

    failed = False
    for target in a.csv_paths:
        hits = scan(target, cfg)
        if not hits:
            print(f"OK   {target}: 細部を問う問題は見つからない")
            continue
        label = "FAIL" if cfg["severity"] == "fail" else "WARN"
        failed = failed or label == "FAIL"
        print(f"{label} {target}: 細部を問う疑いのある問題 {len(hits)} 件")
        for h in hits:
            print(f"  - {h}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
