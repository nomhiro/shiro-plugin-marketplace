# -*- coding: utf-8 -*-
"""アップロードする動画を、Udemy のページ内スクリプトから読めるように 127.0.0.1 だけで配る（読み取り専用）。

なぜ要るか: Claude in Chrome の `file_upload` は合計 10MB が上限で、講義の動画（20MB 前後）は通らない。
そこで、ページ内で `XMLHttpRequest(blob) → File → DataTransfer → input.files → change` を再現し、
Udemy 自身のアップローダを動かす。そのファイルの出どころがこのサーバー（手順は publish-video-course スキル）。

    python udemy_file_server.py <staging_dir> [--port 8765]

<staging_dir> の下に、セクションごとのフォルダ（00, 01, …）を置き、その中に講義の順に並ぶ名前で mp4 を置く
（例: `01/001_<講義名>.mp4`。名前の昇順が講義の順になる。ハードリンクで置けば容量を食わない）。
同じ章の2本目のレクチャーは `08b/` のように数字の後ろに英小文字を1つ付けてよい。

ページ側の注意（実際に起きた）:
- ページの `fetch` は計測スクリプトに包まれて、localhost で `Failed to fetch` になることがある → XMLHttpRequest で取る
- 取れた応答の status が 200 で、大きさが動画らしいか（1MB 以上）を必ず確かめる。404 の本文（335 バイト）を動画として渡し、空の動画が上がった

- `GET /list/<NN>`  → そのフォルダの動画の JSON `[{"i":1,"name":"...","size":123}, ...]`（昇順）
- `GET /f/<NN>/<i>` → i 番目（1 始まり）の動画そのもの
- CORS と Private Network Access のヘッダを付ける（https のページから 127.0.0.1 を読むため）

127.0.0.1 にしか bind しない。<staging_dir> の外は配らない。使い終わったら PID を指定して止める。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote


def files_of(root: Path, nn: str) -> list[Path]:
    d = root / nn
    return sorted(d.glob("*.mp4")) if d.is_dir() else []


def make_handler(root: Path):
    class H(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = unquote(self.path.split("?")[0])
            m = re.fullmatch(r"/list/(\d{2}[a-z]?)", path)   # 08b（同じ章の2本目）も受ける
            if m:
                body = json.dumps([{"i": i, "name": p.name, "size": p.stat().st_size}
                                   for i, p in enumerate(files_of(root, m.group(1)), 1)],
                                  ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            m = re.fullmatch(r"/f/(\d{2}[a-z]?)/(\d+)", path)
            if m:
                fs = files_of(root, m.group(1))
                i = int(m.group(2))
                if not 1 <= i <= len(fs):
                    self.send_error(404)
                    return
                p = fs[i - 1]
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(p.stat().st_size))
                self.end_headers()
                with p.open("rb") as f:
                    while chunk := f.read(1 << 20):
                        self.wfile.write(chunk)
                return
            self.send_error(404)

        def log_message(self, fmt: str, *args) -> None:  # 静かにする
            pass

    return H


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path, help="セクションごとのフォルダ（00, 01, …）を持つ置き場")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    root = a.root.resolve()
    if not root.is_dir():
        print(f"フォルダが無い: {root}", file=sys.stderr)
        return 2
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(root))
    print(f"serving {root} on http://127.0.0.1:{a.port}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
