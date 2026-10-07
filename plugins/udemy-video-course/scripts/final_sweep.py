#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完成 MP4（座学・実践）を1本ずつ機械で通し検査して、1枚の表にする。公開前に全本へ回す。

再生して目で追う代わりの、数える検査。次の6つを全本に対して行う。

  1. 仕様      既定 1920x1080 / 30fps / h264 yuv420p / aac 48kHz ステレオ か
  2. 尺の整合  映像と音声のストリーム長の差（0.25秒以内）／`<basename>_audio/speech_*.wav` があれば、
               その実尺の合計 + lead/tail × 枚数との差（1.5秒以内）
  3. 音量      ebur128 の統合ラウドネス（LUFS）。全本の中央値から ±1 LU 以内か／True Peak
  4. 無音      silencedetect（-45dB・1秒以上）の最長と合計（報告だけ）
  5. 黒        blackdetect（0.5秒以上）。意図しない黒の検出
  6. cue 照合  `<basename>_audio/_timing.json` があれば、補間に落ちた cue の数（cue_report.py と同じ形式）

    python final_sweep.py "lectures/*/*.mp4"
    python final_sweep.py "lectures/*/*.mp4" --md sweep.md --json sweep.json

`_rec.mp4`（素材の録画）と `--exclude` に当たるものは対象外。
終了コード: 異常が1件でもあれば 1。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import wave

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
SPEC = ("1920x1080", "30/1", "h264", "yuv420p", "aac", "48000", 2)


def probe(p: str) -> dict:
    j = json.loads(subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,sample_rate,channels,duration"
         ":format=duration", "-of", "json", p]))
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), {})
    return {"spec": (f'{v.get("width")}x{v.get("height")}', v.get("r_frame_rate"), v.get("codec_name"),
                     v.get("pix_fmt"), a.get("codec_name"), a.get("sample_rate"), a.get("channels")),
            "v_s": float(v.get("duration") or 0), "a_s": float(a.get("duration") or 0),
            "s": float(j["format"]["duration"])}


def audio_scan(p: str) -> dict:
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", p, "-vn", "-af",
                        "ebur128=peak=true,silencedetect=n=-45dB:d=1.0", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    peak = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", r.stderr)
    sil = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", r.stderr)]
    return {"lufs": float(lufs[-1]) if lufs else None, "tp": float(peak[-1]) if peak else None,
            "sil_max": round(max(sil), 1) if sil else 0.0, "sil_total": round(sum(sil), 1)}


def black_scan(p: str) -> dict:
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", p, "-an", "-vf",
                        "fps=2,scale=320:180,blackdetect=d=0.5:pix_th=0.06", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    d = [float(x) for x in re.findall(r"black_duration:([\d.]+)", r.stderr)]
    return {"black_n": len(d), "black_max": round(max(d), 1) if d else 0.0}


def expected_seconds(p: str, lead_tail: float) -> float | None:
    ws = sorted(glob.glob(p[:-4] + "_audio/speech_*.wav"))
    if not ws:
        return None
    t = 0.0
    for w in ws:
        with wave.open(w) as f:
            t += f.getnframes() / f.getframerate() + lead_tail
    return round(t, 1)


def cue_interpolated(p: str) -> int | None:
    tj = p[:-4] + "_audio/_timing.json"
    if not os.path.exists(tj):
        return None
    try:
        with open(tj, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        return -1
    return sum(1 for s in (doc.get("slides") or {}).values()
               for c in (s.get("cues") or []) if not c.get("matched"))


def problems_of(rows: list[dict], spec: tuple = SPEC) -> list[tuple[str, str]]:
    """検査結果の行から異常を拾う（ffmpeg を呼ばない純粋な判定）。"""
    lufs = [r["lufs"] for r in rows if r.get("lufs") is not None]
    med = statistics.median(lufs) if lufs else None
    out = []
    for r in rows:
        n = r["name"]
        if tuple(r["spec"]) != tuple(spec):
            out.append((n, f"仕様 {r['spec']}"))
        if abs(r["v_s"] - r["a_s"]) > 0.25:
            out.append((n, f"映像と音声の尺の差 {r['v_s'] - r['a_s']:.2f}s"))
        if r.get("expected_s") and abs(r["s"] - r["expected_s"]) > 1.5:
            out.append((n, f"尺が wav から出した値と {r['s'] - r['expected_s']:+.1f}s"))
        if r.get("lufs") is None or (med is not None and abs(r["lufs"] - med) > 1.0):
            out.append((n, f"音量 {r.get('lufs')} LUFS（中央値 {med}）"))
        if r.get("black_n"):
            out.append((n, f"黒フレーム {r['black_n']} 区間（最長 {r['black_max']}s）"))
        if r.get("cue_interp"):
            out.append((n, f"補間に落ちた cue {r['cue_interp']} 件" if r["cue_interp"] > 0
                        else "_timing.json が読めない"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mp4", nargs="+", help="完成 MP4（グロブ可）")
    ap.add_argument("--exclude", nargs="*", default=["_rec.mp4", ".previous.mp4"], help="除外する末尾")
    ap.add_argument("--lead-tail", type=float, default=3.0, help="座学のスライドごとの lead + tail（秒）")
    ap.add_argument("--md")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    paths = [p for pat in a.mp4 for p in (sorted(glob.glob(pat)) or [pat])
             if not any(p.endswith(x) for x in a.exclude)]
    rows = []
    for p in paths:
        r = {"name": os.path.basename(p)[:-4], "path": p, "mb": round(os.path.getsize(p) / 1e6, 1)}
        r.update(probe(p))
        r["expected_s"] = expected_seconds(p, a.lead_tail)
        r.update(audio_scan(p))
        r.update(black_scan(p))
        r["cue_interp"] = cue_interpolated(p)
        rows.append(r)
        print(f"  {r['name'][:40]:40} {r['s']:7.1f}s {r['lufs']} LUFS", flush=True)
    if not rows:
        print("対象の MP4 がありません")
        return 1
    problems = problems_of(rows)
    lufs = [r["lufs"] for r in rows if r["lufs"] is not None]
    print(f"\n{len(rows)} 本 / 合計 {sum(r['s'] for r in rows) / 3600:.1f} 時間 / "
          f"統合ラウドネスの中央値 {statistics.median(lufs) if lufs else '—'} LUFS")
    print("異常なし" if not problems else "異常:")
    for n, msg in problems:
        print(f"  {n}: {msg}")
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write("| 本 | 尺 | 期待との差 | LUFS | TP | 最長の無音 | 黒 | cue 補間 |\n"
                    "|---|---:|---:|---:|---:|---:|---:|---:|\n")
            for r in rows:
                dd = f"{r['s'] - r['expected_s']:+.1f}s" if r["expected_s"] else "—"
                f.write(f"| {r['name']} | {r['s'] / 60:.1f}分 | {dd} | {r['lufs']} | {r['tp']} | "
                        f"{r['sil_max']}s | {r['black_n']} | {'—' if r['cue_interp'] is None else r['cue_interp']} |\n")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1, default=list)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
