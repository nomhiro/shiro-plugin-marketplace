"""Udemy の問題エディタを書き換えるヘルパー用の同期サーバー。

`quiz.csv` から問題データと署名を作り、127.0.0.1 だけに配る（CORS 許可）。
ブラウザ側は `udemy_editor_helper.js`（このサーバーが /editor-helper.js として配る）で
問題を1問ずつ書き換え、保存内容を CSV の署名と照合する。

配信するもの:
    /editor-helper.js  ブラウザ用ヘルパー
    /data/s<N>.json    新しい内容（fields=編集欄の順の全文, sig=署名, correct, type, n, domain）
    /data/o<N>.json    Udemy に現在載っている版の問題文の署名（位置合わせ用）。
                       --old-ref の git リビジョンの quiz.csv から作る。直近の同期が
                       未コミットなら、その直前のコミットを指定する。

fields の並びは 質問, (選択肢, 解説) x n, 全体的な説明。署名は udemy_editor_helper.js の
__u.h と同じ [長さ:djb2]（連続改行は1つに正規化）。

使い方（バックグラウンドで起動し、終わったら停止する）:
    python "${CLAUDE_PLUGIN_ROOT}/scripts/udemy_sync_server.py" <project_root> --old-ref HEAD
"""
from __future__ import annotations

import argparse
import csv
import http.server
import io
import json
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
from pathlib import Path

# 直接実行でも兄弟モジュールを解決できるようにする。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import safe_stdout  # noqa: E402

HELPER = Path(__file__).resolve().parent / "udemy_editor_helper.js"


def signature(text: str) -> str:
    """ブラウザ側 __u.h と同じ署名。"""
    t = re.sub(r"\n+", "\n", text.replace("\u00a0", " ").replace("\r", "")).strip()
    v = 5381
    for ch in t:
        v = ((v * 33) ^ ord(ch)) & 0xFFFFFFFF
    return f"{len(t)}:{v}"


def parse(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline="")))


def build(root: Path, old_ref: str, out: Path) -> list[str]:
    (out / "data").mkdir(parents=True, exist_ok=True)
    report = []
    for path in sorted(root.glob("section0*/quiz.csv")):
        rel = path.relative_to(root).as_posix()
        sec = int(re.search(r"section0*(\d+)-", rel).group(1))
        rows = parse(path.read_text(encoding="utf-8-sig"))
        old = subprocess.run(["git", "-C", str(root), "show", f"{old_ref}:{rel}"],
                             capture_output=True)
        old_rows = parse(old.stdout.decode("utf-8-sig")) if old.returncode == 0 else rows
        data, before = {}, {}
        for q in range(1, len(rows)):
            r = rows[q]
            n = sum(1 for i in range(6) if r[2 + i * 2].strip())
            fields = [r[0]]
            for i in range(n):
                fields += [r[2 + i * 2], r[3 + i * 2]]
            fields.append(r[15])
            data[str(q)] = {
                "type": r[1], "n": n, "f": fields,
                "sig": [signature(x) for x in fields],
                "correct": [int(c) for c in r[14].split(",") if c.strip()],
                "domain": r[16].strip(),
            }
            if q < len(old_rows):
                before[str(q)] = {"q0": signature(old_rows[q][0])}
        for name, obj in ((f"s{sec}.json", data), (f"o{sec}.json", before)):
            (out / "data" / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        report.append(f"section {sec}: {len(data)} questions")
    return report


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="quiz.csv を Udemy エディタ用に配信する")
    ap.add_argument("root", help="プロジェクトのルート（section0N-*/quiz.csv がある場所）")
    ap.add_argument("--old-ref", default="HEAD", help="Udemy に載っている版の git リビジョン")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv[1:])

    out = Path(tempfile.mkdtemp(prefix="udemy-sync-"))
    shutil.copy(HELPER, out / "editor-helper.js")
    for line in build(Path(args.root).resolve(), args.old_ref, out):
        print(line)
    handler = lambda *a, **k: Handler(*a, directory=str(out), **k)  # noqa: E731
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as srv:
        print(f"serving on http://127.0.0.1:{args.port}", flush=True)
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
