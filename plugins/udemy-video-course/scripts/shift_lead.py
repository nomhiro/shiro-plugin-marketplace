# -*- coding: utf-8 -*-
"""台本の区間境界を前倒しして、ナレーションが画面変化を「先導」するようにする。

境界を実操作（画面が変化した瞬間）にぴったり合わせると、ナレーションと変化が
**同時**になる。これは視聴時に「ナレーションが遅れている」と感じられる。理由:

- 視聴者はまず画面変化に気づき、そのあとで音声を聞き始める（知覚の順序）
- 日本語のナレーションは「続いて」「次に」などの接続語で始まることが多く、
  肝心の情報（何をしているか）が文頭から1〜2秒後に来る

そこで各区間の開始を target 秒だけ前倒しし、ナレーションが画面変化より先に
始まるようにする。前倒し量は**直前区間の余白（沈黙）**で上限を切る
（直前のナレーションを切らないため）。

本文は変えないので **再TTSは発生しない**（manifest は本文ハッシュで判定）。
タイムコードだけ変わるので build は動画の組み直しだけで済む。

使い方:
    python shift_lead.py <basename>_transcript_rec.md <audio_rec_dir> [--target 1.8]
                         [--margin 0.3] [--apply]
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

REC = re.compile(
    r'^(##\s*録画\s*(\d+)\s*\[)(\d+):(\d+(?:\.\d+)?)-(\d+):(\d+(?:\.\d+)?)(\]\s*[:：].*)$'
)


def wav_dur(path: pathlib.Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def mmss(t: float) -> str:
    t = round(t, 2)  # 59.996 を「00:60.00」と書かないよう、先に丸めてから分と秒に分ける
    return f"{int(t) // 60:02d}:{t % 60:05.2f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("audio_dir")
    ap.add_argument("--target", type=float, default=1.8,
                    help="ナレーションを画面変化より何秒先行させたいか")
    ap.add_argument("--margin", type=float, default=0.3,
                    help="直前区間の末尾に必ず残す無音")
    ap.add_argument("--apply", action="store_true", help="ファイルを書き換える")
    ap.add_argument("--cross-cut", action="store_true",
                    help="カット（区間の切れ目）をまたぐ前倒しも許可する。"
                         "⚠️ カットには個人情報の映り込みを消した区間が含まれることがあるので、"
                         "またぐ前に必ずその数秒のフレームを目視確認すること")
    args = ap.parse_args()

    p = pathlib.Path(args.transcript)
    lines = p.read_text(encoding="utf-8").split("\n")
    adir = pathlib.Path(args.audio_dir)

    # 区間を拾う
    segs = []  # (line_index, n, start, end, prefix, suffix)
    for i, ln in enumerate(lines):
        m = REC.match(ln)
        if m:
            s = int(m.group(3)) * 60 + float(m.group(4))
            e = int(m.group(5)) * 60 + float(m.group(6))
            segs.append({"i": i, "n": int(m.group(2)), "s": s, "e": e,
                         "pre": m.group(1), "suf": m.group(7)})
    if not segs:
        print("録画区間が見つかりません")
        return 1

    # 各区間の wav 実尺
    for sg in segs:
        sg["wav"] = wav_dur(adir / f"rec_{sg['n']:02d}.wav")

    # 境界 i（区間 i の開始 = 区間 i-1 の終了）を前倒しする
    shifts = [0.0] * len(segs)
    cut_skipped = []
    for k in range(1, len(segs)):
        prev = segs[k - 1]
        # 直前区間の終了と当区間の開始が離れている＝カット（意図的に落とした区間）
        is_after_cut = segs[k]["s"] - prev["e"] > 0.5
        if is_after_cut and not args.cross_cut:
            cut_skipped.append(segs[k]["n"])
            continue
        prev_len = prev["e"] - prev["s"]
        slack = prev_len - prev["wav"] - args.margin
        if is_after_cut:
            # カットをまたぐ場合、直前区間は短くならないので target をそのまま使える
            shifts[k] = args.target
        else:
            shifts[k] = max(0.0, min(args.target, slack))

    print(f"# {p.name}  target={args.target}s margin={args.margin}s")
    print(f"{'区間':>4} {'旧開始':>9} {'新開始':>9} {'前倒し':>6} "
          f"{'直前の余白':>9} {'新尺':>6} {'直前新尺':>8}")
    applied = 0
    for k, sg in enumerate(segs):
        new_s = sg["s"] - shifts[k]
        new_e = sg["e"] - (shifts[k + 1] if k + 1 < len(segs) else 0.0)
        prev_new = None
        if k > 0:
            prev_new = (segs[k - 1]["e"] - shifts[k]) - (segs[k - 1]["s"] - shifts[k - 1])
        slack = ""
        if k > 0:
            pl = segs[k - 1]["e"] - segs[k - 1]["s"]
            slack = f"{pl - segs[k - 1]['wav']:8.1f}"
        if shifts[k] > 0:
            applied += 1
        print(f"{sg['n']:>4} {mmss(sg['s']):>9} {mmss(new_s):>9} "
              f"{shifts[k]:6.2f} {slack:>9} {new_e - new_s:6.1f} "
              f"{(f'{prev_new:8.1f}' if prev_new is not None else ''):>8}")
        sg["new_s"] = new_s
        sg["new_e"] = new_e

    # 短くなりすぎる区間がないか（ナレーションが入らない）
    bad = [sg for sg in segs if sg["new_e"] - sg["new_s"] < sg["wav"] + 0.1]
    if bad:
        print("\n⚠️ 前倒しで wav が入らなくなる区間:")
        for sg in bad:
            print(f"   録画{sg['n']}: 新尺 {sg['new_e'] - sg['new_s']:.1f}s < wav {sg['wav']:.1f}s")

    if cut_skipped:
        print(f"\nカットの直後なので前倒しを見送った区間: {cut_skipped}")
        print("  （--cross-cut で許可できるが、カットした数秒に個人情報や"
              "説明していないエラーが映っていないか必ず目視確認すること）")
    print(f"\n前倒しした境界 {applied}/{len(segs) - 1}")
    if not args.apply:
        print("（--apply を付けると書き換えます）")
        return 0

    for sg in segs:
        s, e = sg["new_s"], sg["new_e"]
        s, e = round(s, 2), round(e, 2)
        lines[sg["i"]] = (f"{sg['pre']}{int(s) // 60:02d}:{s % 60:05.2f}-"
                          f"{int(e) // 60:02d}:{e % 60:05.2f}{sg['suf']}")
    p.write_text("\n".join(lines), encoding="utf-8")
    print(f"-> 書き換えました: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
