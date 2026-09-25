# -*- coding: utf-8 -*-
"""録画区間の正本（モードB）。ここだけを直せば、recipe.json・frames.json・台本がそろう。

R の1行 = 1区間 = (raw の画像名, ラベル, 強調の「意図の範囲」[x0,y0,x1,y1] か None, 塗り [[...]] か None, ナレーション)
- 強調は1区間に1つ。座標は「囲みたい範囲」をおおまかに書けばよい。box_fit.py が文字から 3px 以上離して置き直す。
- 塗り（黒ベタ）はサブスクリプション ID・アカウント名・メールなど。座標は原寸で拡大して確かめてから書く。
  表形式の出力は行ごとに右端が違うので、最も長い行に合わせる。
- ナレーションの規則（references/tts-readings.md も見る）:
  体言止めにしない／管理番号・フォルダー名の番号を読まない／az は「エーゼット」／区間は述語で言い切る／
  README の手順番号で語る（2桁は「十一番目の手順」）／モデル番号は読まない／数字は画面から拾う／
  ぶれうる結果は「今回は」／どの値を誰が出したかを言い分ける／条件の抜けた断定をしない／
  続きを予告して終わる文（「〜があります。」）や、英字・小数・パスの羅列を避ける（合成事故を誘う）。

実行: python make_recipe.py   → recipe.json
"""
import json
from pathlib import Path

W = Path(__file__).resolve().parent

# 例：塗りの座標を定数にしておくと、同じ画面の複数区間で使い回せる
# SUB = [[456, 654, 736, 699]]

R = [
    ("v00a.jpg", "レッスンのフォルダー", [262, 480, 925, 523], None,
     "ここから手を動かします。このレッスンのフォルダーには、main.py と README.md が入っています。"
     "実行するコマンドは README.md に手順としてまとめてあるので、プレビューで開きます。"),
    ("v01a.jpg", "手順1 変数（入力）", [262, 480, 1260, 625], None,
     "手順1で、リソースグループやプロジェクトの名前を変数に決めます。"),
    ("v01b.jpg", "手順1 結果", [262, 528, 900, 597], None,
     "値が入りました。"),
    ("c01.jpg", "コード：クライアントの作成", [300, 200, 1200, 420], None,
     "ここでクライアントを作ります。役割は…。こう書くのは…だからです。試験では…が問われます。"),
]

if __name__ == "__main__":
    out = []
    for i, (src, label, hl, bo, _text) in enumerate(R, 1):
        e = {"src": src, "out": f"r{i:02d}.jpg", "label": f"r{i:02d} {label}", "highlight": hl}
        if bo:
            e["blackout"] = bo
        out.append(e)
    (W / "recipe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(out), "entries")
