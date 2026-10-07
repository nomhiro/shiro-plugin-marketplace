#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cue の時刻が、その cue で始まる文の時刻から離れていないかを見る（誤一致の検出）。

cue_report.py は補間（matched=false）しか数えない。短い cue が**別の場所に「一致」**したときは
matched=true のまま時刻がずれる（実測：27秒ずれた例が3本で出た）。`_timing.json` の sentences
（音声の書き起こしから得た文ごとの開始時刻）と突き合わせ、cue で始まる文の開始時刻との差を出す。
形式は cue_report.py の docstring を参照。

文の途中に置いた cue や、書き起こしが崩れた文（cue で始まる文が見つからない）は判定しない。
書き起こしの崩れ（多くの文の時刻が1秒内に固まる）による誤報は、目で見て除く。

    python cue_drift.py "lectures/*/*_audio/_timing.json"
    python cue_drift.py <timing.json> --threshold 2

終了コード: ずれた cue が1件でもあれば 1。
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import unicodedata
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

KEY_LEN = 8


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"[\s、。，．,.！？!?「」『』（）()・:：]", "", s).lower()


def drifts(doc: dict, threshold: float = 3.0) -> list[dict]:
    """cue で始まる文の時刻と cue の時刻の差が threshold を超えたもの。"""
    out = []
    slides = doc.get("slides") or {}
    for sk in sorted(slides, key=lambda k: int(k)):
        sv = slides[sk]
        sents = [(norm(x.get("text", "")), x.get("start", 0.0)) for x in sv.get("sentences") or []]
        if not sents:
            continue
        for c in sv.get("cues") or []:
            key = norm(c.get("cue", ""))[:KEY_LEN]
            if not key:
                continue
            hits = [st for t, st in sents if t.startswith(key)]
            if not hits:
                continue
            near = min(hits, key=lambda h: abs(c["start"] - h))
            d = abs(c["start"] - near)
            if d > threshold:
                out.append({"slide": int(sk), "cue": c.get("cue", ""), "cue_at": c["start"],
                            "sentence_at": near, "diff": round(d, 1)})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("timing", nargs="+", help="_timing.json（グロブ可）")
    ap.add_argument("--threshold", type=float, default=3.0, help="これを超える差を数える（秒）")
    a = ap.parse_args(argv)
    bad = 0
    for p in [Path(x) for pat in a.timing for x in (sorted(glob.glob(pat)) or [pat])]:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"{p}: 読めません（{e}）")
            bad += 1
            continue
        name = p.parent.name.removesuffix("_audio")
        for d in drifts(doc, a.threshold):
            bad += 1
            print(f"{name} s{d['slide']}: {d['cue']} cue={d['cue_at']:.1f}s 文={d['sentence_at']:.1f}s 差={d['diff']}s")
    print(f"ずれた cue: {bad}件")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
