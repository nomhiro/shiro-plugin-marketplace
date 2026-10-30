# -*- coding: utf-8 -*-
"""音声のクリックノイズ（プチッ）を機械で検出する。

なぜ要るか（実測）: TTS の `LINEAR16` の応答は**ヘッダ付きの WAV** で返ることがある。
そのまま連結すると **44 バイトの RIFF ヘッダが音声サンプルとして鳴る**（振幅はフルスケールの 85〜93%・約 0.9ms）。
行末の無音のあとに鳴るので「発話 → 無音 → パチッ → 次の発話」と聞こえる。
動画を3本作り終えるまで、**受講者役の耳でしか見つからなかった**（尺と読みは機械で検証していたが、波形は見ていなかった）。

2つの検査:
  1. wav の先頭 … 先頭に RIFF ヘッダが埋まっていないか、無音で始まっているか。**音声を作った直後に回す。**
  2. 完成動画のクリップ開始点 … 各区間の音声が始まる時刻の ±3ms の最大振幅。
     そこは前の区間の末尾の無音の直後なので**本来ゼロであるべき**。

★ 無音区間を走査する汎用の検出器では見つからない。クリックは 1ms ほどしかなく、窓がクリック自体を含んでしまう
（実際に空振りした）。**開始時刻をピンポイントで測る**のが確実。

    python check_clicks.py <audio_dir>/*.wav                          # 1 だけ
    python check_clicks.py <audio_dir>/*.wav --video out.mp4 --starts 0,7.35,15.14
    python check_clicks.py --video out.mp4 --starts-file starts.txt   # 1 行 1 時刻（秒）

既存の音声を直すときは、**サンプル数を変えずに先頭のヘッダ分をゼロで埋める**（ヘッダ直後は実測で完全な無音なので段差なくつながる）。
削除すると尺が縮み、尺・字幕・強調のきっかけの時刻がまとめて無効になる。

終了コード: 0＝問題なし／1＝問題あり／2＝引数の誤り。
"""
from __future__ import annotations

import argparse
import array
import subprocess
import sys
import wave
from pathlib import Path

# クリックとみなす振幅（16bit フルスケール 32767 に対して約 9%）。AAC の量子化ノイズは実測で 13 程度。
CLICK_LEVEL = 3000
HEAD_SAMPLES = 200   # 先頭のこのサンプル数は無音であるべき（ヘッダは 22 サンプル分）
PROBE_MS = 3.0
MP4_RATE = 48000


def data_offset(blob: bytes) -> int | None:
    """PCM の先頭に埋まった RIFF の `data` チャンクの中身が始まる位置。無ければ None。"""
    if len(blob) < 12 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        return None
    pos = 12
    while pos + 8 <= len(blob):
        chunk_id = blob[pos:pos + 4]
        size = int.from_bytes(blob[pos + 4:pos + 8], "little")
        if chunk_id == b"data":
            return pos + 8
        pos += 8 + size + (size & 1)
    return None


def head_problems(name: str, pcm: bytes) -> list[str]:
    off = data_offset(pcm)
    if off is not None:
        return [f"{name}: 先頭に RIFF ヘッダが {off} バイト埋まっている（合成の応答からヘッダを剥がしていない）"]
    head = pcm[:HEAD_SAMPLES * 2]
    s = array.array("h", head[:len(head) - len(head) % 2])
    peak = max((abs(v) for v in s), default=0)
    if peak > CLICK_LEVEL:
        return [f"{name}: 先頭 {HEAD_SAMPLES} サンプルのピークが {peak}（無音で始まっていない）"]
    return []


def peaks_at(samples, starts: list[float], rate: int = MP4_RATE, probe_ms: float = PROBE_MS) -> list[tuple[float, int]]:
    """各時刻の ±probe_ms の最大振幅。"""
    half = int(rate * probe_ms / 1000)
    out = []
    for t in starts:
        i = int(t * rate)
        lo, hi = max(0, i - half), min(len(samples), i + half)
        out.append((t, max((abs(v) for v in samples[lo:hi]), default=0)))
    return out


def video_problems(mp4: Path, starts: list[float]) -> list[str]:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-ac", "1", "-ar", str(MP4_RATE),
                          "-f", "s16le", "-"], capture_output=True).stdout
    s = array.array("h", raw[:len(raw) - len(raw) % 2])
    if not len(s):
        return [f"{mp4.name}: 音声トラックを読めない"]
    return [f"{mp4.name} t={t:.3f}s: クリップの開始点で振幅 {p}（{100 * p / 32767:.0f}%）。本来ゼロ"
            for t, p in peaks_at(s, starts) if p > CLICK_LEVEL]


def main() -> int:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("wavs", nargs="*", type=Path)
    ap.add_argument("--video", type=Path, default=None)
    ap.add_argument("--starts", default="", help="区間の音声が始まる時刻（秒・カンマ区切り）")
    ap.add_argument("--starts-file", type=Path, default=None, help="1 行 1 時刻（秒）")
    a = ap.parse_args()
    starts = [float(x) for x in a.starts.split(",") if x.strip()]
    if a.starts_file:
        starts += [float(x) for x in a.starts_file.read_text(encoding="utf-8").split() if x.strip()]
    if not a.wavs and not a.video:
        print("wav か --video を指定してください", file=sys.stderr)
        return 2
    if a.video and not starts:
        print("--video には --starts か --starts-file が要る", file=sys.stderr)
        return 2
    problems: list[str] = []
    for w in a.wavs:
        with wave.open(str(w)) as f:
            problems += head_problems(w.name, f.readframes(f.getnframes()))
    if a.video:
        problems += video_problems(a.video, sorted(starts))
    for p in problems:
        print(f"  NG {p}")
    print(f"■ check_clicks: wav {len(a.wavs)} 本・開始点 {len(starts)} 箇所・問題 {len(problems)} 件")
    if problems:
        print("  直すときはサンプル数を変えずに先頭のヘッダ分をゼロで埋める（削除すると尺と時刻がずれる）")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
