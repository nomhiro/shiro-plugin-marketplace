"""udemy-video-course のスクリプトのうち、外部依存なしで確かめられる判定を単体で検証する。

ffmpeg・TTS・STT・OCR を呼ぶ部分は CI で回せないので、判定を純粋な関数に切り出し、そこだけを見る。
"""
import pytest


# ---------------------------------------------------------------- verify_tts
def test_lecture_speech_names_follow_transcript_order_not_slide_number():
    """本文の無いスライドが途中にあると、speech_NN はスライド番号とずれる。"""
    from verify_tts import lecture_speech_names
    secs = {"slide_01": "表紙", "slide_02": "", "slide_03": "本文", "slide_10": "まとめ"}
    assert lecture_speech_names(secs) == {
        "slide_01": "speech_01.wav", "slide_03": "speech_02.wav", "slide_10": "speech_03.wav"}


def test_all_empty_means_the_endpoint_is_broken():
    from verify_tts import all_empty
    assert all_empty([{"recognized": ""}, {"recognized": " "}])
    assert not all_empty([{"recognized": ""}, {"recognized": "読めた"}])
    assert not all_empty([{"recognized": ""}])          # 1区間だけでは判断しない


def test_backend_is_explicit_first_then_endpoint():
    """照合先は 引数 → 環境変数 → エンドポイントの有無。`--endpoint` だけの既存の呼び方は Azure のまま。"""
    from verify_tts import pick_backend
    assert pick_backend(None, None, "https://x.cognitiveservices.azure.com/") == "azure"
    assert pick_backend(None, None, None) == "google"
    assert pick_backend(None, "google", "https://x/") == "google"
    assert pick_backend("azure", "google", None) == "azure"
    with pytest.raises(ValueError):
        pick_backend("whisper", None, None)


def test_long_audio_is_cut_in_the_quiet_part_within_the_limit():
    """Google はインラインの音声が 1 分まで。55 秒以内に、無音の所で切る（語の途中で切らない）。"""
    from verify_tts import cut_points
    rate = 100                                    # 1 秒 = 100 サンプルの模型
    s = [1000] * (rate * 130)
    s[rate * 48:rate * 49] = [0] * rate           # 48 秒目に1秒の無音
    s[rate * 95:rate * 96] = [0] * rate           # 95 秒目に1秒の無音
    pts = cut_points(s, rate, frame_ms=100)
    assert pts[0] == 0 and pts[-1] == len(s)
    assert all(b - a <= 55 * rate for a, b in zip(pts, pts[1:]))
    assert 48 * rate <= pts[1] < 49 * rate and 95 * rate <= pts[2] < 96 * rate
    assert cut_points([0] * (rate * 30), rate) == [0, rate * 30]   # 短ければ切らない


# ---------------------------------------------------------------- audio_manifest
def _mf(text, model="m1", voice="v1"):
    from audio_manifest import make_entry
    return make_entry(text, model, voice)


def test_changed_text_is_resynthesized_and_unchanged_is_kept():
    from audio_manifest import plan_audio
    items = [("speech_01.wav", "そのまま"), ("speech_02.wav", "直した文")]
    manifest = {"speech_01.wav": _mf("そのまま"), "speech_02.wav": _mf("直す前の文")}
    plan = plan_audio(items, {"speech_01.wav", "speech_02.wav"}, manifest, "m1", "v1")
    assert plan.make == ["speech_02.wav"] and plan.skip == ["speech_01.wav"] and not plan.conflicts


def test_inserted_slide_renumbers_and_resynthesizes_later_wavs():
    """台本の途中にスライドを足すと speech_NN が繰り下がる。古い番号の wav を流用しない。"""
    from audio_manifest import plan_audio
    old = {"speech_01.wav": _mf("一"), "speech_02.wav": _mf("二")}
    items = [("speech_01.wav", "一"), ("speech_02.wav", "足した"), ("speech_03.wav", "二")]
    plan = plan_audio(items, set(old), old, "m1", "v1")
    assert plan.skip == ["speech_01.wav"]
    assert plan.make == ["speech_02.wav", "speech_03.wav"]


