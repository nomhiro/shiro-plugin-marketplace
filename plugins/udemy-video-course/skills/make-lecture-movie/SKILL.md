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

## 🔴 必ず回す検査

1本を「完成」と書く前に、次をすべて通す。表の正本（失敗 → 検出器 → 関門 → 書き戻し先）は
`../../references/self-improvement.md`。スライドと台本の基準は `../../references/quality-standards.md`。

**どの講座でも（pptx 経路を含む）**

| いつ | 検査 | 合格 |
|---|---|---|
| 音声を作る前 | 初学者役のレビュー（用語の説明・話と絵のずれ・見た目だけの図・固有名の言い換え）と、台本の `受講者\|受講生\|講師` の grep | 指摘を直した。grep 0 件 |
| 起動時（自動） | `deps.py`（工程に要る依存と、どの Python で動いているか） | 足りなければ終了コード 2 で止まる |
| 音声の前（自動） | manifest（本文・モデル・声） | 本文が変わった区間だけ作り直す。モデル・声が既存と違えば何も作らずに止まる |
| 音声の後 | `lecture_movie.py` の終了コード | 0（TTS の失敗があれば 1。動画は組まれない） |
| 音声の後 | `verify_tts.py <台本> --endpoint <Speech>` を全区間 | NG 0。終了コード 3 は照合先の故障（音声を作り直さない） |
| 動画の前（自動） | 音声が無い・古い・モデルが混在する区間 | 0（あれば終了コード 1 で止まる） |
| 完成後 | スライドの PNG・完成動画のシートを全数目視 | 抜き取りで見ない |
| 完成後 | `empty_frames.py <mp4>` | 見出しだけの区間 0 |
| 完成後（報告） | `still_report.py <mp4>` | 20 秒を超えて止まるスライドを把握し、きっかけの無い要素があれば足す |
| 公開前に全本 | `final_sweep.py "<lectures>/*/*.mp4"` | 異常 0（仕様・尺・音量・黒・cue の補間） |

**cue（台本の一節を音声と照合して強調を出す同期）を使う講座**では、加えて：

| いつ | 検査 | 合格 |
|---|---|---|
| レンダの後に全本まとめて | `cue_report.py "<lectures>/*/*_audio/_timing.json"` | 補間 0（1本ずつの警告ではなく、分母つきで数える） |
| レンダの後 | `cue_drift.py "<lectures>/*/*_audio/_timing.json"` | 別の文への誤一致 0（書き起こしの崩れは目で除く） |

検出器を新しく作ったら、**承認済みの全本にさかのぼって回す**（空白の検出器で、承認済みの3本に空白が見つかった）。

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
| `--model <名>` | 環境変数 `VIDEO_COURSE_TTS_MODEL`、無ければ `gemini-3.1-flash-tts-preview` | TTSモデル。**既存の音声と違うモデルなら止まる**（1本の中で混ぜない） |
| `--voice <名>` | 指示ファイルの Voice（`Callirrhoe`） | 読み上げ音声 |
| `--max-chunk-chars <n>` | `250` | TTS分割の文字数上限（2分バグ回避） |
| `--chunk-gap-seconds <s>` | `0.5` | スライド内：分割TTSチャンク間の無音 |
| `--slide-lead-seconds <s>` | `1.0` | スライド表示→ナレーション開始の無音 |
| `--slide-tail-seconds <s>` | `2.0` | ナレーション終了→次スライドの無音 |
| `--default-still-seconds <s>` | `4` | 台本が無いスライドの表示秒数 |
| `--png-scale <n>` | `2` | pptx→PNG 倍率（16:9デックで 1920×1080 相当） |
| `--force` | off | 既存の wav/mp4 も再生成（既定は本文・モデル・声が同じ wav をスキップ） |
| `--allow-tts-failure` | off | TTS の失敗・音声の欠けがあっても無音の静止画で組み、終了コード 0 を返す（従来の動き） |
| `--adopt-existing` | off | manifest に記録の無い既存 wav を、今回のモデル・声・台本で作ったものとして記録する（合成はしない）。**音声を作ってから台本を直していない**と確かなときだけ |
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
    .manifest.json                 # どの wav を、どの本文・モデル・声で作ったか
