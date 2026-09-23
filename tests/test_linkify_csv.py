"""linkify_csv.py と、<a href> を許すタグ検査。

素の URL のまま一括アップロードすると出典がテキストで保存され、受講者がクリックできなかった。
CSV に <a href> を書けばリンクとして保存されることを公開中の講座で確かめたので、
投入用 CSV を作るスクリプトと検査の緩和を退行させない。
"""
from pathlib import Path

from scripts.linkify_csv import linkify_rows, linkify_text
from scripts.validate_quiz_csv import HEADER, validate_csv, write_rows

U = "https://learn.example.com/docs/page"


def test_links_only_urls_on_source_lines():
    text = f"本文でスコープ https://ai.example.com/.default を指定する。\n\n出典: {U}"
    out = linkify_text(text)
    assert out.endswith(f'出典: <a href="{U}">{U}</a>')
    assert "https://ai.example.com/.default を指定" in out          # 本文の URL はそのまま


def test_multiple_sources_and_trailing_punctuation():
    out = linkify_text(f"出典: {U}, {U}/b.")
    assert out == f'出典: <a href="{U}">{U}</a>, <a href="{U}/b">{U}/b</a>.'


def test_does_not_swallow_following_japanese_and_keeps_existing_anchor():
    assert linkify_text(f"参考：{U}を参照") == f'参考：<a href="{U}">{U}</a>を参照'
    already = f'出典: <a href="{U}">{U}</a>'
    assert linkify_text(already) == already


def _row(overall):
    return ["Q?", "multiple-choice", "A", "正解です。", "B", "不正解です。",
            "", "", "", "", "", "", "", "", "1", overall, "D1"]


def test_rows_keep_domain_and_visible_text():
    rows = [list(HEADER), _row(f"要約。\n\n出典: {U}")]
    linked, n = linkify_rows(rows)
    assert n == 1 and linked[1][16] == "D1"
    assert linked[1][15].replace(f'<a href="{U}">', "").replace("</a>", "") == rows[1][15]


def test_validator_accepts_anchor_but_still_rejects_bare_tags(tmp_path: Path):
    ok = tmp_path / "ok.csv"
    write_rows(ok, [list(HEADER), _row(f'要約。\n\n出典: <a href="{U}">{U}</a>')])
    assert not [e for e in validate_csv(ok) if "tag-like" in e]
    ng = tmp_path / "ng.csv"
    write_rows(ng, [list(HEADER), _row(f"<role> と <output> を使う\n\n出典: {U}")])
    assert any("tag-like" in e for e in validate_csv(ng))
