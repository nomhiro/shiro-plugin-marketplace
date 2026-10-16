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
  - 台本の冒頭より前／末尾より後ろに、認識結果の文字が 6 字を超えて残る … 短い前置き・作り話の付加
    （長い区間に20字ほど付いただけだと適合率も末尾の判定も通ってしまうため。受講者に指摘された実例）
  - スタイル指示の読み上げ（「オンライン講座」「語りかける」「カメラの前」など）
0.6〜0.75 の区間は OK でも「要確認」と表示するので、認識結果を目で見て判断する。

使い方:
    python verify_tts.py <..._transcript_rec.md> --endpoint https://<resource>.cognitiveservices.azure.com/
    python verify_tts.py <台本> --backend google                         # Google Cloud Speech-to-Text
    python verify_tts.py <台本> --endpoint ... --keys rec_27 rec_44     # 指定した区間だけ
    python verify_tts.py <台本> --endpoint ... --json result.json

照合先（--backend。環境変数 VERIFY_TTS_BACKEND でも渡せる。省略時はエンドポイントがあれば azure、無ければ google）:
  - azure  … Azure AI Speech をキーレス（Entra ID）で呼ぶ。pip install azure-cognitiveservices-speech azure-identity、
              az login 済みで、エンドポイントのリソースに推論のロール（Foundry User など）があること。
              エンドポイントは --endpoint か環境変数 SPEECH_ENDPOINT
  - google … Google Cloud Speech-to-Text（v1・latest_long・句読点あり）を ADC で呼ぶ。pip install google-cloud-speech、
              gcloud auth application-default login 済みで、プロジェクトの Speech-to-Text API が有効なこと。
              Gemini-TTS と同じプロジェクトで完結する。インラインで送れる音声は 1 分までなので、
              長い区間は**いちばん静かな所で 55 秒以内に切って**順に認識し、つないでから判定する
              （long_running_recognize もインラインは 1 分までで、超えると GCS を求められた。実測）
どちらも ffmpeg が PATH にあること。判定（judge）は照合先によらず同じ。

**STT の綴りだけで「誤読」と決めない。** STT はヒントの語に引かれて同じ音を別の語に綴る（「ドッカー」→「ロッカー」）。
同じ区間で NG が繰り返し、作り直しても同じ綴りが出るときは、hira_check.py で音をひらがなで確かめてから作り直す。

NG が出た区間は、wav を退避して再合成し、もう一度このスクリプトで確かめる。
同じ区間で繰り返すなら、英字・小数・日付・パスの羅列を言い換える。

**全区間が「認識結果が空」になったら、音声ではなく照合先を疑う。** 実測で2つの原因があった。
  - 照合先のリソースが消えていた（別講座の後片付けで削除され、DNS が引けなくなった）。
    照合先は講座のハンズオン用のリソースから切り離し、複数講座で共用するものにする。
  - 認証の取得が間に合わなかった（az の起動が遅いと既定の 10 秒で切れる。レンダと並走したとき）。
    そのため `DefaultAzureCredential(process_timeout=60)` にしている。
2区間以上を照合して全部が空のときは、NG とは別の終了コード 3（照合先エラー）で止める。

終了コード: 0＝全区間 OK／1＝NG あり／2＝引数の誤り／3＝照合先エラーの疑い（全区間が空）。
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


def lecture_speech_names(secs: dict[str, str]) -> dict[str, str]:
    """座学の区間キー（slide_NN）→ 音声ファイル名（speech_NN.wav）。

    lecture_movie.py は、本文のある `## スライドN:` に**台本のある順で** 01 から番号を振る。
    スライド番号そのものではないので、本文の無いスライドが途中にあると番号がずれる。
    """
    slides = sorted((k for k, v in secs.items() if k.startswith("slide_") and v.strip()),
                    key=lambda k: int(k[6:]))
    return {k: f"speech_{i:02d}.wav" for i, k in enumerate(slides, 1)}


def all_empty(results: list[dict]) -> bool:
    """2区間以上を照合し、全部の認識結果が空なら True（照合先の故障を疑う）。"""
    return len(results) >= 2 and all(not (r.get("recognized") or "").strip() for r in results)


def norm(t: str) -> str:
    return NORM_RE.sub("", t).lower()


BACKENDS = ("azure", "google")
GOOGLE_MAX_SEC = 55.0     # インラインで送れるのは 1 分まで（recognize も long_running_recognize も）。余裕を見て 55 秒
GOOGLE_CUT_SEARCH = 15.0  # 切れ目は、窓の終わりから手前この秒数の中で、いちばん静かな所に置く（語の途中で切らない）