```

`speech_NN.wav` は台本のあるページに `01` から採番（ページ番号ではなく台本のある順）。
途中にスライドを足すと以降の番号が繰り下がるが、manifest が本文の違いとして作り直す（古い番号の wav を流用しない）。

### 終了コード

| コード | 意味 |
|---|---|
| 0 | すべて成功 |
| 1 | TTS に失敗した区間がある／音声が無い・古い区間がある／既存の音声とモデル・声が違う。**動画は組まれない** |
| 2 | 依存が足りない（起動時に止まる。表示された Python に `pip install -r scripts/requirements.txt`） |

以前は TTS の失敗を無音の静止画として組み込み、終了コード 0 で終わっていた。外側のスクリプトがログを grep して
失敗を拾う運用になっていたので、本体で止めるようにした。

## 声・スタイル

`<repo>/vertexai-tts-instruction.md` で制御する。`Voice：<名>`（既定 `Callirrhoe`）の行と、それ以降の `DIRECTOR'S NOTES`（スタイル指示プロンプト）を読み込む。声やトーンを変えたいときはこのファイルを編集する。

## よくある落とし穴

- **英字の略語・記号の誤読**：`az` を「アズ」と読むなど、TTS は台本の表記どおりには読まないことがある。台本を書く前に **`../../references/tts-readings.md`（読み上げ表記一覧）** を見て、載っている表記は台本での書き方に直す（例：`az login` → 「エーゼットログイン」）。直したら `--audio-only`（本文が変わった区間だけ作り直される）→ `--video-only --force`（手順は一覧の D）。
- **flash-tts の2分バグ**：flash系モデルは約2分以上を一度に生成すると読み上げが速くなる。本スキルは `--max-chunk-chars`（文単位）で細分割して結合し回避済み。長い台本でも速度が一定か確認する。
- **認証・権限エラー**：`PERMISSION_DENIED: Agent Platform API has not been used...` は `aiplatform.googleapis.com` の未有効化が原因（Gemini-TTSはVertex AI経由）。ADCログインと上記2APIの有効化を確認。API有効化直後は反映に数分かかる場合がある。
- **soffice が PDF を生成しない**：別の soffice 常駐インスタンスが横取りしている／対象 pptx を PowerPoint で開いている → スクリプトは soffice を全終了して一度だけ再試行する。`lectures/.../~$*.pptx` ロックがあれば PowerPoint を閉じる。
- **soffice は `soffice.com`**（同期実行）を使う。`soffice.exe` は即 detach し変換完了前に戻る（スクリプトは .com を優先）。
- **日本語パス**：pptx は ASCII の作業コピーへ複製してから変換する（スクリプトが処理）。
- **Windows の cp932 エンコードエラー**：スクリプトは起動時に stdout/stderr を UTF-8 へ再設定して `▶ ✓` 等の `UnicodeEncodeError` を回避済み（追加の環境変数設定は不要）。
- **既存データの上書き**：既定では本文・モデル・声が同じ wav と既存の mp4 をスキップ。全部作り直す場合のみ `--force`。
- **モデルを変える**：1本の中で混ぜない。音声フォルダを `<basename>_audio.bak_<日付>` へ退避（移動）してから全区間を作る。
  変えた最初の数本は `verify_tts.py` で全区間を照合する（事故の出方がモデルで変わる。`tts-readings.md` の C3〜C5）。
- **TTS の事故の形**：台本に無い文を足す・全文を2回読む・スタイル指示を読み上げる・冒頭や末尾が抜ける。
  NG の区間は wav だけを退避して `--audio-only`（無い wav だけ作られる）→ その区間を再照合。
- **合成の内容事故は長さでは分からない**：上の 🔴 のとおり、全区間を STT で照合する。
  事故を誘いやすい文型（続きを予告して終わる文、英字ラベルや小数の羅列、2桁の手順番号）は
  `../../references/tts-readings.md` を参照して、台本の段階で避ける。
- **並列で回すとき**：STT はレート制限があり、一時ファイル名が衝突しないこと（verify_tts は一意名で対応済み）。
  固まったプロセスは **PID を指定して**止める（`taskkill /IM python.exe` は他の処理まで止める）。
- **照合が全区間「認識結果が空」**：音声ではなく照合先（エンドポイントの DNS・認証・ロール）を疑う。照合先は
  講座のハンズオン用のリソースから切り離し、複数講座で共用するものにする（ハンズオンの後片付けで消える）。
- **コスト**：TTS は文字数課金。`--audio-only` で先に音声を確認し、動画は `--video-only` で繰り返すと TTS を再課金せずに済む。

## 関連スキル

- 上流：[[make-lecture-slides]]（pptx と `_transcript.md` を作る）／[[write-lecture-doc]]（詳細原本）
- 規約：講座リポジトリの用語規約・テンプレート／設計：カリキュラム設計書
- 姉妹：[[make-practice-movie]]（実践レクチャーの動画化）
