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
