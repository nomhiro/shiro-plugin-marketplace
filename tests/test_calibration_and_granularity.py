"""出題傾向の校正とレビュー後の保護に関わる検査の検証。

いずれも、ある講座（2ドメイン・6本300問）の作問と精読で実際に踏んだ事故への歯止め。

1. シナリオ率の上限と本の種類ごとの範囲（scenario_ratio）
   下限しか無く、フル模試1本目がシナリオ率 88% のまま通った。drill は高くてよい。
2. multi-select の「正解肢が全部最長」を既定で FAIL にする
   件数が「参考」表示だけだったため、作問のたびに1〜4問残った。
3. 粒度（上限値・課金・API の版）の WARN
4. 精読済みの本（.reviewed）への --force 結合の拒否と --dry-run
5. quiz.csv 単体の空白の正規化
"""
import pytest

from scripts import check_granularity, check_option_balance, check_scenario_ratio
from scripts.merge_parts import REVIEWED_MARKER, merge
from scripts.normalize_spacing import normalize_file
from scripts.profile import parse_ratio, scenario_bounds, validate_profile
from scripts.validate_quiz_csv import HEADER, read_rows, write_rows

TAB = chr(9)
NL = chr(10)


# --- 1. シナリオ率の範囲 -------------------------------------------------------

def test_parse_ratio_accepts_percent_fraction_and_integer():
    assert parse_ratio("60%") == pytest.approx(0.6)
    assert parse_ratio(0.6) == pytest.approx(0.6)
    assert parse_ratio(60) == pytest.approx(0.6)
    assert parse_ratio(None) is None and parse_ratio("") is None


def test_scenario_bounds_prefers_section_then_kind_then_global():
    profile = {
        "scenario_ratio_min": "30%",
        "scenario_ratio": {"mock": {"min": "55%", "max": "65%"}},
    }
    assert scenario_bounds(profile, {"kind": "mock"}) == pytest.approx((0.55, 0.65))
    # drill は種類ごとの指定が無いので全体の下限だけ（上限なし）
    lo, hi = scenario_bounds(profile, {"kind": "drill"})
    assert lo == pytest.approx(0.30) and hi is None
    # 本ごとの指定が最優先
    spec = {"kind": "mock", "scenario_ratio": {"max": "70%"}}
    assert scenario_bounds(profile, spec) == pytest.approx((0.55, 0.70))


def test_validate_profile_rejects_malformed_scenario_ratio():
    base = {
        "cert": "X", "cert_name": "X", "vendor": "generic",
        "exam": {"minutes": 60, "pass_score": 700, "max_score": 1000, "language": "ja"},
        "mock_exams": 1, "questions_per_exam": 2,
        "domains": [{"id": "D1", "name": "A", "ratio": "100%", "per_exam": 2}],
    }
    bad = dict(base, scenario_ratio={"mock": {"max": "abc"}})
    assert any("scenario_ratio.mock.max" in e for e in validate_profile(bad))
    bad2 = dict(base, scenario_ratio_max="150%")
    assert any("scenario_ratio_max" in e for e in validate_profile(bad2))
    ok = dict(base, scenario_ratio={"mock": {"min": "55%", "max": "65%"}})
    assert not [e for e in validate_profile(ok) if "scenario_ratio" in e]


def _bank(section, scenarios):
    parts = section / "_parts"
    parts.mkdir(parents=True, exist_ok=True)
    lines = [
        f"| {section.name[:9]} | Q{i} | D1 | 1.1 | 概念{i} | {s} | 問題{i} |"
        for i, s in enumerate(scenarios, 1)
    ]
    (parts / "bank-rows.md").write_text(NL.join(lines) + NL, encoding="utf-8")


def _mixed_profile():
    return {
        "mode": "mixed",
        "domains": [{"id": "D1", "name": "A", "ratio": "100%", "per_exam": 10}],
        "questions_per_exam": 10,
        "scenario_ratio_min": "30%",
        "scenario_ratio": {"mock": {"min": "55%", "max": "65%"}},
        "sections": [
            {"slug": "section01-drill-1", "title": "d", "kind": "drill",
             "questions": 10, "minutes": 10},
            {"slug": "section02-mock-exam-1", "title": "m", "kind": "mock",
             "questions": 10, "minutes": 10},
        ],
    }


def test_mock_with_too_many_scenarios_fails(tmp_path):
    sec = tmp_path / "section02-mock-exam-1"
    _bank(sec, ["S-a"] * 9 + ["knowledge"])            # 90%
    verdict, msg = check_scenario_ratio.check(sec, _mixed_profile())
    assert verdict == "FAIL" and "上限" in msg