def test_other_model_or_unknown_model_is_a_conflict():
    from audio_manifest import plan_audio
    items = [("rec_01", "a"), ("rec_02", "b")]
    manifest = {"rec_01": _mf("a", model="old"), "rec_02": _mf("b")}
    plan = plan_audio(items, {"rec_01", "rec_02"}, manifest, "m1", "v1")
    assert [k for k, _, _ in plan.conflicts] == ["rec_01"]
    # manifest の無い既存 wav（古い版）もモデルが分からないので止める
    plan = plan_audio(items, {"rec_01"}, {}, "m1", "v1")
    assert plan.conflicts == [("rec_01", None, None)] and plan.make == ["rec_02"]
    # --force は全部作り直すので衝突しない
    plan = plan_audio(items, {"rec_01", "rec_02"}, manifest, "m1", "v1", force=True)
    assert plan.make == ["rec_01", "rec_02"] and not plan.conflicts


def test_legacy_practice_manifest_is_read(tmp_path):
    import json
    from audio_manifest import load, text_digest
    (tmp_path / ".manifest.json").write_text(json.dumps({"rec_01": text_digest("a")}), encoding="utf-8")
    assert load(tmp_path) == {"rec_01": {"text": text_digest("a"), "model": None, "voice": None}}


def test_video_gate_finds_missing_stale_and_mixed_audio():
    from audio_manifest import video_problems
    items = [("speech_01.wav", "一"), ("speech_02.wav", "二"), ("speech_03.wav", "三")]
    manifest = {"speech_01.wav": _mf("一"), "speech_02.wav": _mf("古い二", model="m2")}
    problems, _ = video_problems(items, {"speech_01.wav", "speech_02.wav"}, manifest)
    text = "\n".join(problems)
    assert "speech_03.wav" in text and "古い" in text and "混在" in text


def test_video_gate_only_warns_without_manifest():
    """manifest の無い既存講座でも --video-only は通る（警告だけ）。"""
    from audio_manifest import video_problems
    items = [("speech_01.wav", "一")]
    problems, warnings = video_problems(items, {"speech_01.wav"}, {})
    assert not problems and warnings


# ---------------------------------------------------------------- deps
def test_preflight_stops_on_missing_dependency(monkeypatch, capsys):
    import deps
    monkeypatch.setitem(deps.GROUPS, "zzz", (("module_that_does_not_exist_xyz",), (), "テスト"))
    assert deps.missing({"zzz"}) == ["zzz: Python モジュール module_that_does_not_exist_xyz"]
    with pytest.raises(SystemExit) as e:
        deps.preflight({"zzz"})
    assert e.value.code == 2
    assert "python:" in capsys.readouterr().out      # どの Python で動いたかを必ず出す


# ---------------------------------------------------------------- lecture_movie の終了コード
def _lecture(tmp_path):
    sec = tmp_path / "lectures" / "01_x"
    sec.mkdir(parents=True)
    (sec / "L1-1-1_座学_x_transcript.md").write_text(
        "## スライド1: 表紙\n\n一枚目です。\n\n## スライド2: 本文\n\n二枚目です。\n", encoding="utf-8")
    return sec


def _run_lecture(monkeypatch, tmp_path, argv, synth):
    import lecture_movie
    monkeypatch.setattr(lecture_movie.deps, "preflight", lambda groups, **k: None)
    monkeypatch.setattr(lecture_movie, "synthesize_speech_file", synth)
    monkeypatch.setattr("sys.argv", ["lecture_movie.py", "L1-1-1", "--lectures-dir",
                                     str(tmp_path / "lectures"), "--audio-only", *argv])
    try:
        lecture_movie.main()
        return 0
    except SystemExit as e:
        return e.code


def test_tts_failure_returns_nonzero(monkeypatch, tmp_path):
    """以前は失敗した区間を無音の静止画にして終了コード 0 で終わっていた。"""
    _lecture(tmp_path)

    def boom(**kw):
        raise RuntimeError("503 Service Unavailable")
    assert _run_lecture(monkeypatch, tmp_path, [], boom) == 1
    assert _run_lecture(monkeypatch, tmp_path, ["--allow-tts-failure"], boom) == 0


