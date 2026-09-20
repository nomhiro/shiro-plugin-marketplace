# shiro-plugin-marketplace

nomhiro の Claude Code プラグイン置き場。

## 追加

```
/plugin marketplace add nomhiro/shiro-plugin-marketplace
/plugin install udemy-exam-prep@shiro-plugin-marketplace
/plugin install udemy-video-course@shiro-plugin-marketplace
```

## プラグイン

| プラグイン | 説明 |
|---|---|
| [udemy-exam-prep](plugins/udemy-exam-prep/) | 認定資格の試験対策問題集（Udemy 演習テスト講座）を作成するハーネス。試験ブループリントの起草、公式ドキュメント調査、本番相当フル模試の生成・検証、Udemy へのアップロードまでを自動化する |
| [udemy-video-course](plugins/udemy-video-course/) | 動画講座のレクチャーを、スライドとナレーション台本からAI音声付きの動画にするハーネス。実践（ハンズオン）は Claude 自身が画面を操作して素材を撮る。品質ゲートと第三者レビューを工程に含む |

## 開発

```bash
python -m pytest
```

- 設計書: [docs/superpowers/specs/](docs/superpowers/specs/)
- 実装計画: [docs/superpowers/plans/](docs/superpowers/plans/)

## ライセンス

MIT
