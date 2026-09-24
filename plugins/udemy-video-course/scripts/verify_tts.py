# -*- coding: utf-8 -*-
"""合成した wav を音声認識（STT）で文字に戻し、台本と同じ内容かを確かめる。

なぜ要るか: 合成音声は、まれに**台本と無関係な文**を読む（実測：「教育的な講座は…」
「ようこそ。オンライン講座へ…」のような文が区間まるごと、または冒頭に付いた）。
長さが台本の文字数に近いと qa_check.py の「実尺/期待尺」では見逃す。
文字に戻して台本と突き合わせるしか確かめる方法がない。

判定（どれかに当たれば NG）。比べるのは漢字とひらがなだけ（英字・数字はカタカナや漢数字で
認識されて一致しないため。difflib の全文比較では、正しい区間でも 0.5 前後まで下がり、事故と
見分けがつかなかった）:
  - 再現率（台本の2文字組のうち認識結果にある割合）が --threshold 未満 … 読み落とし・途中で切れた
  - 適合率（認識結果の2文字組のうち台本にある割合）が --threshold 未満 … 前置き・別の文
  - 台本の冒頭／末尾の数文字が、認識結果の冒頭／末尾に無い … 1文だけの脱落・付加
  - スタイル指示の読み上げ（「オンライン講座」「語りかける」「カメラの前」など）
0.6〜0.75 の区間は OK でも「要確認」と表示するので、認識結果を目で見て判断する。

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
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
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


J_RE = re.compile(r"[ぁ-ゟ一-鿿]")
# 合成時のスタイル指示（「親しみやすいオンライン講座…語りかけるように…カメラの前に…」）が
# そのまま読み上げられた事故の目印。台本側に無い語が認識結果に出たら NG
LEAK_WORDS = ("語りかける", "カメラの前", "オンライン講座", "ナレーター", "安心して学べる")


def _jchars(t: str) -> str:
    """漢字とひらがなだけを残す（英字はカタカナで認識されるので比較から外す）"""
    return "".join(J_RE.findall(t))


def _bigrams(t: str) -> Counter:
    return Counter(t[i:i + 2] for i in range(len(t) - 1))


def _cover(part: str, whole: str) -> float:
    """part の2文字組のうち、whole に現れる割合"""
    a, b = _bigrams(part), _bigrams(whole)
    n = sum(a.values())
    return sum((a & b).values()) / n if n else 1.0


def judge(script: str, got: str, threshold: float) -> tuple[bool, float, list[str]]:
    """判定。戻り値の数値は min(再現率, 適合率)（漢字・ひらがなの2文字組で数える）。

    - 再現率が低い：台本の一部が読まれていない（冒頭・途中の脱落、途中で切れた）
    - 適合率が低い：台本に無い文が読まれている（前置きの付加、別の文、スタイル指示の読み上げ）
    - 冒頭・末尾：台本の最初と最後の数文字が、認識結果の最初と最後にあるか
    """
    a, b = _jchars(script), _jchars(got)
    why = []
    if not b:
        return False, 0.0, ["認識結果が空"]
    ab, bb = _bigrams(a), _bigrams(b)
    inter = sum((ab & bb).values())
    rec = inter / sum(ab.values()) if ab else 1.0
    pre = inter / sum(bb.values()) if bb else 1.0
    score = min(rec, pre)
    if rec < threshold:
        why.append(f"台本の読み落とし（再現率 {rec:.2f}）")
    if pre < threshold:
        why.append(f"台本に無い文（適合率 {pre:.2f}）")
    if len(a) >= 12:
        if _cover(a[:8], b[:24]) < 0.4:
            why.append("冒頭が台本と合わない")
        if _cover(a[-8:], b[-24:]) < 0.4:
            why.append("末尾が台本と合わない")
    leak = [w for w in LEAK_WORDS if w in got and w not in script]
    if leak:
        why.append("スタイル指示の読み上げ（" + "・".join(leak) + "）")
    return (not why), score, why


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--audio-dir", type=Path, default=None)
    ap.add_argument("--endpoint", default=os.environ.get("SPEECH_ENDPOINT"))
    ap.add_argument("--keys", nargs="*", default=None, help="rec_01 slide_02 … を指定（省略時は全区間）")
    ap.add_argument("--threshold", type=float, default=0.6,
                    help="再現率・適合率（漢字・ひらがなの2文字組）の下限。0.6〜0.75 は目視で確かめる帯")
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()
    if not a.endpoint:
        print("--endpoint か SPEECH_ENDPOINT を指定してください", file=sys.stderr)
        return 2
    # 実践（…_transcript_rec.md ＋ …_audio_rec/slide_NN.wav・rec_NN.wav）と
    # 座学（…_transcript.md ＋ …_audio/speech_NN.wav）の両方に対応する
    base = a.transcript.name.replace("_transcript_rec.md", "").replace("_transcript.md", "")
    adir = a.audio_dir
    if adir is None:
        adir = a.transcript.parent / f"{base}_audio_rec"
        if not adir.exists():
            adir = a.transcript.parent / f"{base}_audio"
    secs = parse(a.transcript)
    keys = a.keys or list(secs)
    from azure.identity import DefaultAzureCredential
    cred = DefaultAzureCredential()
    results, bad = [], 0
    print(f"■ verify-tts: {base}（{len(keys)} 区間）")
    for k in keys:
        wav = adir / f"{k}.wav"
        if not wav.exists() and k.startswith("slide_"):
            wav = adir / f"speech_{k[6:]}.wav"   # 座学の音声の名前
        if k not in secs or not wav.exists():
            print(f"  -- {k}: 台本か wav が無い")
            continue
        got = recognize(wav, a.endpoint, cred)
        ok, ratio, why = judge(secs[k], got, a.threshold)
        bad += not ok
        results.append({"key": k, "ok": ok, "score": round(ratio, 3), "why": why, "recognized": got})
        mark = "OK" if ok else "NG"
        if ok and ratio < 0.75:
            mark = "OK?"
        print(f"  {mark} {k} score={ratio:.2f} {'／'.join(why)}")
        if mark != "OK":
            print(f"     台本: {secs[k][:80]}")
            print(f"     認識: {got[:80]}")
    if a.json:
        a.json.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  NG {bad} / {len(results)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