def test_model_change_stops_before_synthesizing(monkeypatch, tmp_path):
    sec = _lecture(tmp_path)
    calls = []

    def ok(**kw):
        calls.append(kw["out_wav"].name)
        kw["out_wav"].parent.mkdir(parents=True, exist_ok=True)
        kw["out_wav"].write_bytes(b"RIFF")
    assert _run_lecture(monkeypatch, tmp_path, ["--model", "m1"], ok) == 0
    assert calls == ["speech_01.wav", "speech_02.wav"]
    calls.clear()
    assert _run_lecture(monkeypatch, tmp_path, ["--model", "m1"], ok) == 0
    assert calls == []                                     # 本文もモデルも同じなら作らない
    assert _run_lecture(monkeypatch, tmp_path, ["--model", "m2"], ok) == 1
    assert calls == []                                     # モデルが違えば何も作らずに止める
    t = sec / "L1-1-1_座学_x_transcript.md"
    t.write_text(t.read_text(encoding="utf-8").replace("二枚目です。", "二枚目を直しました。"), encoding="utf-8")
    assert _run_lecture(monkeypatch, tmp_path, ["--model", "m1"], ok) == 0
    assert calls == ["speech_02.wav"]                      # 直した区間だけ作り直す


# ---------------------------------------------------------------- 完成動画の検査
def test_empty_runs_counts_only_long_blank_stretches():
    from empty_frames import empty_runs
    ink = [0.1] * 3 + [0.0] * 12 + [0.1] * 2 + [0.0] * 5 + [0.0] * 0
    assert empty_runs(ink, min_ink=0.004, run=10) == [(3, 15)]
    assert empty_runs([0.0] * 10, run=10) == [(0, 10)]        # 末尾まで続く空白も数える


def test_longest_still_per_slide():
    from still_report import longest_still
    # 2fps。スライド1 = 0〜5秒（10フレーム）、スライド2 = 5〜10秒
    moving = [None] + [True] * 9 + [False] * 8 + [True, True]
    rows = longest_still(moving, [(1, 0.0, 5.0), (2, 5.0, 10.0)])
    assert rows[0]["still"] == 0.0
    assert rows[1]["still"] == 3.5          # 切り替わりの1フレームは数えない


def test_final_sweep_problem_rules():
    from final_sweep import SPEC, problems_of
    ok = {"name": "a", "spec": SPEC, "v_s": 10.0, "a_s": 10.0, "s": 10.0, "expected_s": 10.0,
          "lufs": -16.0, "black_n": 0, "cue_interp": None}
    loud = dict(ok, name="b", lufs=-12.0)
    black = dict(ok, name="c", black_n=1, black_max=0.8)
    stale = dict(ok, name="d", s=14.0, cue_interp=2)
    found = {(n, m.split()[0]) for n, m in problems_of([ok, ok, ok, loud, black, stale])}
    assert ("b", "音量") in found and ("c", "黒フレーム") in found
    assert ("d", "尺が") in found and ("d", "補間に落ちた") in found
    assert not [p for p in problems_of([ok, ok]) if p[0] == "a"]


def _timing(tmp_path, cues, sentences):
    import json
    d = tmp_path / "L1_x_audio"
    d.mkdir()
    p = d / "_timing.json"
    p.write_text(json.dumps({"slides": {"2": {"cues": cues, "sentences": sentences}}}, ensure_ascii=False),
                 encoding="utf-8")
    return p


def test_cue_report_counts_interpolated(tmp_path):
    from cue_report import collect, main
    p = _timing(tmp_path, [{"cue": "最初の一節です", "start": 1.0, "matched": True},
                           {"cue": "落ちた一節です", "start": 5.0, "matched": False}], [])
    rows = collect([p])
    assert rows[0]["total"] == 2 and len(rows[0]["unmatched"]) == 1
    assert main([str(p)]) == 1


def test_cue_drift_finds_a_match_in_the_wrong_sentence(tmp_path):
    from cue_drift import drifts, main
    import json
    sentences = [{"text": "仮想ネットワークを作ります。", "start": 2.0},
                 {"text": "サブネットを分けます。", "start": 30.0}]
    good = _timing(tmp_path, [{"cue": "仮想ネットワークを作ります", "start": 2.4, "matched": True}], sentences)
    assert main([str(good)]) == 0
    doc = json.loads(good.read_text(encoding="utf-8"))
    doc["slides"]["2"]["cues"][0]["start"] = 29.5             # 別の文に「一致」した
    assert drifts(doc)[0]["diff"] == 27.5


def test_qa_scripts_run_on_a_real_mp4(tmp_path):
    """ffmpeg がある環境だけ：白一色の動画は「空」、仕様が違う動画は異常として出る。"""
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg が無い")
    mp4 = tmp_path / "blank.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=white:s=640x360:d=12:r=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(mp4)], check=True)
    from empty_frames import main as ef
    from final_sweep import main as fs
    assert ef([str(mp4), "--run", "10"]) == 1
    assert fs([str(mp4)]) == 1                                 # 640x360・モノラルは仕様外


