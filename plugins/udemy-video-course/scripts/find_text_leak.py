# -*- coding: utf-8 -*-
"""録画の中で「特定の文字列画像（テンプレート）が映っているフレーム」を全編から探す。

用途：個人情報の映り込み点検。メールアドレス・アカウント名・実名などは
ターミナル出力やポータル画面に不意に現れる。彩度や輝度の変化では見つからない
（文字は小さく、画面全体の統計に埋もれる）ため、**現れている1枚からテンプレートを
切り出し、それを全編に照合する**のが確実。

テンプレートの作り方（現れている時刻が1つ分かっている前提）:
    ffmpeg -ss <秒> -i rec_norm.mp4 -frames:v 1 -vf "crop=W:H:X:Y" tpl.png

使い方:
    python find_text_leak.py rec_norm.mp4 tpl.png [--fps 1] [--thr 0.75]
                             [--region x0,y0,x1,y1] [--json hits.json]

出力: ヒットした時刻・相関値・位置。連続するヒットは区間としてまとめて表示する
（その区間が drawbox/boxblur で隠す対象になる）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

import numpy as np
from scipy.signal import fftconvolve

W, H = 1920, 1080


def probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def gray_frames(path: str, fps: float, w: int, h: int):
    cmd = ["ffmpeg", "-v", "error", "-i", path,
           "-vf", f"fps={fps},scale={w}:{h},format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = w * h
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w)
    finally:
        proc.stdout.close()
        proc.wait()


def load_template(path: str) -> np.ndarray:
    """PNG をグレースケール配列で読む（PIL 使用）。"""
    from PIL import Image
    return np.asarray(Image.open(path).convert("L"), dtype=np.float64)


def ncc(img: np.ndarray, tpl: np.ndarray):
    """正規化相互相関。戻り値は (スコア配列, 最大値, 最大位置)。"""
    t = tpl - tpl.mean()
    t_norm = np.sqrt((t * t).sum())
    if t_norm == 0:
        return None, 0.0, (0, 0)
    th, tw = tpl.shape
    ones = np.ones_like(tpl)
    # 相関（テンプレートを反転して畳み込む）
    num = fftconvolve(img, t[::-1, ::-1], mode="valid")
    s1 = fftconvolve(img, ones[::-1, ::-1], mode="valid")
    s2 = fftconvolve(img * img, ones[::-1, ::-1], mode="valid")
    n = th * tw
    var = s2 - (s1 * s1) / n
    var[var < 1e-9] = 1e-9
    denom = np.sqrt(var) * t_norm
    score = num / denom
    idx = int(np.argmax(score))
    y, x = divmod(idx, score.shape[1])
    return score, float(score[y, x]), (x, y)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("template")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--thr", type=float, default=0.75, help="相関の閾値（0〜1）")
    ap.add_argument("--region", default=None,
                    help="探索範囲 x0,y0,x1,y1（既定は全画面）")
    ap.add_argument("--merge-gap", type=float, default=3.0,
                    help="この秒数以内のヒットは1区間にまとめる")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    tpl = load_template(args.template)
    dur = probe_duration(args.video)
    if args.region:
        x0, y0, x1, y1 = (int(v) for v in args.region.split(","))
    else:
        x0, y0, x1, y1 = 0, 0, W, H

    print(f"# {args.video}")
    print(f"# template {args.template} {tpl.shape[1]}x{tpl.shape[0]} / "
          f"region ({x0},{y0})-({x1},{y1}) / fps={args.fps} / thr={args.thr}")

    hits = []
    for i, fr in enumerate(gray_frames(args.video, args.fps, W, H)):
        t = i / args.fps
        sub = fr[y0:y1, x0:x1].astype(np.float64)
        if sub.shape[0] < tpl.shape[0] or sub.shape[1] < tpl.shape[1]:
            continue
        _, best, (bx, by) = ncc(sub, tpl)
        if best >= args.thr:
            hits.append({"t": round(t, 2), "score": round(best, 3),
                         "x": x0 + bx, "y": y0 + by})

    print(f"# ヒット {len(hits)} フレーム / 走査 {dur:.0f}s")
    spans = []
    for h in hits:
        if spans and h["t"] - spans[-1]["end"] <= args.merge_gap:
            spans[-1]["end"] = h["t"]
            spans[-1]["n"] += 1
            spans[-1]["max"] = max(spans[-1]["max"], h["score"])
        else:
            spans.append({"start": h["t"], "end": h["t"], "n": 1,
                          "max": h["score"], "x": h["x"], "y": h["y"]})

    print(f"\n## 映り込み区間 {len(spans)} 件（drawbox/boxblur の対象）")
    for s in spans:
        a, b = s["start"], s["end"]
        print(f"  {int(a)//60:02d}:{a%60:05.2f} - {int(b)//60:02d}:{b%60:05.2f}"
              f"  ({b - a + 1 / args.fps:5.1f}s, {s['n']}枚, 相関{s['max']:.3f})"
              f"  位置 x={s['x']} y={s['y']}")
        print(f"     enable='between(t,{max(0, a - 1):.2f},{b + 1:.2f})'")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"video": args.video, "template": args.template,
                       "hits": hits, "spans": spans}, f, ensure_ascii=False, indent=1)
        print(f"\n-> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