def test_mock_inside_the_range_passes(tmp_path):
    sec = tmp_path / "section02-mock-exam-1"
    _bank(sec, ["S-a"] * 6 + ["knowledge"] * 4)        # 60%
    assert check_scenario_ratio.check(sec, _mixed_profile())[0] == "OK"


def test_drill_may_have_a_high_scenario_ratio(tmp_path):
    sec = tmp_path / "section01-drill-1"
    _bank(sec, ["S-a"] * 10)                            # 100%
    assert check_scenario_ratio.check(sec, _mixed_profile())[0] == "OK"


def test_no_range_is_a_skip(tmp_path):
    sec = tmp_path / "section01-drill-1"
    _bank(sec, ["S-a"] * 10)
    prof = _mixed_profile()
    prof.pop("scenario_ratio_min")
    prof.pop("scenario_ratio")
    assert check_scenario_ratio.check(sec, prof)[0] == "SKIP"


# --- 2. 正解肢が全部最長 -------------------------------------------------------

def _ms_row(opts, correct):
    r = ["問題文?", "multi-select"]
    for i in range(6):
        if i < len(opts):
            mark = "正解" if (i + 1) in correct else "不正解"
            r += [opts[i], f"{mark}です。説明"]
        else:
            r += ["", ""]
    r += [",".join(map(str, correct)), "全体の説明", "Domain"]
    return r


def _write(tmp_path, rows):
    p = tmp_path / "quiz.csv"
    write_rows(p, [list(HEADER)] + rows)
    return str(p)


def test_all_longest_multi_select_fails_even_with_a_small_margin(tmp_path, capsys):
    # 最短の正解肢(41) > 最長の誤答肢(39)。margin は +5% で上限 +20% には届かない
    opts = ["あ" * 41, "い" * 47, "う" * 38, "え" * 39]
    path = _write(tmp_path, [_ms_row(opts, [1, 2])])
    assert check_option_balance.main(["x", path]) == 1
    assert "正解肢が全部最長" in capsys.readouterr().out


def test_all_longest_can_be_downgraded_to_warn_or_off(tmp_path, capsys):
    opts = ["あ" * 41, "い" * 47, "う" * 38, "え" * 39]
    path = _write(tmp_path, [_ms_row(opts, [1, 2])])
    assert check_option_balance.main(["x", path, "--ms-all-longest", "warn"]) == 0
    assert "WARN" in capsys.readouterr().out
    assert check_option_balance.main(["x", path, "--ms-all-longest", "off"]) == 0


def test_a_longer_distractor_clears_the_all_longest_check(tmp_path):
    opts = ["あ" * 41, "い" * 47, "う" * 38, "え" * 44]
    path = _write(tmp_path, [_ms_row(opts, [1, 2])])
    assert check_option_balance.main(["x", path]) == 0


def test_short_bare_names_are_exempt_from_all_longest(tmp_path):
    opts = ["prebuilt-invoice", "prebuilt-receipt", "OCR", "Face"]
    path = _write(tmp_path, [_ms_row(opts, [1, 2])])
    assert check_option_balance.main(["x", path]) == 0


# --- 3. 粒度 -------------------------------------------------------------------

def _mc_row(question, options, correct=1):
    r = [question, "multiple-choice"]
    for i in range(6):
        if i < len(options):
            mark = "正解" if i + 1 == correct else "不正解"
            r += [options[i], f"{mark}です。説明"]
        else:
            r += ["", ""]
    r += [str(correct), "全体の説明", "Domain"]
    return r


def test_granularity_flags_limits_and_api_versions(tmp_path):
    rows = [
        _mc_row("1 回の呼び出しで渡せる画像は何枚までか。", ["20 枚まで", "10 枚まで"]),
        _mc_row("正しい記述はどれか。", ["リクエストに api-version を付ける", "付けない"]),
        _mc_row("文章の感情を判定する機能はどれか。", ["感情分析", "キーフレーズ抽出"]),
    ]
    hits = check_granularity.scan(_write(tmp_path, rows), check_granularity.granularity_config(None))
    assert [h.split()[0] for h in hits] == ["Q1", "Q2"]


