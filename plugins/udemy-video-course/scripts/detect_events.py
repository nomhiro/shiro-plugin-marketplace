# -*- coding: utf-8 -*-
"""録画から「画面が変化した瞬間」を秒単位で列挙する（境界を実操作に合わせるため）。

make-practice-movie の `analyze` が出す等間隔フレーム（既定60枚＝十数秒間隔）だけで
区切りを決めると、境界が実際の操作より 1〜3 秒後ろにずれ、視聴時に
「音声が少し遅れている」と感じられる。本スクリプトは録画を 4fps で走査して
フレーム間差分の立ち上がり（＝操作が起きた瞬間）を列挙し、その時刻を境界候補にする。

使い方:
    python detect_events.py <rec_norm.mp4> [--fps 4] [--min-gap 0.75] [--thr 1.2]
    python detect_events.py <rec_norm.mp4> --json events.json
    python detect_events.py <rec_norm.mp4> --near 92.5,131.0   # 指定時刻の最近傍イベントを表示

出力: 時刻(秒) / 変化量 ALL / 帯ごとの変化量。変化量が大きいほど大きな画面遷移
（ブラウザ↔エディタの切替は ALL 13〜30、スクロールや選択は 2〜5 程度）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

import numpy as np

W, H = 1280, 720
# 画面を横帯に分割して、どこが変化したかを併せて出す（層の判別用）
BANDS = {
    "top": (0, 70),        # タブ・タイトルバー
    "editor": (70, 418),   # エディタ本文
    "mid": (418, 445),     # 区切り
    "term": (445, 700),    # ターミナル
    "bottom": (700, 720),  # ステータスバー
}


def probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def read_gray_frames(path: str, fps: float):
    """録画を fps で間引き、グレースケール 1280x720 の生フレームを順に返す。"""
    cmd = [
        "ffmpeg", "-v", "error", "-i", path,
        "-vf", f"fps={fps},scale={W}:{H},format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = W * H
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(H, W)
    finally:
        proc.stdout.close()
        proc.wait()


def detect(path: str, fps: float, thr: float, min_gap: float, x0: int, x1: int):
    """フレーム間差分の立ち上がりを検出して (時刻, ALL, 帯別) のリストを返す。"""
    prev = None
    series = []  # (t, all_diff, {band: diff})
    for i, fr in enumerate(read_gray_frames(path, fps)):
        crop = fr[:, x0:x1].astype(np.int16)
        if prev is not None:
            d = np.abs(crop - prev)
            allv = float(d.mean())
            bands = {}
            for name, (ya, yb) in BANDS.items():
                bands[name] = float(d[ya:yb, :].mean())
            series.append((i / fps, allv, bands))
        prev = crop

    # 立ち上がり検出: 閾値超え、かつ直前 min_gap 秒が静止していたら「イベント開始」
    quiet_frames = max(1, int(round(min_gap * fps)))
    events = []
    for idx, (t, allv, bands) in enumerate(series):
        if allv < thr:
            continue
        lo = max(0, idx - quiet_frames)
        window = series[lo:idx]
        if window and max(w[1] for w in window) >= thr:
            continue  # 直前も動いている＝継続中なので開始ではない
        events.append({"t": round(t, 2), "all": round(allv, 2),
                       "bands": {k: round(v, 2) for k, v in bands.items()}})
    return series, events


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--thr", type=float, default=1.2, help="変化とみなす差分の閾値")
    ap.add_argument("--min-gap", type=float, default=0.75, help="直前これだけ静止していたら開始とみなす")
    ap.add_argument("--x0", type=int, default=300, help="走査する x 範囲の左端（左のサイドバーを除外）")
    ap.add_argument("--x1", type=int, default=1140, help="走査する x 範囲の右端（右のミニマップを除外）")
    ap.add_argument("--json", help="イベントを JSON で書き出す")
    ap.add_argument("--near", help="カンマ区切りの時刻。各時刻の最近傍イベントを表示する")
    ap.add_argument("--min-all", type=float, default=0.0, help="この変化量未満のイベントは表示しない")
    args = ap.parse_args()

    dur = probe_duration(args.video)
    series, events = detect(args.video, args.fps, args.thr, args.min_gap, args.x0, args.x1)
    shown = [e for e in events if e["all"] >= args.min_all]

    print(f"# {args.video}")
    print(f"# duration={dur:.1f}s  fps={args.fps}  検出イベント={len(events)}件"
          f"（表示 {len(shown)}件, min-all={args.min_all}）")

    if args.near:
        want = [float(x) for x in args.near.split(",")]
        print("\n## 指定時刻の最近傍イベント")
        for w in want:
            if not events:
                break
            best = min(events, key=lambda e: abs(e["t"] - w))
            delta = best["t"] - w
            print(f"  {w:8.2f}s -> {best['t']:8.2f}s (Δ{delta:+.2f}s) ALL={best['all']:6.2f}")
    else:
        print("\n#     時刻      ALL   top  editor    term")
        for e in shown:
            b = e["bands"]
            mm, ss = divmod(e["t"], 60)
            print(f"  {int(mm):02d}:{ss:05.2f} {e['t']:8.2f} {e['all']:7.2f} "
                  f"{b['top']:6.2f} {b['editor']:7.2f} {b['term']:7.2f}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"video": args.video, "duration": dur, "fps": args.fps,
                       "events": events}, f, ensure_ascii=False, indent=1)
        print(f"\n-> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