# ---------------------------------------------------------------- 実践：OCR の黒塗りと点検
RULES = {
    "words": [{"pattern": r"taro|example\.com"},
              {"pattern": "sub-name", "pad": [-60, -3, 6, 3], "template": True}],
    "label_value": [{"pattern": r"サブスクリプション\s*ID", "width": 300}],
    "fixed_boxes": [{"box": [1100, 0, 1300, 40], "except": "^S9"}],
    "guid": {"enabled": True, "keep": ["beef"]},
    "price": True,
    "check": {"extra": ["/subscriptions/"]},
}


def test_ocr_mask_boxes_follow_the_rules():
    from ocr_mask import boxes_for, compile_rules
    r = compile_rules(RULES)
    words = [([100, 10, 200, 30], "taro@example.com"),
             ([100, 50, 220, 70], "サブスクリプション ID"),
             ([100, 90, 500, 110], "id: abcd1234-1111-2222-3333-444455556666 end"),
             ([100, 130, 300, 150], "flowlog beef0000-1111-2222-"),
             ([100, 170, 200, 190], "$12.34/month")]
    boxes = boxes_for("S001.jpg", words, r)
    assert [1100, 0, 1300, 40] in boxes                       # 固定の箱
    assert [96, 7, 204, 33] in boxes                           # 語の箱を pad だけ広げる
    assert [224, 46, 524, 74] in boxes                         # ラベルの右の値
    guid = [b for b in boxes if b[1] == 87]
    assert len(guid) == 1 and guid[0][0] > 100 and guid[0][2] < 500   # GUID の部分だけ
    assert not [b for b in boxes if b[1] == 127]               # keep の GUID は残す
    assert [96, 167, 204, 193] in boxes                        # 金額
    assert [1100, 0, 1300, 40] not in boxes_for("S901.jpg", [], r)   # except に当たる枚は外す


def test_leak_check_uses_the_same_rules():
    from ocr_mask import compile_rules, leak_hits
    r = compile_rules(RULES)
    words = [([0, 0, 1, 1], "taro"), ([0, 0, 1, 1], "/subscriptions/x"), ([0, 0, 1, 1], "ok"),
             ([0, 0, 1, 1], "beef0000-1111-2222-")]
    assert leak_hits("S001.jpg", words, r) == ["taro", "/subscriptions/x"]


def test_leak_rules_example_parses():
    from pathlib import Path
    from ocr_mask import load_rules
    p = Path(__file__).resolve().parents[1] / "plugins/udemy-video-course/templates/leak_rules.example.yaml"
    r = load_rules(p)
    assert r["words"] and r["label_value"] and r["guid"] and r["price"]


def test_render_frames_adds_ocr_masks(tmp_path, monkeypatch):
    import json
    from PIL import Image
    (tmp_path / "raw").mkdir()
    Image.new("RGB", (100, 60), "white").save(tmp_path / "raw" / "S001.jpg")
    (tmp_path / "recipe.json").write_text(json.dumps([{"src": "S001.jpg", "out": "r01.jpg"}]), encoding="utf-8")
    (tmp_path / "masks.json").write_text(json.dumps({"S001.jpg": [[10, 10, 40, 30]]}), encoding="utf-8")
    import render_frames
    monkeypatch.setattr("sys.argv", ["render_frames.py", "--work", str(tmp_path)])
    assert render_frames.main() == 0
    im = Image.open(tmp_path / "frames" / "r01.jpg").convert("L")
    assert im.getpixel((25, 20)) < 40 and im.getpixel((80, 50)) > 200


# ---------------------------------------------------------------- 実践：取り込みと窓の大きさ
def test_fit_crop_rejects_resizing():
    from ingest_shot import fit_crop
    assert fit_crop((1350, 703), (1350, 703), 2) == (0, 0, 1350, 703)
    assert fit_crop((1350, 704), (1350, 703), 2) == (0, 0, 1350, 703)
    assert fit_crop((1070, 415), (1350, 703), 2) is None       # 小さい枚は拡大しない
    assert fit_crop((2109, 1098), (1350, 703), 2) is None      # 大きい枚も縮めない