def pick_backend(arg: str | None, env: str | None, endpoint: str | None) -> str:
    """照合先を決める。明示（引数 → 環境変数）が優先。無ければエンドポイントの有無で決める
    （既存の `--endpoint` だけの呼び方は、これまでどおり Azure で動く）。"""
    b = (arg or env or ("azure" if endpoint else "google")).strip().lower()
    if b not in BACKENDS:
        raise ValueError(f"未知の照合先: {b}（{' / '.join(BACKENDS)}）")
    return b


def cut_points(samples, rate: int, max_sec: float = GOOGLE_MAX_SEC, search: float = GOOGLE_CUT_SEARCH,
               frame_ms: int = 100) -> list[int]:
    """長い音声を max_sec 以内の塊に切るサンプル位置（先頭 0 と末尾を含む）。
    切れ目は各窓の終わりから手前 search 秒の中で、平均振幅がいちばん小さい frame_ms の位置（無音の間）にする。"""
    n, step = len(samples), max(1, rate * frame_ms // 1000)
    limit = int(max_sec * rate)
    pts = [0]
    while n - pts[-1] > limit:
        start = pts[-1]
        lo = start + max(step, int((max_sec - search) * rate))
        hi = start + limit - step
        best, best_e = hi, None
        for i in range(lo, hi, step):
            e = sum(abs(v) for v in samples[i:i + step])
            if best_e is None or e < best_e:
                best, best_e = i + step // 2, e
        pts.append(best)
    pts.append(n)
    return pts


def _prepare(wav: Path) -> Path:
    """照合用に 16kHz・モノへ変換し、末尾に無音を足した一時ファイルを返す（呼んだ側が消す）。"""
    # 一時ファイルは一意の名前にする（区間名だけだと、並行実行した別レクチャーの同名区間と上書きし合い、
    # 他の回の音声を認識して「台本と別の文」と誤判定する。実測で起きた）
    fd, tmpname = tempfile.mkstemp(prefix=f"verify_tts_{wav.stem}_", suffix=".wav")
    os.close(fd)
    tmp = Path(tmpname)
    # 末尾に無音を足す。合成音声の末尾の無音は 0.3 秒ほどしかなく、そのままだと STT が最後の語を
    # 取りこぼして「〜を確認。」のように切れ、末尾切れと誤判定する（実測：10区間、足すと全部読めた）
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-af", "apad=pad_dur=1.5",
                    "-ar", "16000", "-ac", "1", str(tmp)], check=True)
    return tmp


def recognize_google(wav: Path, client) -> str:
    """Google Cloud Speech-to-Text で認識する。"""
    import wave

    from google.cloud import speech
    tmp = _prepare(wav)
    try:
        # WAV ヘッダを剥がして PCM だけを送る（ヘッダごと・句読点なしで送ると、語単位の認識で
        # 数秒ぶんの語が落ちた実測がある）
        with wave.open(str(tmp), "rb") as w:
            pcm = w.readframes(w.getnframes())
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    import array
    samples = array.array("h", pcm[:len(pcm) - len(pcm) % 2])
    pts = cut_points(samples, 16000)
    cfg = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16, sample_rate_hertz=16000,
        language_code="ja-JP", model="latest_long", enable_automatic_punctuation=True)
    out = []
    for a, b in zip(pts, pts[1:]):
        audio = speech.RecognitionAudio(content=samples[a:b].tobytes())
        # 応答待ちのまま数時間止まったプロセスがあった。必ず timeout を付ける
        resp = client.recognize(config=cfg, audio=audio, timeout=180)
        out += [r.alternatives[0].transcript for r in resp.results if r.alternatives]
    return "".join(out)


def make_recognizer(backend: str, endpoint: str | None):
    """wav → 認識結果の文字列、を返す関数を作る。認証は1回だけ取る。"""
    if backend == "azure":
        from azure.identity import DefaultAzureCredential
        # az の起動が重いとき（レンダと並走など）既定の 10 秒で切れ、全区間が「認識結果が空」になる
        cred = DefaultAzureCredential(process_timeout=60)
        return lambda wav: recognize(wav, endpoint, cred)
    from google.cloud import speech
    client = speech.SpeechClient()
    return lambda wav: recognize_google(wav, client)


def recognize(wav: Path, endpoint: str, cred) -> str:
    """Azure AI Speech で認識する。"""
    import azure.cognitiveservices.speech as sd
    tmp = _prepare(wav)
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


