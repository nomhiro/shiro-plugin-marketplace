#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""座学 MP4 から「画が動かない区間」を、フレームを実際に比べて測る。

**なぜ画素で測るか（実測）**: 強調が動く間隔を「尺 ÷ (きっかけの数 + 1)」で見積もると、
全体の 96.5% が20秒以内に見えた。しかしきっかけは語りの前や後ろに固まるので、MP4 を比べると
**20秒を超えて静止するスライドが 242枚（45本）** あった。見積もりで実体を推測しない。

判定：2fps・320x180・グレーで復号し、隣り合うフレームで「値が12以上違う画素」が4個未満なら静止。
スライドの境目は `<basename>_audio/speech_NN.wav` の実尺 + lead/tail（既定 1+2 秒）から出す
（lecture_movie.py の既定の「間」）。表紙（先頭のスライド）は語りだけで動かないのが正常なので、
`--skip-first` 枚（既定 1）を集計から外す。

    python still_report.py lectures/01_x/L1-1-1_xxx.mp4        # 1本（スライドごとに表示）
    python still_report.py "lectures/*/*.mp4" --threshold 30 --details

終了コード: 常に 0（ゲートではなく実測の報告。cue の無い要素が残っていれば足す材料にする）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
W, H, FPS = 320, 180, 2
PIX_DELTA, PIX_COUNT = 12, 4


def _diffs(mp4: str):
    import numpy as np
    cmd = [FFMPEG, "-v", "error", "-i", mp4, "-vf", f"fps={FPS},scale={W}:{H},format=gray",
           "-f", "rawvideo", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size, prev = W * H, None
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        cur = np.frombuffer(buf, dtype=np.uint8).astype(np.int16)
        yield None if prev is None else int((np.abs(cur - prev) >= PIX_DELTA).sum())
        prev = cur
    p.wait()


def slide_bounds(mp4: str, lead_tail: float = 3.0) -> list[tuple[int, float, float]]:
    """[(スライドの通し番号, 開始秒, 終了秒)]。音声フォルダが無ければ空。"""
    base = mp4[:-4]
    bounds, t = [], 0.0
    for w in sorted(glob.glob(base + "_audio/speech_*.wav")):
        with wave.open(w) as f:
            d = f.getnframes() / f.getframerate() + lead_tail
        bounds.append((int(os.path.basename(w)[7:-4]), t, t + d))
        t += d
    return bounds


def longest_still(moving: list[bool | None], bounds: list[tuple[int, float, float]],
                  fps: int = FPS) -> list[dict]:
    """スライドごとの最長の静止秒数。moving[i] はフレーム i が前のフレームから動いたか。"""
    res = []
    for sid, a, b in bounds:
        i0, i1 = int(a * fps) + 1, min(int(b * fps), len(moving))
        best = cur = best_at = cur_at = 0
        for i in range(i0, i1):
            if moving[i]:
                cur = 0
                continue
            if cur == 0:
                cur_at = i
            cur += 1
            if cur > best:
                best, best_at = cur, cur_at
        res.append({"slide": sid, "dur": round(b - a, 1), "still": round(best / fps, 1),
                    "at": round(best_at / fps - a, 1)})
    return res


def measure(mp4: str, lead_tail: float = 3.0) -> list[dict]:
    bounds = slide_bounds(mp4, lead_tail)
    moving = [None] + [(d is not None and d >= PIX_COUNT) for d in _diffs(mp4)]
    return longest_still(moving, bounds)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mp4", nargs="+", help="座学の完成 MP4（グロブ可）")
    ap.add_argument("--threshold", type=float, default=20.0, help="これを超える静止を数える（秒）")
    ap.add_argument("--lead-tail", type=float, default=3.0, help="スライドごとの lead + tail（秒）")
    ap.add_argument("--skip-first", type=int, default=1, help="集計から外す先頭のスライド数（表紙）")
    ap.add_argument("--details", action="store_true", help="超えたスライドを1件ずつ出す")
    ap.add_argument("--json", help="結果を JSON で書き出す")
    a = ap.parse_args(argv)

    paths = [p for pat in a.mp4 for p in (sorted(glob.glob(pat)) or [pat])
             if not p.endswith("_rec.mp4")]
    out, over = {}, []
    for p in paths:
        name = Path(p).stem
        rows = measure(p, a.lead_tail)
        if not rows:
            print(f"  ! {name}: 音声フォルダ（{Path(p).stem}_audio/speech_*.wav）が無いので測れません")
            continue
        out[name] = rows
        for r in rows[a.skip_first:]:
            if r["still"] > a.threshold:
                over.append((name, r))
        if len(paths) == 1:
            for r in rows:
                print(f"  s{r['slide']:>2} dur={r['dur']:>6} 最長の静止={r['still']:>5}s（スライド内 +{r['at']}s から）")
    n_slides = sum(max(0, len(rows) - a.skip_first) for rows in out.values())
    print(f"{len(out)} 本 / 表紙を除く {n_slides} スライド")
    print(f"{a.threshold:g} 秒を超えて静止するスライド: {len(over)} 枚（{len({n for n, _ in over})} 本）")
    if a.details:
        for name, r in sorted(over, key=lambda x: -x[1]["still"]):
            print(f"  {r['still']:>6.1f}s  {name} s{r['slide']} (尺 {r['dur']}s, +{r['at']}s から)")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
