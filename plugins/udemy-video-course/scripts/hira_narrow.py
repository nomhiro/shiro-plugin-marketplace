# -*- coding: utf-8 -*-
"""狭い窓（約3秒・1.5秒刻み）で、1つの語の読みの割れを数える（読み取り専用）。

    python hira_narrow.py speech_08.wav しゅちょう しちょう [<疑う読み> ...]

なぜ要るか（実測）: 通しの窓（9秒）の `hira_check.py` では「しゅちょう」と出たのに、語を中心にした2〜4秒の窓では
「しちょう」に割れた。通しの窓を1回見るだけでは割れが見えない。
`hira_check.py` の P1・P2 と同じ指示で、窓ごとに2回ずつ聞き、どれかの読みを含む窓だけを数える。

目安: **疑う読みが半分以下なら通す**（STT の揺れの範囲）。半分を超えたときだけ、録り直すか、読みの辞書で直すか、言い換える
（`references/tts-readings.md`「読みの確認を過剰にしない」）。

音声は変更しない。Vertex AI の Gemini を ADC で呼ぶ（プロジェクトは --project か環境変数 GOOGLE_CLOUD_PROJECT）。
終了コード: 0＝通す（疑う読みが半分以下）／1＝疑う読みが過半数／2＝引数・認証の不足。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hira_check import MODEL, run  # noqa: E402


def count_readings(texts: list[str], words: list[str]) -> dict[str, int]:
    """書き起こし（窓ごと）のうち、各読みを含むものを数える。空白は無視する。"""
    counts = {w: 0 for w in words}
    for t in texts:
        t = t.replace(" ", "").replace("　", "")
        for w in words:
            if w in t:
                counts[w] += 1
    return counts


def suspicious(counts: dict[str, int], good: str) -> bool:
    """疑う読みが、数えた読み全体の過半数か。"""
    bad = sum(c for w, c in counts.items() if w != good)
    total = bad + counts.get(good, 0)
    return total > 0 and bad * 2 > total


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", type=Path)
    ap.add_argument("good", help="正しい読み（ひらがな）")
    ap.add_argument("bads", nargs="+", help="疑う読み（ひらがな）")
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    ap.add_argument("--location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()
    if not a.project:
        print("--project か GOOGLE_CLOUD_PROJECT を指定してください", file=sys.stderr)
        return 2
    from google import genai
    client = genai.Client(vertexai=True, project=a.project, location=a.location)
    rows = run(client, a.model, a.wav, win=3.0, stride=1.5)
    words = [a.good] + a.bads
    for t0, t1, tag, r in rows:
        if any(w in r.replace(" ", "") for w in words):
            print(f"  {t0:5.1f}-{t1:5.1f} {tag}: {r}", flush=True)
    counts = count_readings([r for *_, r in rows], words)
    print("数:", "　".join(f"{w}={c}" for w, c in counts.items()))
    # 2026-11-01: 語が行に2回以上あると、1回目が正しい読みで2回目の誤読が隠れる（AZ-104 L2-2 F16「職務ロール」）。
    # 語を含む窓を、時刻が 3 秒以内でつながる「出現」ごとにまとめて、出現ごとにも数える。どれか1つでも過半数なら止める
    hits = [(t0, r) for t0, _t1, _tag, r in rows if any(w in r.replace(" ", "") for w in words)]
    groups, cur, last = [], [], None
    for t0, r in hits:
        if last is not None and t0 - last > 3.0:
            groups.append(cur); cur = []
        cur.append((t0, r)); last = t0
    if cur:
        groups.append(cur)
    bad_group = False
    if len(groups) > 1:
        for g in groups:
            c = count_readings([r for _t, r in g], words)
            mark = "  ← 疑う読みが過半数" if suspicious(c, a.good) else ""
            bad_group = bad_group or bool(mark)
            print(f"  出現 {g[0][0]:5.1f}s〜:", "　".join(f"{w}={n}" for w, n in c.items()) + mark)
    if suspicious(counts, a.good) or bad_group:
        print("→ 疑う読みが過半数（行全体か、どれかの出現で）。録り直すか、読みの辞書で直すか、言い換える")
        return 1
    print("→ 通す（疑う読みは半分以下）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