# 台本の最初／最後の数文字が認識結果のどこに現れるかを探し、その前／後ろに残る文字数を数える。
# 「末尾が合わない」（最後の8文字が認識結果の最後の24文字にあるか）だけでは、短い作り話が
# 末尾に付いた事故を見逃す（実測：95秒の区間の末尾に「一番重要なテーマはSEO…」の約20字が付き、
# 本来の末尾が24字の窓に残って OK になった。適合率も 0.88 までしか下がらない）
EXTRA_MAX = 6   # 漢字・ひらがなでこれを超えて余っていたら NG（認識の揺れで数文字は余る）
_ANCHOR = 8


def _find(anchor: str, b: str, rightmost: bool) -> int | None:
    """anchor が合う b 内の開始位置のうち、端（冒頭なら左端・末尾なら右端）に最も近いもの。
    合う度合い 0.6 以上を優先し、無ければ最もよく合う位置（0.5 未満なら None）。
    最もよく合う位置だけを採ると、同じ言い回しが区間の後ろにもあるとき（「1回目の応答で」と
    「2回目の応答では」）そちらを選び、冒頭の前に余分な文があると誤判定する"""
    n = len(anchor)
    ps = list(range(0, max(1, len(b) - n + 1)))
    if rightmost:
        ps.reverse()
    best, pos = 0.0, None
    for p in ps:
        c = _cover(anchor, b[p:p + n])
        if c >= 0.6:
            return p
        if c > best:
            best, pos = c, p
    return pos if best >= 0.5 else None


def _extra_tail(a: str, b: str) -> int:
    p = _find(a[-_ANCHOR:], b, rightmost=True)
    # 見つからない場合は「末尾が台本と合わない」の判定に任せる
    return 0 if p is None else max(0, len(b) - (p + _ANCHOR))


def _extra_head(a: str, b: str) -> int:
    p = _find(a[:_ANCHOR], b, rightmost=False)
    return 0 if p is None else p


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
        head, tail = _extra_head(a, b), _extra_tail(a, b)
        if head > EXTRA_MAX:
            why.append(f"冒頭の前に台本に無い文（{head} 字）")
        if tail > EXTRA_MAX:
            why.append(f"末尾の後に台本に無い文（{tail} 字）")
    leak = [w for w in LEAK_WORDS if w in got and w not in script]
    if leak:
        why.append("スタイル指示の読み上げ（" + "・".join(leak) + "）")
    return (not why), score, why


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--audio-dir", type=Path, default=None)
    ap.add_argument("--backend", choices=BACKENDS, default=None,
                    help="照合先（省略時は環境変数 VERIFY_TTS_BACKEND、それも無ければエンドポイントの有無で決める）")
    ap.add_argument("--endpoint", default=os.environ.get("SPEECH_ENDPOINT"), help="azure のときのエンドポイント")
    ap.add_argument("--keys", nargs="*", default=None, help="rec_01 slide_02 … を指定（省略時は全区間）")
    ap.add_argument("--threshold", type=float, default=0.6,
                    help="再現率・適合率（漢字・ひらがなの2文字組）の下限。0.6〜0.75 は目視で確かめる帯")
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()
    try:
        backend = pick_backend(a.backend, os.environ.get("VERIFY_TTS_BACKEND"), a.endpoint)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    if backend == "azure" and not a.endpoint:
        print("azure で照合するには --endpoint か SPEECH_ENDPOINT を指定してください", file=sys.stderr)
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
    speech_names = lecture_speech_names(secs)
    import deps
    deps.preflight({"stt"} if backend == "azure" else {"stt-google"})
    recog = make_recognizer(backend, a.endpoint)
    results, bad = [], 0
    print(f"■ verify-tts: {base}（{len(keys)} 区間・照合先 {backend}）")
    for k in keys:
        wav = adir / f"{k}.wav"
        if not wav.exists() and k in speech_names:
            wav = adir / speech_names[k]   # 座学の音声の名前（台本のある順の通し番号）
        if k not in secs or not wav.exists():
            print(f"  -- {k}: 台本か wav が無い")
            continue
        got = recog(wav)
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
    if all_empty(results):
        print("  !! 全区間が「認識結果が空」です。音声ではなく照合先（azure はエンドポイントの DNS・認証・ロール、"
              "google は ADC・API の有効化・課金）を"
              "疑ってください。NG の区間を作り直す前に、1区間だけ認識させて原因を確かめる。", file=sys.stderr)
        return 3
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
