#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完成 MP4 から「見出しだけで本体が空」の区間を画素で探す。

1秒ごとに 320x180 のグレースケールで切り出し、見出しの帯（既定は上 22%）より下で、
背景（中央値）から大きく外れた画素の割合（インク）を測る。インクが --min-ink 未満の秒が
--run 秒以上続いた区間を出す。

なぜ画素で測るか（実測）: 図の要素を話の順に出すスライドで、最初の要素が出るまでの間
見出ししか映らない時間が16秒続いた。台本やスライドの定義から秒数を推定する方法は入れ子の
段階表示を読み違えるので、完成した絵そのものを測る。**承認済みの3本にも空白が見つかった**ので、
検出器を作ったら承認済みの全本にさかのぼって回す。

    python empty_frames.py lectures/*/L1-*.mp4
    python empty_frames.py out.mp4 --header 0.18 --run 8

終了コード: 空の区間が1つでもあれば 1（ゲート）。読めない mp4 は 2。
"""
from __future__ import annotations

import argparse
import glob
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
W, H = 320, 180


def ink_per_second(mp4: str, header: float = 0.22) -> list[float]:
    import numpy as np
    cmd = [FFMPEG, "-v", "error", "-i", mp4, "-vf", f"fps=1,scale={W}:{H},format=gray",
           "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, H, W)
    body = frames[:, int(H * header):int(H * 0.95), int(W * 0.03):int(W * 0.97)].astype(np.int16)
    bg = np.median(body.reshape(len(body), -1), axis=1)[:, None, None]
    return [float(x) for x in (np.abs(body - bg) > 40).mean(axis=(1, 2))]


def empty_runs(ink: list[float], min_ink: float = 0.004, run: int = 10) -> list[tuple[int, int]]:
    """インクが min_ink 未満の秒が run 秒以上続く区間 [(開始秒, 終了秒)]。"""
    runs, start = [], None
    for i, v in enumerate(list(ink) + [1.0]):
        if v < min_ink and start is None:
            start = i
        elif v >= min_ink and start is not None:
            if i - start >= run:
                runs.append((start, i))
            start = None
    return runs


def expand(patterns: list[str]) -> list[str]:
    out: list[str] = []
    for p in patterns:
        out += sorted(glob.glob(p)) or [p]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mp4", nargs="+", help="完成 MP4（グロブ可）")
    ap.add_argument("--header", type=float, default=0.22, help="見出しの帯の高さ（画面の割合）")
    ap.add_argument("--min-ink", type=float, default=0.004, help="これ未満を「空」とみなすインクの割合")
    ap.add_argument("--run", type=int, default=10, help="何秒続いたら数えるか")
    ap.add_argument("--exclude", nargs="*", default=["_rec.mp4"], help="除外する末尾（素材の録画など）")
    a = ap.parse_args(argv)
    rc = 0
    for mp4 in expand(a.mp4):
        if any(mp4.endswith(x) for x in a.exclude):
            continue
        try:
            runs = empty_runs(ink_per_second(mp4, a.header), a.min_ink, a.run)
        except (subprocess.CalledProcessError, ValueError) as e:
            print(f"{mp4}: 読めません（{e}）")
            rc = max(rc, 2)
            continue
        out = ", ".join(f"{s}〜{e}s（{e - s}秒）" for s, e in runs) or "なし"
        print(f"{mp4}: 空の区間 {out}")
        if runs:
            rc = max(rc, 1)
    return rc


if __name__ == "__main__":
    sys.exit(main())
