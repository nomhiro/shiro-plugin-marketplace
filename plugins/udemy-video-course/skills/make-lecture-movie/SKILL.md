---
name: make-lecture-movie
description: 動画講座のナレーション台本（*_transcript.md）と PowerPoint スライド（*.pptx）から、AI音声付きの講座動画（MP4）を生成する下流スキル。Google Gemini-TTS で日本語ナレーション音声（speech_NN.wav）を合成し、LibreOffice で pptx をPNG化、ffmpeg でスライドと音声をレクチャー単位の動画に合成する。「L1-1-2 の動画作って」「このレクチャーを動画化」「ナレーション音声を生成」「スライドに音声を付けて動画に」やスラッシュコマンド /make-lecture-movie で起動。動画講座レクチャーの音声合成・動画(MP4)生成では必ずこのスキルを使う。
allowed-tools: Read, Write, Glob, Bash
---

# make-lecture-movie

台本（`lectures/<NN_section>/<basename>_transcript.md`）と PowerPoint スライド（`<basename>.pptx`）から、AI音声付きの講座動画 `<basename>.mp4` を生成するスキル。

> **位置づけ**：[[make-lecture-slides]] の**下流**。`make-lecture-slides` が作る `.pptx` と `_transcript.md` を入力に、ナレーションを合成して動画化する。1レクチャー＝1デック＝1台本（basename 共通）。
>
> **由来**：Marp ベースの先行実装を土台に、入力スライドを **Marp md → PowerPoint(.pptx)** に、レクチャー単位を **ページ分割 → basename ペア解決**に移植したもの。TTS・「間」・ffmpeg 合成のコアは流用。

## パイプライン

台本 → AI音声（`speech_NN.wav`）→ pptxをPNG化 → 動画（`<basename>.mp4`）。

1. レクチャーID/グロブ/パスから `(pptx, transcript)` ペアを **basename** で解決。
2. 台本を `## スライドN:` 単位にパース（ページNと1:1対応）。
3. Google Cloud Text-to-Speech（Gemini-TTS）で各スライドのナレーションを合成（声・スタイルは `<repo>/vertexai-tts-instruction.md`）。
4. **LibreOffice(soffice)** で pptx → PDF → PNG（PyMuPDF）にレンダリング。
5. ffmpeg で「スライド画像＋音声」をレクチャー単位の MP4 に合成。

> 🔴 **音声を作ったら、動画を組む前に `scripts/verify_tts.py <…_transcript.md> --endpoint <Speech>` で照合する。**
> Gemini-TTS は、台本と無関係な文・**スタイル指示の読み上げ**・冒頭や末尾の脱落を起こす。
> 実測（座学76本）：**23本・33区間**で発生し、公開済みの動画に埋もれていた。
> 最多はスタイル指示の読み上げ（17区間）で、チャンクの切れ目に出やすい。再合成しても繰り返す区間は、
> スタイル指示なしで合成する（声は同じで、トーンだけ標準になる）。

## いつ使うか

- **座学レクチャー**のスライドを、ナレーション付きの動画にしたいとき。
- 台本だけ先に音声化したい（`--audio-only`）／既存音声から動画だけ作りたい（`--video-only`）とき。

> **実践（ハンズオン）は既定でスキップ**：実践レクチャーの命名規則（既定は basename に `_実践_` を含むもの）に一致するレクチャーは、このスキルでは生成しない。実践は [[make-practice-movie]] が担当する。まとめて指定しても実践は自動で除外され、スキップした旨を表示する。どうしてもここで生成したいときだけ `--include-practice` を付ける。

## 前提条件（初回のみ確認）

1. **Python依存**：`pip install -r scripts/requirements.txt`（`google-cloud-texttospeech` / `PyMuPDF` / `python-pptx`）
2. **gcloud 認証（ADC）**：`gcloud auth application-default login`
   - 対象GCPプロジェクトで課金を有効化し、次の **2つのAPIを有効化**：
     ```bash
     gcloud services enable texttospeech.googleapis.com aiplatform.googleapis.com
     ```
     ※ Gemini-TTS モデル（`gemini-*-tts`）は Vertex AI 経由のため `aiplatform.googleapis.com` も必須。無いと `PERMISSION_DENIED: Agent Platform API has not been used...` で失敗する。
   - 実行アカウントに `roles/aiplatform.user` を付与（必要なら `GOOGLE_CLOUD_PROJECT` を設定）
3. **ffmpeg / ffprobe** が PATH にあること
4. **LibreOffice（soffice）** が PATH もしくは既定インストール先（`C:/Program Files/LibreOffice/program/soffice.com`）にあること
   - ※ `slide-movie` と違い **Node/Marp は不要**（Marp ではなく pptx を使うため）

## 使い方

```bash
# レクチャー単位（音声＋動画）。ID は前方一致
python scripts/lecture_movie.py L1-1-2

# L1-1 配下すべて（L1-1-x → L1-1-* に展開）
python scripts/lecture_movie.py L1-1-x

# 音声のみ / 動画のみ
... L1-1-2 --audio-only
... L1-1-2 --video-only

# パス直接指定（.pptx か *_transcript.md）も可
... "lectures/01_plan_manage/L1-1-2_座学_model-selection_transcript.md"
```

> 実行は **リポジトリ直下**から（既定の検索ルートが `lectures/`）。別の場所からは `--lectures-dir <path>` を指定。

### 主なオプション