def test_solve_window_reproduces_measured_points():
    """実測の2点（DPR 1.5625 の画面）から、表示領域 1350x703 になる窓の大きさを出す。"""
    from ingest_shot import solve_window
    samples = [((1700, 1063), (1350, 703)), ((1350, 703), (1070, 415))]
    assert solve_window(samples, (1350, 703)) == (1700, 1063)


def test_ingest_records_only_matching_shots(tmp_path):
    from PIL import Image
    from ingest_shot import main
    shots = tmp_path / "shots"
    shots.mkdir()
    Image.new("RGB", (1350, 703), "white").save(shots / "a.jpg")
    work = tmp_path / "work"
    assert main(["add", "--work", str(work), "--from", str(shots), "--expect", "1350x703", "rec_01", "一覧"]) == 0
    Image.new("RGB", (1070, 415), "white").save(shots / "b.jpg")
    assert main(["add", "--work", str(work), "--from", str(shots / "b.jpg"), "--expect", "1350x703", "rec_02"]) == 1
    assert sorted(p.name for p in (work / "raw").iterdir()) == ["S001.jpg"]
    assert (work / "shots.tsv").read_text(encoding="utf-8").startswith("S001\trec_01\t")


# ---------------------------------------------------------------- practice_movie build の音声フェーズ
def _practice(tmp_path):
    sec = tmp_path / "lectures" / "02_y"
    sec.mkdir(parents=True)
    t = sec / "L2-1-3_実践_y_transcript_rec.md"
    t.write_text("## スライド1: 表紙\n\n始めます。\n\n## 録画1 [00:00-00:10]: 一覧\n\n一覧を開きます。\n",
                 encoding="utf-8")
    return sec, t


def _run_practice(monkeypatch, transcript, argv, synth):
    import practice_movie
    monkeypatch.setattr(practice_movie.deps, "preflight", lambda groups, **k: None)
    monkeypatch.setattr(practice_movie.lm, "synthesize_speech_file", synth)
    args = practice_movie.build_parser().parse_args(["build", str(transcript), "--audio-only", *argv])
    return args.func(args)


def _writer(calls):
    def ok(**kw):
        calls.append(kw["out_wav"].name)
        kw["out_wav"].parent.mkdir(parents=True, exist_ok=True)
        kw["out_wav"].write_bytes(b"RIFF")
    return ok


def test_practice_tts_failure_returns_nonzero(monkeypatch, tmp_path):
    _, t = _practice(tmp_path)

    def boom(**kw):
        raise RuntimeError("503")
    assert _run_practice(monkeypatch, t, [], boom) == 1


def test_practice_legacy_manifest_stops_until_adopted(monkeypatch, tmp_path):
    """モデルの記録が無い古い manifest（値が本文のハッシュだけ）は、何も作らずに止まる。"""
    import json
    from audio_manifest import text_digest
    sec, t = _practice(tmp_path)
    adir = sec / "L2-1-3_実践_y_audio_rec"
    adir.mkdir()
    for k in ("slide_01", "rec_01"):
        (adir / f"{k}.wav").write_bytes(b"RIFF")
    (adir / ".manifest.json").write_text(json.dumps(
        {"slide_01": text_digest("始めます。"), "rec_01": text_digest("一覧を開きます。")}), encoding="utf-8")
    calls = []
    assert _run_practice(monkeypatch, t, ["--model", "m1"], _writer(calls)) == 1
    assert calls == []
    assert _run_practice(monkeypatch, t, ["--model", "m1", "--adopt-existing"], _writer(calls)) == 0
    assert calls == []
    assert _run_practice(monkeypatch, t, ["--model", "m1"], _writer(calls)) == 0   # 記録したので通る
    assert _run_practice(monkeypatch, t, ["--model", "m2"], _writer(calls)) == 1   # 別のモデルは止まる
    assert calls == []


# ---------------------------------------------------------------- check_clicks
def test_embedded_wav_header_is_a_click():
    """ヘッダ付きの WAV をそのまま連結すると、44 バイトがサンプルとして鳴る。"""
    import struct
    from check_clicks import data_offset, head_problems
    hdr = b"RIFF" + struct.pack("<I", 36 + 400) + b"WAVE" + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 24000, 48000, 2, 16) \
        + b"data" + struct.pack("<I", 400)
    assert data_offset(hdr + bytes(400)) == 44
    assert head_problems("x.wav", hdr + bytes(400))
    assert not head_problems("x.wav", bytes(44) + bytes(400))          # ゼロで埋めた形は通る


