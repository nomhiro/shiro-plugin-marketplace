# stop-ai-slop-jp

AIで書いた日本語から、AI臭さを取り除くスキル。

全角ダッシュや偏愛語のような表面の症状だけでなく、主体の不在（モノが人間の動詞をする）、命題型の見出し、
二項対比、3項目並列、リズムの均一さも直す。講義名、台本、説明文、記事など、日本語で書いたものを外に出す前に通す。

## 使い方

```
/plugin marketplace add nomhiro/shiro-plugin-marketplace
/plugin install stop-ai-slop-jp@shiro-plugin-marketplace
```

そのあと、`stop-ai-slop-jp` スキルを呼んで、直したい文章を渡す（例：「このレクチャー名を stop-ai-slop-jp で直して」）。

## 由来とライセンス

[iKora128/stop-ai-slop-jp](https://github.com/iKora128/stop-ai-slop-jp)（v0.1.1、コミット `e09d327`）を、**手を加えずに取り込んだ**もの。
原著者は Daichi Nagashima。MIT ライセンスで、`LICENSE` に原文の著作権表示を残している。

- 取り込んだもの：`skills/stop-ai-slop-jp/SKILL.md` と `references/`（`structures.md`・`phrases.md`・`examples.md`）
- 本家に更新があったら、その3種類を差し替えて版を上げる。ここで書き換えない（書き換えたい点は本家へ）