| オプション | 既定 | 説明 |
|---|---|---|
| `targets`（必須・複数可） | — | レクチャーID（`L1-1-2`）/グロブ（`L1-1-x`）/ `.pptx`・`*_transcript.md` のパス |
| `--lectures-dir <path>` | `lectures` | 検索ルート |
| `--include-practice` | off | 実践（ハンズオン）も生成する（既定は実践をスキップ＝自分の声で収録するため） |
| `--audio-only` / `--video-only` | 両方 | フェーズを限定 |
| `--model <名>` | `gemini-3.1-flash-tts-preview` | TTSモデル（最新flash。高音質安定版は `gemini-2.5-pro-tts`） |
| `--voice <名>` | 指示ファイルの Voice（`Callirrhoe`） | 読み上げ音声 |
| `--max-chunk-chars <n>` | `250` | TTS分割の文字数上限（2分バグ回避） |
| `--chunk-gap-seconds <s>` | `0.5` | スライド内：分割TTSチャンク間の無音 |
| `--slide-lead-seconds <s>` | `1.0` | スライド表示→ナレーション開始の無音 |
| `--slide-tail-seconds <s>` | `2.0` | ナレーション終了→次スライドの無音 |
| `--default-still-seconds <s>` | `4` | 台本が無いスライドの表示秒数 |
| `--png-scale <n>` | `2` | pptx→PNG 倍率（16:9デックで 1920×1080 相当） |
| `--force` | off | 既存の wav/mp4 も再生成（既定はスキップ） |
| `--dry-run` | off | TTS/soffice/ffmpeg を実行せず分割計画のみ表示 |

### 「間（ポーズ）」の設計

| 場面 | 制御 | 既定 |
|---|---|---|
| 文グループ間（長い台本の分割箇所） | `--chunk-gap-seconds` | 0.5秒 |
| スライド表示直後（語り出しまで） | `--slide-lead-seconds` | 1.0秒 |
| 語り終わり〜次スライドまで | `--slide-tail-seconds` | 2.0秒 |

スライド切替時の実質的な「間」＝ 前スライドの tail（2.0秒）＋ 次スライドの lead（1.0秒）で **約3秒**。台本の無いスライドは `--default-still-seconds`（4秒）静止。

## 出力レイアウト

```
lectures/<NN_section>/
  <basename>.pptx                  # 入力（make-lecture-slides 生成）
  <basename>_transcript.md         # 入力（make-lecture-slides 生成）
  <basename>.mp4                   # 出力：動画（1920×1080 / 30fps）
  <basename>_audio/                # 出力：音声
    speech_01.wav, speech_02.wav, ...
```

`speech_NN.wav` は台本のあるページに `01` から採番（ページ番号ではなく台本のある順）。

## 声・スタイル

`<repo>/vertexai-tts-instruction.md` で制御する。`Voice：<名>`（既定 `Callirrhoe`）の行と、それ以降の `DIRECTOR'S NOTES`（スタイル指示プロンプト）を読み込む。声やトーンを変えたいときはこのファイルを編集する。

## よくある落とし穴

- **英字の略語・記号の誤読**：`az` を「アズ」と読むなど、TTS は台本の表記どおりには読まないことがある。台本を書く前に **`../../references/tts-readings.md`（読み上げ表記一覧）** を見て、載っている表記は台本での書き方に直す（例：`az login` → 「エーゼットログイン」）。直したら該当区間の `speech_NN.wav` を削除して `--audio-only` → `--video-only --force`（手順は一覧の D）。
- **flash-tts の2分バグ**：flash系モデルは約2分以上を一度に生成すると読み上げが速くなる。本スキルは `--max-chunk-chars`（文単位）で細分割して結合し回避済み。長い台本でも速度が一定か確認する。
- **認証・権限エラー**：`PERMISSION_DENIED: Agent Platform API has not been used...` は `aiplatform.googleapis.com` の未有効化が原因（Gemini-TTSはVertex AI経由）。ADCログインと上記2APIの有効化を確認。API有効化直後は反映に数分かかる場合がある。
- **soffice が PDF を生成しない**：別の soffice 常駐インスタンスが横取りしている／対象 pptx を PowerPoint で開いている → スクリプトは soffice を全終了して一度だけ再試行する。`lectures/.../~$*.pptx` ロックがあれば PowerPoint を閉じる。
- **soffice は `soffice.com`**（同期実行）を使う。`soffice.exe` は即 detach し変換完了前に戻る（スクリプトは .com を優先）。
- **日本語パス**：pptx は ASCII の作業コピーへ複製してから変換する（スクリプトが処理）。
- **Windows の cp932 エンコードエラー**：スクリプトは起動時に stdout/stderr を UTF-8 へ再設定して `▶ ✓` 等の `UnicodeEncodeError` を回避済み（追加の環境変数設定は不要）。
- **既存データの上書き**：既定では既存の wav/mp4 をスキップ。作り直す場合のみ `--force`。
- **合成の内容事故は長さでは分からない**：上の 🔴 のとおり、全区間を STT で照合する。
  事故を誘いやすい文型（続きを予告して終わる文、英字ラベルや小数の羅列、2桁の手順番号）は
  `../../references/tts-readings.md` を参照して、台本の段階で避ける。
- **並列で回すとき**：STT はレート制限があり、一時ファイル名が衝突しないこと（verify_tts は一意名で対応済み）。
  固まったプロセスは **PID を指定して**止める（`taskkill /IM python.exe` は他の処理まで止める）。
- **コスト**：TTS は文字数課金。`--audio-only` で先に音声を確認し、動画は `--video-only` で繰り返すと TTS を再課金せずに済む。

## 関連スキル

- 上流：[[make-lecture-slides]]（pptx と `_transcript.md` を作る）／[[write-lecture-doc]]（詳細原本）
- 規約：講座リポジトリの用語規約・テンプレート／設計：カリキュラム設計書
- 姉妹：[[make-practice-movie]]（実践レクチャーの動画化）
