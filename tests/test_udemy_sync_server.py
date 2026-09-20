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