def test_click_is_found_only_at_the_clip_start():
    from check_clicks import peaks_at
    s = [0] * 48000
    s[24000] = 20000                                                    # 0.5 秒にクリック
    got = dict(peaks_at(s, [0.5, 0.8]))
    assert got[0.5] == 20000 and got[0.8] == 0


# ---------------------------------------------------------------- hira_check
def test_hira_windows_overlap_and_reach_the_end():
    from hira_check import windows
    w = windows(20.0)
    assert w[0] == (0.0, 9.0) and w[-1][1] == 20.0
    assert all(b > c for (_, b), (c, _) in zip(w, w[1:]))              # 隣の窓と重なる
    assert windows(5.0) == [(0.0, 5.0)]


def test_hira_narrow_passes_unless_the_wrong_reading_is_the_majority():
    """疑う読みが半分以下なら通す（STT の揺れで録り直さない）。"""
    from hira_narrow import count_readings, suspicious
    c = count_readings(["しゅちょう する", "しちょうする", "しゅちょうを", "べつの"], ["しゅちょう", "しちょう"])
    assert c == {"しゅちょう": 2, "しちょう": 1}
    assert not suspicious(c, "しゅちょう")
    assert suspicious({"しゅちょう": 1, "しちょう": 2}, "しゅちょう")
    assert not suspicious({"しゅちょう": 1, "しちょう": 1}, "しゅちょう")   # 同数は通す
    assert not suspicious({"しゅちょう": 0, "しちょう": 0}, "しゅちょう")


# ---------------------------------------------------------------- udemy_quiz_payload
def test_quiz_payload_shape():
    import json
    from udemy_quiz_payload import body, problems
    q = {"id": "Q1", "question": "次のうち正しいものは？\n- ア **A**\n- イ B", "options": ["ア", "イ", "両方"],
         "correct": 1, "explanation": "イが正しい。"}
    assert not problems(q)
    b = body(q)
    assert b["assessment_type"] == "multiple-choice"
    assert json.loads(b["correct_response"]) == ["b"]
    assert "<ul>" in b["question"] and "**" not in b["question"]
    fb = json.loads(b["feedbacks"])
    assert fb[1].startswith("<p>正解です。</p>") and fb[0].startswith("<p>不正解です。</p>")
    assert len(json.loads(b["answers"])) == 3


def test_quiz_payload_rejects_broken_questions():
    from udemy_quiz_payload import problems
    assert problems({"question": "q", "options": ["a"], "correct": 0, "explanation": "e"})
    assert problems({"question": "q", "options": ["a", "b"], "correct": 2, "explanation": "e"})
    assert problems({"question": "q", "options": ["a", "b"], "correct": 0, "explanation": ""})


# ---------------------------------------------------------------- udemy_file_server
def test_file_server_serves_only_inside_the_root(tmp_path):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from udemy_file_server import make_handler
    (tmp_path / "01").mkdir()
    (tmp_path / "01" / "002_b.mp4").write_bytes(b"BB")
    (tmp_path / "01" / "001_a.mp4").write_bytes(b"A")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        import json
        lst = json.loads(urllib.request.urlopen(base + "/list/01").read())
        assert [x["name"] for x in lst] == ["001_a.mp4", "002_b.mp4"]   # 名前の昇順＝講義の順
        r = urllib.request.urlopen(base + "/f/01/2")
        assert r.read() == b"BB" and r.headers["Access-Control-Allow-Private-Network"] == "true"
        with pytest.raises(Exception):
            urllib.request.urlopen(base + "/f/01/..%2f..%2fsecret")
    finally:
        srv.shutdown()


