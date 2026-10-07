#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""レンダの後に、強調のきっかけ（cue）が**音声**とどれだけ照合できたかを全数集計する。

講座側で「台本の一節（cue）を音声の書き起こしと照合して、強調を出す時刻を決める」同期を
使っているときの検査。入力は音声フォルダの `_timing.json`（形式は下）。

**なぜ全数集計が要るか（実測）**: 照合できなかった cue は前後の中点で補間される。警告は
`! cue N件を補間` の1行だけで、1本ずつ流すとログの奥に流れて残らない。全本を作り終えてから
数えたところ、3,206件のうち64件（2.0%）が補間で、強調が実際の語りから最大26秒ずれていた。
**1本ずつの警告ではなく、最後に分母つきで数える。** まとまって落ちたスライドが本当の欠陥。

`_timing.json` の形式（この形で書き出せば、どの同期の実装でも使える）:
    {"slides": {"<スライド番号>": {
        "cues": [{"cue": "<台本の一節>", "start": <秒>, "matched": true, "approx": false}, ...],
        "sentences": [{"text": "<書き起こしの文>", "start": <秒>}, ...]}}}
  matched=false は補間に落ちたもの。approx=true は近似一致（cue_drift.py で位置を確かめる）。

    python cue_report.py "lectures/*/*_audio/_timing.json"
    python cue_report.py "lectures/*/*_audio/_timing.json" --details

終了コード: 補間に落ちた cue が1件でもあれば 1（読めないファイルも 1）。
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def collect(paths: list[Path]) -> list[dict]:
    """`_timing.json` を読み、ファイル（＝レクチャー）単位に集計する。"""
    rows: list[dict] = []
    for tj in sorted(paths):
        name = tj.parent.name.removesuffix("_audio")
        try:
            doc = json.loads(tj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            rows.append({"name": name, "total": 0, "unmatched": [], "approx": 0, "error": str(exc)})
            continue
        total, approx, unmatched = 0, 0, []
        # スライド番号は文字列キーなので数値として並べ替える（10 が 2 より先に来ないように）
        for sid in sorted((doc.get("slides") or {}), key=lambda s: int(s)):
            for cue in (doc["slides"][sid].get("cues") or []):
                total += 1
                if not cue.get("matched"):
                    unmatched.append({"slide": int(sid), "cue": cue.get("cue", ""), "start": cue.get("start")})
                elif cue.get("approx"):
                    approx += 1
        rows.append({"name": name, "total": total, "unmatched": unmatched, "approx": approx})
    return rows


def format_report(rows: list[dict], details: bool = False) -> str:
    total = sum(r["total"] for r in rows)
    bad = sum(len(r["unmatched"]) for r in rows)
    approx = sum(r.get("approx", 0) for r in rows)
    lines = [f"cue の照合（音声）: {total} 件中 {total - bad} 件が一致（うち近似 {approx} 件）／補間 {bad} 件"
             + (f"（{bad / total * 100:.1f}%）" if total else "")]
    lines.append(f"レクチャー: {len(rows)} 本／補間を含む {sum(1 for r in rows if r['unmatched'])} 本")
    for r in rows:
        if r.get("error"):
            lines.append(f"  ! {r['name']}: 読めません（{r['error']}）")
            continue
        if not r["unmatched"]:
            continue
        lines.append(f"  {r['name']}: 補間 {len(r['unmatched'])} / {r['total']} 件")
        if details:
            for u in r["unmatched"]:
                lines.append(f"      スライド{u['slide']}: {u['cue']}（補間 {u['start']}s）")
    if not bad:
        lines.append("補間に落ちた cue はありません。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("timing", nargs="+", help="_timing.json（グロブ可）")
    ap.add_argument("--details", action="store_true", help="補間に落ちた cue を1件ずつ出す")
    a = ap.parse_args(argv)
    paths = [Path(p) for pat in a.timing for p in (sorted(glob.glob(pat)) or [pat]) if Path(p).exists()]
    if not paths:
        print("_timing.json が見つかりません")
        return 1
    rows = collect(paths)
    print(format_report(rows, a.details))
    return 1 if any(r["unmatched"] or r.get("error") for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
