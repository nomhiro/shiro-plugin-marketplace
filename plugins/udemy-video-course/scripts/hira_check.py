# -*- coding: utf-8 -*-
"""合成音声を窓に切り、Gemini の音声入力に「聞こえた音のとおり、ひらがなだけで」書かせる（読み取り専用）。

なぜ要るか（実測）: 音声認識（verify_tts.py の STT）は**ヒントの語に引かれて綴る**。
同じ音が行によって「非公知性」「非効率性」「飛行地性」、「ドッカー」「ロッカー」に割れ、
綴りだけで「誤読」と決めて作り直すと**空回りする**（同じ癖が毎回出る。約15回作り直しても同じだった）。
このツールで音をひらがなで確かめると、7箇所すべて正しく読めていた（＝TTS の誤読ではなく STT の癖）。

    python hira_check.py <wav> [<wav> ...]
    python hira_check.py speech_05.wav --pattern "[どろ]っ?か[ーあ]"     # 注目する語（ひらがなの正規表現）を数える

使い方の注意:
- 窓は約 9 秒（7 秒刻みで重ねる）。区間全体（25 秒超）を1回で送ると接続が切れることがある。
  窓の端で語が切れることがあるので、**重なる窓で見る**。
- 2 種類の指示（P1・P2）で出す。**2 回以上同じ音なら確からしい。** Gemini も 1 回は聞き違えうる。
- 同じ話者・同じ文脈で「正しい入力」と「疑う入力」を合成し、同じ方式にかけて**音で分けられるか**を先に確かめるとよい（対照実験）。
- 音声は変更しない。Vertex AI の Gemini を ADC で呼ぶ（pip install google-genai。
  プロジェクトは --project か環境変数 GOOGLE_CLOUD_PROJECT。値は `gcloud config get-value project` で取る。全窓 ERR はプロジェクトか認証の誤り）。

終了コード: 0＝書き起こした／2＝引数・認証の不足。誤読かどうかの判定はしない（人が読む）。

止まったまま戻らないことへの対処（0.7.2）: AI-200 の制作（2026-11-28）で、書き起こしを出し終えたあと（または途中で）
プロセスが戻らないことがあった。1回の呼び出しに上限（`--timeout`、既定 60 秒）を付け、超えた窓は再試行のあと `ERR(時間切れ…)` と出す。
終わる前にクライアントを閉じ、出力を流しきってから `os._exit` で抜ける（`hira_narrow.py` も同じ）。原因は未確定。
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MODEL = "gemini-2.5-flash"
REQUEST_TIMEOUT_SECONDS = 60.0   # 1回の呼び出しの上限（0.7.2）
P1 = ("この音声は日本語の文章です。聞こえたとおりに、ひらがなだけで書き起こしてください。"
      "意味を推測して補正せず、実際に発音された音をそのまま書いてください。出力は書き起こし1行だけ。")
P2 = ("次の音声を、聞こえた音のとおりにひらがなだけで文字に起こしてください。意味を考えて直さないこと。"
      "外来語の語頭の音（ど・ろ・と・こ など）は、聞こえた音を区別して書くこと。出力は本文のみ。")


def windows(n_sec: float, win: float = 9.0, stride: float = 7.0):
    """重なる窓 (開始, 終了) を返す。最後の窓は末尾まで。"""
    out, t = [], 0.0
    while t < n_sec:
        out.append((t, min(t + win, n_sec)))
        if t + win >= n_sec:
            break
        t += stride
    return out


def read_wav(path: Path) -> tuple[bytes, int, int, int]:
    """(PCM, サンプリング周波数, チャンネル数, サンプル幅) を返す。"""
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getnchannels(), w.getsampwidth()


def wav_bytes(pcm: bytes, rate: int, ch: int, width: int) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return b.getvalue()


def make_client(project: str, location: str, timeout: float = REQUEST_TIMEOUT_SECONDS):
    """Vertex AI の Gemini のクライアント。1回の呼び出しに上限を付ける（HttpOptions.timeout はミリ秒）。"""
    from google import genai
    from google.genai import types
    return genai.Client(vertexai=True, project=project, location=location,
                        http_options=types.HttpOptions(timeout=int(timeout * 1000)))


def exit_now(client, code: int) -> None:
    """クライアントを閉じ、出力を流しきってから、後片付けを待たずに抜ける（0.7.2。書き込むファイルは無い）。"""
    try:
        client.close()
    except Exception:  # noqa: BLE001
        pass
    for s in (sys.stdout, sys.stderr):
        try:
            s.flush()
        except Exception:  # noqa: BLE001
            pass
    os._exit(code)


def listen(client, model: str, data: bytes, prompt: str) -> str:
    from google.genai import types
    last = ""
    for k in range(4):
        try:
            r = client.models.generate_content(
                model=model,
                contents=[types.Part.from_bytes(data=data, mime_type="audio/wav"), prompt],
                config=types.GenerateContentConfig(temperature=0.0))
            return (r.text or "").strip()
        except Exception as e:      # 一時的な失敗・時間切れは少し待って再試行する
            last = type(e).__name__
            time.sleep(2 + 2 * k)
    return f"ERR({last})" if last else "ERR"


def run(client, model: str, path: Path, win: float = 9.0, stride: float = 7.0):
    pcm, rate, ch, width = read_wav(path)
    step = ch * width
    n = len(pcm) / step / rate
    jobs = [(a, b, p) for a, b in windows(n, win, stride) for p in (P1, P2)]

    def one(j):
        a, b, p = j
        seg = pcm[int(a * rate) * step:int(b * rate) * step]
        return listen(client, model, wav_bytes(seg, rate, ch, width), p)

    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(one, jobs))
    return [(a, b, "P1" if p is P1 else "P2", r) for (a, b, p), r in zip(jobs, res)]


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("wavs", nargs="+", type=Path)
    ap.add_argument("--pattern", default="", help="注目する語の正規表現（ひらがな。任意）")
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    ap.add_argument("--location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--timeout", type=float, default=REQUEST_TIMEOUT_SECONDS, help="1回の呼び出しの上限秒数")
    a = ap.parse_args()
    if not a.project:
        print("--project か GOOGLE_CLOUD_PROJECT を指定してください", file=sys.stderr)
        return 2
    client = make_client(a.project, a.location, a.timeout)
    pat = re.compile(a.pattern) if a.pattern else None
    for w in a.wavs:
        print(f"=== {w.name}", flush=True)
        for t0, t1, tag, r in run(client, a.model, w):
            mark = ""
            if pat:
                hits = pat.findall(r)
                mark = f"   <- {hits}" if hits else ""
            print(f"  {t0:5.1f}-{t1:5.1f} {tag}: {r}{mark}", flush=True)
    exit_now(client, 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