def test_file_server_accepts_a_second_lecture_folder(tmp_path):
    """同じ章の2本目のレクチャーは 08b のように置く（GH-300）。"""
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from udemy_file_server import make_handler
    (tmp_path / "08b").mkdir()
    (tmp_path / "08b" / "01_x.mp4").write_bytes(b"X")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert [x["name"] for x in json.loads(urllib.request.urlopen(base + "/list/08b").read())] == ["01_x.mp4"]
        assert urllib.request.urlopen(base + "/f/08b/1").read() == b"X"
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- udemy_quiz_payload（原稿から）
QUIZ_MD = """# [L1-1] 小テスト（原稿）

> 作り方のメモ。Udemy には入れない

## 作り方の約束

- 軸の表など

## 問題

### Q1

あなたは、`git` を使っています。正しいものはどれですか？

- A. **太字**の選択肢
- B. 正しい選択肢 ← **正解**
- C. ほかの選択肢
- D. 最後の選択肢

**解説**：Bは正しい。Aは、`x` なので誤りです。

### Q2

二つ目の問いです。

- A. ア ← **正解**
- B. イ

**解説**：アが正しい。

## 保留案

### Q1

重なって入ってはいけない問い

- A. a ← **正解**
- B. b

**解説**：保留。
"""


def test_quiz_markdown_reads_only_the_question_section():
    """「## 問題」の節だけを読む（後ろの「保留案」まで読むと、同じ番号の問いが重なって入った）。"""
    from udemy_quiz_payload import parse_md, problems
    qz = parse_md(QUIZ_MD, slug="L1-1_quiz")
    qs = qz["questions"]
    assert [q["id"] for q in qs] == ["L1-1_quiz-Q1", "L1-1_quiz-Q2"]
    assert qs[0]["correct"] == 1 and len(qs[0]["options"]) == 4
    assert qs[0]["question"].startswith("あなたは")
    assert qs[1]["correct"] == 0
    assert not any(problems(q) for q in qs)


def test_quiz_for_screen_input_drops_markup_but_keeps_words():
    """画面の入力欄は書式なし。** とバッククォートの記号を外し、中の語は残す。"""
    from udemy_quiz_payload import parse_md, to_qs
    q = to_qs(parse_md(QUIZ_MD, slug="s")["questions"][0])
    assert q["a"] == 1
    assert q["s"] == "あなたは、git を使っています。正しいものはどれですか？"
    assert q["o"][0] == "太字の選択肢"
    assert "`" not in q["e"] and "**" not in q["e"] and "x" in q["e"]


# ---------------------------------------------------------------- 音声（指示ファイル・読みの辞書・退避）
def test_style_prompt_is_off_by_default_and_stops_at_the_rule(tmp_path):
    """演技指示は既定で渡さない。渡すときも、最初の --- より前だけ（後ろの運用メモを TTS に渡していた）。"""
    from lecture_movie import load_voice_and_style
    p = tmp_path / "tts-instruction.md"
    p.write_text("Voice: Callirrhoe\n落ち着いた声で話す。\n---\n運用メモ: 演技指示は使わない\n", encoding="utf-8")
    assert load_voice_and_style(p, "Kore") == ("Callirrhoe", "")
    voice, style = load_voice_and_style(p, "Kore", use_style=True)
    assert voice == "Callirrhoe" and style == "落ち着いた声で話す。"
    assert "運用メモ" not in style
    assert load_voice_and_style(tmp_path / "none.md", "Kore") == ("Kore", "")


def test_readings_replace_longer_words_first(tmp_path):
    from lecture_movie import apply_readings, load_readings
    p = tmp_path / "tts-readings.tsv"
    p.write_text("# 表記\t読み\nEsc\tエスク\nEscキー\tエスケープキー  # 2026-10-19 F10 で「えすくきー」\n"
                 "pytest → パイテスト\n", encoding="utf-8")
    r = load_readings(p)
    assert apply_readings("Escキーを押し、pytestを回す。Escだけ。", r) == "エスケープキーを押し、パイテストを回す。エスクだけ。"
    assert load_readings(tmp_path / "none.tsv") == []
    p.write_text("読めない行\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_readings(p)


def test_made_audio_is_backed_up_without_overwriting(tmp_path):
    from lecture_movie import backup_audio
    a = tmp_path / "audio"
    a.mkdir()
    (a / "speech_01.wav").write_bytes(b"1")
    (a / "speech_02.wav").write_bytes(b"2")
    (a / "audio_manifest.json").write_text("{}", encoding="utf-8")
    d1 = backup_audio(a, ["speech_01.wav"], tmp_path / "bk", "L1-1")
    d2 = backup_audio(a, ["speech_02.wav"], tmp_path / "bk", "L1-1")
    assert d1 != d2 and d2.name == "L1-1-2"
    assert sorted(x.name for x in d1.iterdir()) == ["audio_manifest.json", "speech_01.wav"]
    assert backup_audio(a, [], tmp_path / "bk", "L1-1") is None
