# -*- coding: utf-8 -*-
"""段階的に積み上がる構成図を draw.io で作る（図解回のフレーム生成）。

設計・アーキテクチャの回は、完成図を1枚見せても頭に入らない。**同じレイアウトのまま
要素が1つずつ増える**図を段階ごとに書き出し、それをフレームとして並べると、
「いま何が足されたか」が分かる。

⚠️ **最大の落とし穴**：draw.io はコンテンツの外接矩形で crop する。素直に書き出すと
段ごとに画像サイズが変わり、動画にしたとき図が伸縮・移動して見える。
これを防ぐため、**全段に不可視の白い矩形（キャンバス全面）を入れて外接矩形を固定する**。

もう1つの頻出の崩れは**エッジラベルとボックスの重なり**。ラベルは短く保ち、
長い注記は独立したテキスト要素として、空いている場所に置く。

要素は `min_stage` を持ち、stage N では `min_stage <= N` のものだけ出力する（累積）。

使い方（Python から）:

    from stage_diagram import Diagram

    d = Diagram(1600, 816, title="シナリオA：社内QA エージェント")
    d.box("user", 1, 60, 352, 220, 116, "従業員", fill="#FFF2CC", stroke="#D6B656")
    d.box("agent", 1, 390, 342, 280, 136, "エージェント", fill="#DAE8FC", stroke="#6C8EBF")
    d.edge("e1", 1, "user", "agent", "質問")
    d.box("kb", 2, 880, 342, 300, 136, "knowledge base", fill="#D5E8D4", stroke="#82B366")
    d.edge("e2", 2, "agent", "kb", "検索")
    d.note("key", 3, 50, 648, 1500, 44, "決め手：…", size=19, color="#B85C00", bold=True)
    d.export(Path("./drawio"), Path("./images"), "scenarioA", stages=(1, 2, 3))
"""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

DEFAULT_DRAWIO = Path.home() / "AppData/Local/Programs/draw.io/draw.io.exe"
FONT = "BIZ UDPGothic"

_HEAD = ('<mxfile host="app.diagrams.net">\n'
         '  <diagram name="{n}" id="{n}">\n'
         '    <mxGraphModel dx="1000" dy="700" grid="0" gridSize="10" guides="1" '
         'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
         'pageWidth="{w}" pageHeight="{h}" math="0" shadow="0">\n'
         '      <root>\n        <mxCell id="0" />\n        <mxCell id="1" parent="0" />\n')
_TAIL = '      </root>\n    </mxGraphModel>\n  </diagram>\n</mxfile>\n'


class Diagram:
    def __init__(self, width: int = 1600, height: int = 816, title: str | None = None,
                 font: str = FONT):
        self.w, self.h, self.font = width, height, font
        self.items: list[tuple[int, str]] = []
        # 外接矩形を固定する不可視の白枠。これが無いと段ごとに画像サイズが変わる
        self._cell(1, "__frame", "",
                   f"rounded=0;html=1;fillColor=#FFFFFF;strokeColor=#FFFFFF;",
                   0, 0, width, height)
        if title:
            self.note("__title", 1, 50, 34, width - 100, 46, title,
                      size=27, color="#444444", bold=True)

    def _cell(self, stage, ident, value, style, x, y, w, h):
        self.items.append((stage,
                           f'<mxCell id="{ident}" value="{value}" style="{style}" '
                           f'vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" '
                           f'width="{w}" height="{h}" as="geometry"/></mxCell>'))

    def box(self, ident, stage, x, y, w, h, label, fill="#F5F5F5", stroke="#B3B3B3",
            size=17, bold=False, dashed=False):
        style = (f"rounded=1;whiteSpace=wrap;html=1;fontSize={size};verticalAlign=middle;"
                 f"align=center;fontFamily={self.font};fontColor=#1A1A1A;arcSize=8;"
                 f"fillColor={fill};strokeColor={stroke};"
                 + ("fontStyle=1;" if bold else "")
                 + ("dashed=1;dashPattern=8 6;" if dashed else ""))
        self._cell(stage, ident, label.replace("\n", "&#10;"), style, x, y, w, h)

    def note(self, ident, stage, x, y, w, h, label, size=16, color="#333333", bold=False):
        style = (f"text;html=1;strokeColor=none;fillColor=none;align=left;"
                 f"verticalAlign=top;whiteSpace=wrap;fontFamily={self.font};"
                 f"fontSize={size};fontColor={color};" + ("fontStyle=1;" if bold else ""))
        self._cell(stage, ident, label.replace("\n", "&#10;"), style, x, y, w, h)

    def edge(self, ident, stage, src, dst, label="", dashed=False, extra=""):
        style = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeWidth=2;"
                 f"strokeColor=#5A5A5A;fontSize=15;fontFamily={self.font};"
                 "fontColor=#333333;labelBackgroundColor=#FFFFFF;"
                 + ("dashed=1;" if dashed else "") + extra)
        self.items.append((stage,
                           f'<mxCell id="{ident}" value="{label}" style="{style}" '
                           f'edge="1" parent="1" source="{src}" target="{dst}">'
                           f'<mxGeometry relative="1" as="geometry"/></mxCell>'))

    def xml(self, name: str, stage: int) -> str:
        body = "".join(x + "\n" for s, x in self.items if s <= stage)
        return _HEAD.format(n=name, w=self.w, h=self.h) + body + _TAIL

    def export(self, src_dir: Path, png_dir: Path, name: str, stages=(1, 2, 3),
               scale: int = 2, drawio: Path | None = None) -> list[Path]:
        """.drawio を書き出し、draw.io CLI で PNG 化する。"""
        exe = Path(drawio) if drawio else DEFAULT_DRAWIO
        src_dir.mkdir(parents=True, exist_ok=True)
        png_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for stage in stages:
            p = src_dir / f"{name}-{stage}.drawio"
            io.open(p, "w", encoding="utf-8").write(self.xml(name, stage))
            png = png_dir / f"{name}-{stage}.png"
            r = subprocess.run([str(exe), "--export", "--format", "png",
                                "--scale", str(scale), "--border", "0",
                                "--output", str(png), str(p)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise SystemExit(f"draw.io の書き出しに失敗: {p.name}\n"
                                 f"{r.stdout[-300:]}{r.stderr[-300:]}")
            out.append(png)
            print(f"  ok {png.name}")
        return out


if __name__ == "__main__":
    print(__doc__)
