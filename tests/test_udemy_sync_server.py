"""Udemy 編集ヘルパー用の同期サーバー（データ生成部）とヘルパー JS の整合を担保する。

ヘルパーは編集画面の内容を CSV から作った署名と照合するので、Python 側と
JS 側の署名が1文字でもずれると、正しく保存できていても「不一致」になる。
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "udemy-exam-prep"
sys.path.insert(0, str(PLUGIN))

from scripts.udemy_sync_server import build, signature  # noqa: E402
from scripts.validate_quiz_csv import HEADER, write_rows  # noqa: E402


def row(q="What is X?", correct="2", qt="multiple-choice"):
    return [
        q, qt,
        "Option A", "A is wrong.",
        "Option B", "B is right." + chr(10) + "It works because ...",
        "Option C", "C is wrong.",
        "Option D", "D is wrong.",
        "", "", "", "",
        correct, "Summary." + chr(10) + chr(10) + "Source: https://example.com", "Domain 1",
    ]


def test_signature_ignores_repeated_newlines_and_nbsp():
    assert signature("a" + chr(10) * 3 + "b") == signature("a" + chr(10) + "b")
    assert signature("a\u00a0b") == signature("a b")
    assert signature("  a  ") == signature("a")


def test_build_writes_fields_in_the_order_of_the_editor(tmp_path):
    root = tmp_path / "project"
    sec = root / "section01-mock-exam-1"
    sec.mkdir(parents=True)
    write_rows(sec / "quiz.csv", [list(HEADER), row()])
    out = tmp_path / "out"
    report = build(root, "HEAD", out)          # git 管理外なので旧版は現行版で代用される
    assert report == ["section 1: 1 questions"]

    data = json.loads((out / "data" / "s1.json").read_text(encoding="utf-8"))["1"]
    assert data["type"] == "multiple-choice"
    assert data["n"] == 4 and data["correct"] == [2] and data["domain"] == "Domain 1"
    # 質問, (選択肢, 解説) x 4, 全体的な説明
    assert len(data["f"]) == 1 + 4 * 2 + 1
    assert data["f"][0] == "What is X?"
    assert data["f"][4] == "B is right." + chr(10) + "It works because ..."
    assert data["f"][-1].endswith("Source: https://example.com")
    assert data["sig"] == [signature(x) for x in data["f"]]

    before = json.loads((out / "data" / "o1.json").read_text(encoding="utf-8"))["1"]
    assert before["q0"] == data["sig"][0]


def test_multi_select_correct_answers_are_parsed(tmp_path):
    root = tmp_path / "p"
    sec = root / "section02-mock-exam-2"
    sec.mkdir(parents=True)
    write_rows(sec / "quiz.csv", [list(HEADER), row(correct="1,3", qt="multi-select")])
    out = tmp_path / "out"
    build(root, "HEAD", out)
    data = json.loads((out / "data" / "s2.json").read_text(encoding="utf-8"))["1"]
    assert data["correct"] == [1, 3] and data["type"] == "multi-select"


@pytest.mark.skipif(shutil.which("node") is None, reason="node が無い環境では JS 側の署名を確かめられない")
def test_python_signature_matches_the_browser_helper():
    """__u.h（ブラウザ側）と signature（Python 側）が同じ値を返す。"""
    helper = (PLUGIN / "scripts" / "udemy_editor_helper.js").read_text(encoding="utf-8")
    samples = ["abc", "日本語の解説。" + chr(10) + chr(10) + "出典: https://example.com", "a\u00a0b"]
    js = (
        "global.window = {}; global.document = {querySelectorAll: () => []};"
        + helper
        + ";const S=" + json.dumps(samples, ensure_ascii=False)
        + ";console.log(JSON.stringify(S.map(x => window.__u.h(x))))"
    )
    proc = subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [signature(x) for x in samples]


def test_the_skill_documents_both_scripts_and_they_exist():
    text = (PLUGIN / "skills" / "udemy-bulk-upload" / "SKILL.md").read_text(encoding="utf-8")
    for name in ("udemy_sync_server.py",):
        assert name in text and (PLUGIN / "scripts" / name).is_file()
    assert (PLUGIN / "scripts" / "udemy_editor_helper.js").is_file()
    assert "editor-helper.js" in text


# --- ヘルパー JS の実行時の振る舞い ------------------------------------------
#
# 公開中コースの一括書き換えで実際に止まった箇所（再試行なしの runBg、例外で
# 完了フラグが立たない audit、裏タブでの停止）を退行させないための歯止め。

HELPER_JS = PLUGIN / "scripts" / "udemy_editor_helper.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node が無い環境では JS を実行できない")


def run_node(body: str, visibility: str = "visible"):
    """document を最小限に差し替えてヘルパーを読み込み、body（async）の戻り値を JSON で返す。"""
    js = (
        "global.window = global; global.document = {querySelectorAll: () => [], visibilityState: "
        + json.dumps(visibility) + "};"
        + HELPER_JS.read_text(encoding="utf-8")
        + ";const until=async(f)=>{for(let i=0;i<500&&!f();i++)await new Promise(r=>setTimeout(r,2));};"
        + "(async()=>{const out=await (async()=>{" + body + "})();console.log(JSON.stringify(out));})()"
        + ".catch(e=>{console.error(e);process.exit(1);});"
    )
    proc = subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@needs_node
def test_helper_passes_node_syntax_check():
    proc = subprocess.run(["node", "--check", str(HELPER_JS)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@needs_node
def test_helper_exposes_the_documented_api():
    names = ["load", "run", "runBg", "runAll", "jobStatus", "stop", "visible",
             "audit", "auditBg", "auditStatus", "dismiss"]
    got = run_node("return " + json.dumps(names) + ".filter(n => typeof __u[n] !== 'function');")
    assert got == []


@needs_node
def test_run_bg_retries_a_failed_question_with_fast_off():
    got = run_node("""
      __u.retryWait = 0; __u.fast = true; const seen = {};
      __u.run = async q => { seen[q] = (seen[q] || []).concat(__u.fast);
        if (q === 2 && seen[q].length < 3) return JSON.stringify({q, abort: 'align'});
        return JSON.stringify({q, ok: true}); };
      __u.runBg([1, 2, 3]); await until(() => !__job.running);
      return {job: __job, seen, fast: __u.fast};
    """)
    job = got["job"]
    assert job["done"] == 3 and job["stopped"] is None and job["running"] is False
    assert job["retries"] == 2 and [x["abort"] for x in job["log"]] == ["align", "align"]
    assert got["seen"]["2"] == [True, False, False]   # 再試行は通常モード
    assert got["fast"] is True                         # 利用者の設定は戻す


@needs_node
def test_run_bg_stops_after_three_failures_and_catches_exceptions():
    got = run_node("""
      __u.retryWait = 0;
      __u.run = async q => { if (q === 2) throw new Error('boom'); return JSON.stringify({q, ok: true}); };
      __u.runBg([1, 2, 3]); await until(() => !__job.running);
      return __job;
    """)
    assert got["done"] == 2 and got["stopped"]["abort"] == "exc" and got["stopped"]["q"] == 2
    assert len(got["log"]) == 3 and got["retries"] == 2 and got["running"] is False


@needs_node
def test_stop_halts_before_the_next_question():
    got = run_node("""
      __u.retryWait = 0;
      __u.run = async q => { await new Promise(r => setTimeout(r, 20)); return JSON.stringify({q, ok: true}); };
      __u.runBg([1, 2, 3, 4]); await until(() => __job.done >= 1); __u.stop();
      await until(() => !__job.running);
      return {job: __job};
    """)
    job = got["job"]
    assert job["running"] is False and job["stopped"]["abort"] == "stop" and job["done"] < 4


@needs_node
def test_run_bg_refuses_a_second_job_while_running():
    got = run_node("""
      __u.run = async q => { await new Promise(r => setTimeout(r, 20)); return JSON.stringify({q, ok: true}); };
      const first = __u.runBg([1, 2]); const second = __u.runBg([3]);
      await until(() => !__job.running); return [first, second];
    """)
    assert got == ["started 2", "busy"]


@needs_node
def test_audit_bg_survives_exceptions_and_reports_progress():
    got = run_node("""
      __u.auditOne = async q => { if (q === 2) throw new Error('boom');
        return {q, nav: true, sig: q !== 3, cor: true, ty: true}; };
      __u.auditBg(1, 4); await until(() => !__audit.running);
      return JSON.parse(__u.auditStatus());
    """)
    assert got["done"] is True and got["at"] == 4 and got["running"] is False
    assert [x["q"] for x in got["mismatch"]] == [3]
    assert [x["q"] for x in got["err"]] == [2]


@needs_node
def test_hidden_tab_is_recorded_in_the_job():
    got = run_node("""
      __u.run = async q => JSON.stringify({q, ok: true});
      __u.runBg([1, 2]); await until(() => !__job.running);
      return {v: __u.visible(), hidden: __job.hidden.map(h => h.q)};
    """, visibility="hidden")
    assert got == {"v": "hidden", "hidden": [1, 2]}


# --- スキルに残す実測の要点 ----------------------------------------------------

def _skill(name):
    return (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def test_bulk_upload_prefers_claude_in_chrome_and_maps_the_tools():
    text = _skill("udemy-bulk-upload")
    assert "Claude in Chrome を第一手段" in text
    for tool in ("tabs_context_mcp", "javascript_tool", "file_upload", "find"):
        assert tool in text, tool
    assert "トップレベル `await`" in text and "45秒" in text


def test_bulk_upload_documents_the_new_helper_api_and_pitfalls():
    text = _skill("udemy-bulk-upload")
    for api in ("__u.visible()", "__u.stop()", "__u.auditBg", "__u.auditStatus()", "__u.runBg"):
        assert api in text, api
    assert "visibilityState" in text
    assert "1本ずつ・1タブ" in text
    assert "保存せずに離れる" in text
    assert "学習者に更新メッセージを送信" in text


def test_upload_reads_course_meta_before_asking_and_keeps_live_tests():
    text = _skill("upload-practice-tests")
    assert "udemy-course-meta.md" in text and "quizId 対応表" in text
    assert "is_published,status_label" in text
    assert "公開済みのコースでは削除→再作成しない" in text
    assert "更新履歴" in text


# 一括アップロードの URL は素のテキストで保存され、受講者がクリックできなかった。
# 投入後にリンク化する 'link' モードと、照合での未リンク検出を退行させない。

@needs_node
def test_helper_exposes_the_link_api():
    got = run_node("return ['linkify','linkifyAll','linkifyOne','unlinked'].filter(n => typeof __u[n] !== 'function').concat(__u.links === true ? [] : ['links']);")
    assert got == []


@needs_node
def test_run_bg_link_mode_calls_linkify_one_not_run():
    got = run_node("""
      const calls = [];
      __u.run = async q => { calls.push('run' + q); return JSON.stringify({q, ok: true}); };
      __u.linkifyOne = async q => { calls.push('link' + q); return JSON.stringify({q, ok: true, linked: 1}); };
      __u.runBg([1, 2], 'link'); await until(() => !__job.running);
      return {calls, done: __job.done};
    """)
    assert got == {"calls": ["link1", "link2"], "done": 2}


@needs_node
def test_audit_treats_remaining_bare_urls_as_a_mismatch():
    got = run_node("""
      const ok = {sig: true, cor: true, ty: true, nav: true};
      return [__u.bad(Object.assign({unlinked: 0}, ok)), __u.bad(Object.assign({unlinked: 2}, ok)), __u.bad(ok)];
    """)
    assert got == [False, True, False]


@needs_node
def test_url_pattern_stops_at_japanese_punctuation_and_trailing_dots():
    got = run_node("""
      const f = s => (s.match(__u._urlRe()) || []).map(u => __u._trimUrl(u));
      return [f('出典: https://example.com/a/b'), f('（https://example.com/x）を参照。'), f('see https://example.com/y.')];
    """)
    assert got == [["https://example.com/a/b"], ["https://example.com/x"], ["https://example.com/y"]]


def test_skills_require_linking_source_urls_after_bulk_upload():
    bulk = _skill("udemy-bulk-upload")
    assert "投入後に出典 URL をリンクにする" in bulk and "runBg([1, 2, ..., N], 'link')" in bulk
    assert "CSV に `<a href>` を書かない" in bulk
    assert "出典 URL をリンクにする" in _skill("upload-practice-tests")
    assert "素の URL のまま" in _skill("quiz-csv-format")
