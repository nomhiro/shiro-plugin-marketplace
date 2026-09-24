# -*- coding: utf-8 -*-
"""合成した wav を音声認識（STT）で文字に戻し、台本と同じ内容かを確かめる。

なぜ要るか: 合成音声は、まれに**台本と無関係な文**を読む（実測：「教育的な講座は…」
「ようこそ。オンライン講座へ…」のような文が区間まるごと、または冒頭に付いた）。
長さが台本の文字数に近いと qa_check.py の「実尺/期待尺」では見逃す。
文字に戻して台本と突き合わせるしか確かめる方法がない。

判定（どれかに当たれば NG）:
  - 類似度（difflib、空白・句読点を除いて比較）が --threshold 未満
  - 認識結果の長さが台本の 0.6〜1.6 倍の外（冒頭・末尾に余計な文が付いた、途中が抜けた）
  - 台本の先頭 8 文字が、認識結果の先頭 30 文字の中に似た形で現れない（冒頭の抜け・前置き）
    ※ 台本の先頭に英字・数字があるときは判定しない（Owner→オーナー のように表記が変わるため）

使い方:
    python verify_tts.py <..._transcript_rec.md> --endpoint https://<resource>.cognitiveservices.azure.com/
    python verify_tts.py <台本> --endpoint ... --keys rec_27 rec_44     # 指定した区間だけ
    python verify_tts.py <台本> --endpoint ... --json result.json

前提: pip install azure-cognitiveservices-speech azure-identity、ffmpeg が PATH にあること、
az login 済みで、エンドポイントのリソースに推論のロール（Foundry User など）があること。
エンドポイントは環境変数 SPEECH_ENDPOINT でも渡せる。

NG が出た区間は、wav を退避して再合成し、もう一度このスクリプトで確かめる。
同じ区間で繰り返すなら、英字・小数・日付・パスの羅列を言い換える。
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SLIDE_RE = re.compile(r"^スライド\s*(\d+)\s*[:：]")
REC_RE = re.compile(r"^録画\s*(\d+)\s*\[")
NORM_RE = re.compile(r"[\s、。，．,.・「」『』（）()!！?？:：;；\-ー―…]")


def parse(md: Path) -> dict[str, str]:
    secs: dict[str, str] = {}
    cur, rec_i = None, 0
    for line in md.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            h = line[3:].strip()
            m = SLIDE_RE.match(h)
            if m:
                cur = f"slide_{int(m.group(1)):02d}"
            elif REC_RE.match(h):
                rec_i += 1
                cur = f"rec_{rec_i:02d}"
            else:
                cur = None
                continue
            secs[cur] = ""
        elif cur:
            secs[cur] += line.strip()
    return secs


def norm(t: str) -> str:
    return NORM_RE.sub("", t).lower()


def recognize(wav: Path, endpoint: str, cred) -> str:
    import azure.cognitiveservices.speech as sd
    # 一時ファイルは一意の名前にする（区間名だけだと、並行実行した別レクチャーの同名区間と上書きし合い、
    # 他の回の音声を認識して「台本と別の文」と誤判定する。実測で起きた）
    fd, tmpname = tempfile.mkstemp(prefix=f"verify_tts_{wav.stem}_", suffix=".wav")
    os.close(fd)
    tmp = Path(tmpname)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-ar", "16000", "-ac", "1", str(tmp)],
                   check=True)
    cfg = sd.SpeechConfig(token_credential=cred, endpoint=endpoint)
    cfg.speech_recognition_language = "ja-JP"
    r = sd.SpeechRecognizer(speech_config=cfg, audio_config=sd.audio.AudioConfig(filename=str(tmp)))
    out, done = [], [False]
    r.recognized.connect(lambda e: out.append(e.result.text))
    r.session_stopped.connect(lambda e: done.__setitem__(0, True))
    r.canceled.connect(lambda e: done.__setitem__(0, True))
    r.start_continuous_recognition()
    t0 = time.time()
    while not done[0] and time.time() - t0 < 600:
        time.sleep(0.3)
    r.stop_continuous_recognition()
    try:
        tmp.unlink()
    except OSError:
        pass
    return "".join(out)


def judge(script: str, got: str, threshold: float) -> tuple[bool, float, list[str]]:
    a, b = norm(script), norm(got)
    ratio = difflib.SequenceMatcher(None, a, b).ratio() if a else 0.0
    why = []
    if ratio < threshold:
        why.append(f"類似度 {ratio:.2f}")
    if a:
        lr = len(b) / len(a)
        if not (0.6 <= lr <= 1.6):
            why.append(f"長さの比 {lr:.2f}")
        # 冒頭の確認は、台本の先頭が英字・数字を含まない場合だけ（英字はカタカナで認識されて一致しない）
        head = a[:8]
        if head and len(b) >= 8 and not re.search(r"[a-z0-9]", head):
            best = max(difflib.SequenceMatcher(None, head, b[i:i + 8]).ratio()
                       for i in range(0, max(1, min(30, len(b) - 7))))
            if best < 0.4:
                why.append("冒頭が台本と合わない")
    return (not why), ratio, why


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--audio-dir", type=Path, default=None)
    ap.add_argument("--endpoint", default=os.environ.get("SPEECH_ENDPOINT"))
    ap.add_argument("--keys", nargs="*", default=None, help="rec_01 slide_02 … を指定（省略時は全区間）")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()
    if not a.endpoint:
        print("--endpoint か SPEECH_ENDPOINT を指定してください", file=sys.stderr)
        return 2
    base = a.transcript.name.replace("_transcript_rec.md", "")
    adir = a.audio_dir or (a.transcript.parent / f"{base}_audio_rec")
    secs = parse(a.transcript)
    keys = a.keys or list(secs)
    from azure.identity import DefaultAzureCredential
    cred = DefaultAzureCredential()
    results, bad = [], 0
    print(f"■ verify-tts: {base}（{len(keys)} 区間）")
    for k in keys:
        wav = adir / f"{k}.wav"
        if k not in secs or not wav.exists():
            print(f"  -- {k}: 台本か wav が無い")
            continue
        got = recognize(wav, a.endpoint, cred)
        ok, ratio, why = judge(secs[k], got, a.threshold)
        bad += not ok
        results.append({"key": k, "ok": ok, "similarity": round(ratio, 3), "why": why, "recognized": got})
        mark = "OK" if ok else "NG"
        print(f"  {mark} {k} sim={ratio:.2f} {'／'.join(why)}")
        if not ok:
            print(f"     台本: {secs[k][:80]}")
            print(f"     認識: {got[:80]}")
    if a.json:
        a.json.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  NG {bad} / {len(results)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