def test_granularity_ignores_limits_that_only_appear_in_distractors_or_explanations(tmp_path):
    r = _mc_row("文章の要約を作る機能はどれか。", ["要約", "上限は 10 件まで"])
    r[15] = "補足: 1 回あたり 10 件まで送れます。"
    hits = check_granularity.scan(_write(tmp_path, [r]), check_granularity.granularity_config(None))
    assert hits == []


def test_granularity_allow_list_and_severity(tmp_path, monkeypatch):
    rows = [_mc_row("temperature は 0 から 2 まで。上限は 2 である。正しいものは。", ["2 回まで", "b"])]
    path = _write(tmp_path, rows)
    cfg = check_granularity.granularity_config({"granularity": {"allow": ["temperature"]}})
    assert check_granularity.scan(path, cfg) == []
    cfg = check_granularity.granularity_config({"granularity": {"severity": "fail"}})
    assert cfg["severity"] == "fail" and check_granularity.scan(path, cfg)


# --- 4. 精読済みの本の保護と --dry-run ----------------------------------------

def _row(n, text="本文"):
    r = [f"問題 {n}?", "multiple-choice"]
    for i in range(4):
        mark = "正解" if i == 0 else "不正解"
        r += [f"候補 {chr(65 + i)}", f"{mark}です。{text}"]
    r += ["", "", "", ""]
    r += ["1", f"{text} 出典: https://example.com/a", "Domain 1"]
    return r


def _profile2():
    return {
        "mode": "mock-exam", "mock_exams": 1, "questions_per_exam": 2,
        "domains": [{"id": "D1", "name": "Domain 1", "ratio": "100%", "per_exam": 2}],
    }


def _parts(section, rows_):
    parts = section / "_parts"
    parts.mkdir(parents=True, exist_ok=True)
    write_rows(parts / "D1.csv", [list(HEADER)] + rows_)
    meta = [TAB.join([str(i), "D1", "1.1", f"概念{i}", "S1", r[0]]) for i, r in enumerate(rows_, 1)]
    (parts / "D1-meta.tsv").write_text(NL.join(meta) + NL, encoding="utf-8", newline=NL)


def _reviewed_section(tmp_path):
    sec = tmp_path / "section01-mock-exam-1"
    rows_ = [_row(1), _row(2)]
    _parts(sec, rows_)
    merge(sec, _profile2(), keep_parts=True)
    # 精読の修正は quiz.csv にだけ入る
    body = read_rows(sec / "quiz.csv")
    body[1][3] = "正解です。精読で直した説明"
    write_rows(sec / "quiz.csv", body)
    write_rows(sec / "quiz.raw.csv", [list(HEADER)] + rows_)
    (sec / REVIEWED_MARKER).write_text("2026-09-28", encoding="utf-8")
    return sec


def test_force_merge_is_refused_on_a_reviewed_section(tmp_path):
    sec = _reviewed_section(tmp_path)
    with pytest.raises(SystemExit):
        merge(sec, _profile2(), keep_parts=True, force=True)
    assert "精読で直した説明" in read_rows(sec / "quiz.csv")[1][3]


def test_discard_review_edits_is_the_explicit_escape_hatch(tmp_path):
    sec = _reviewed_section(tmp_path)
    merge(sec, _profile2(), keep_parts=True, force=True, discard_review=True)
    assert "精読で直した説明" not in read_rows(sec / "quiz.csv")[1][3]


def test_dry_run_writes_nothing(tmp_path):
    sec = _reviewed_section(tmp_path)
    before = (sec / "quiz.csv").read_bytes()
    bank = sec / "_parts" / "bank-rows.md"
    bank_before = bank.read_bytes()
    result = merge(sec, _profile2(), keep_parts=True, dry_run=True)
    assert result["dry_run"] and result["lost"]
    assert (sec / "quiz.csv").read_bytes() == before
    assert bank.read_bytes() == bank_before


# --- 5. quiz.csv 単体の空白の正規化 -------------------------------------------

def test_normalize_spacing_on_a_quiz_csv(tmp_path):
    rows = [_row(1, "Widget の設定は API で行う。"), _row(2, "Widgetの設定はAPIで行う。"),
            _row(3, "Widget の値は v2 で送る。")]
    path = tmp_path / "quiz.csv"
    write_rows(path, [list(HEADER)] + rows)
    maj, n = normalize_file(path, check=True)
    assert maj == "spaced" and n > 0
    assert "Widgetの設定" in read_rows(path)[2][3]          # check は書き込まない
    normalize_file(path)
    assert "Widget の設定は API で行う" in read_rows(path)[2][3]
    assert read_rows(path)[2][14] == "1"                     # 正解は動かない
