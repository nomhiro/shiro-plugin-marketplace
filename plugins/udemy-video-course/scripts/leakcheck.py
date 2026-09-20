# -*- coding: utf-8 -*-
"""完成動画を走査して「映り込みの疑いがある区間」を挙げる（彩度ベース）。

個人情報や無関係な画面は、**輝度の変化では見つからない**。タスクバーのウィンドウ
プレビューやポップアップは輝度差が小さく、画面全体の統計に埋もれる。

一方、開発画面（エディタ・ターミナル・ポータル）は**ほぼ無彩色**なので、
彩度（max(RGB) - min(RGB)）の高い画素の割合を見ると、写真サムネイル・アイコン・
色付きのオーバーレイだけが際立つ。まずこれで「見るべき区間」を絞り、目視する。

`find_text_leak.py` との使い分け:
  - leakcheck   … **何が映ったか分からない**ときに、怪しい区間を洗い出す（探索）
  - find_text_leak … **消したい文字列が1枚分かっている**ときに全編から探す（照合）

使い方:
    python leakcheck.py movie.mp4
    python leakcheck.py movie.mp4 --fps 2 --sat 60 --ratio 0.02
    python leakcheck.py movie.mp4 --json hits.json

出力された区間は**必ず目視する**。タイトルスライドや色付きの図は正当なヒットで、
その場合は「正当」と判断して先に進む（ゼロにはならない）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np


def sample(path: Path, fps: float, w: int, h: int) -> np.ndarray:
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True)
    if p.returncode != 0:
        raise SystemExit(p.stderr.decode("utf-8", "replace")[-500:])
    buf = np.frombuffer(p.stdout, dtype=np.uint8)
    n = buf.size // (w * h * 3)
    if n == 0:
        raise SystemExit("フレームを取得できませんでした")
    return buf[: n * w * h * 3].reshape(n, h, w, 3).astype(np.int16)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("movie", type=Path)
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--sat", type=int, default=60, help="彩度のしきい値（既定60）")
    ap.add_argument("--ratio", type=float, default=0.02,
                    help="高彩度画素の割合がこれを超えた秒を拾う（既定0.02）")
    ap.add_argument("--size", default="320x180")
    ap.add_argument("--gap", type=int, default=2, help="この秒数まで離れていても同じ区間にまとめる")
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()

    w, h = (int(x) for x in a.size.split("x"))
    fr = sample(a.movie, a.fps, w, h)
    sat = fr.max(axis=3) - fr.min(axis=3)
    ratio = (sat > a.sat).mean(axis=(1, 2))

    runs = []
    for i, r in enumerate(ratio):
        if r <= a.ratio:
            continue
        t = i / a.fps
        if runs and t - runs[-1][1] <= a.gap:
            runs[-1][1] = t
            runs[-1][2] = max(runs[-1][2], float(r))
        else:
            runs.append([t, t, float(r)])

    def mmss(x):
        return f"{int(x) // 60:02d}:{int(x) % 60:02d}"

    print(f"■ leakcheck: {a.movie.name}（{len(ratio)}サンプル / {a.fps}fps）")
    print(f"  彩度ヒット区間: {len(runs)}")
    for s, e, r in runs:
        print(f"   {mmss(s)}-{mmss(e)}  ({e - s + 1 / a.fps:.0f}s) 最大割合={r:.3f}")
    if not runs:
        print("   （なし）")
    print("\n  ※ ヒットは必ず目視する。タイトルスライドや色付きの図は正当。")

    if a.json:
        a.json.write_text(json.dumps(
            [{"start": s, "end": e, "max_ratio": r} for s, e, r in runs],
            ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
