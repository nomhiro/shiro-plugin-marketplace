---
name: make-slide-lecture
description: Hyperframes のスライド型（白い地・大きな文字・フェードと矢印だけ）で、Udemy の講義動画を作る。座学のユニットと、ハンズオンの本体（record-practice-screen で撮った静止画を並べる）の両方。台本 → 初学者役・事実・日本語のレビュー → 音声と退避 → 読みの検証 → 語末の実測 → slides.py → 検査 → slide-reviewer → レンダリング → 冒頭・本体・末尾を1本に連結、までを回す。講座の値は course.yaml に置く。
---

# make-slide-lecture

1ユニット＝1本の動画（尺の目安は `references/slide-format.md` §2d）を `videos/<unit>/` に作り、冒頭（`lecture-<章>-<レク>-open`）・本体のユニット・末尾（`-close`）を
連結して、Udemy の講義1本（`<lectures_out_dir>/<lecture-id>/lecture.mp4`）にする。

- 型の規則は `references/slide-format.md`、1ユニットの細かい手順は `references/unit-playbook.md`、関門の一覧は `references/production-checklist.md`
- 台本と画面の質の基準は `references/quality-standards.md`、読みは `references/tts-readings.md`、日本語は `references/japanese-check.md`、
  小テストは `references/quiz-authoring.md`、Windows と長い処理は `references/windows-and-ops.md`
- 上がった動画を Udemy に入れるのは [[publish-video-course]]。ハンズオンの画面を撮るのは [[record-practice-screen]]
- 旧型（pptx の座学 [[make-lecture-movie]]、録画 `_rec.mp4` の実践 [[make-practice-movie]]）は、既にその型で作った講座の手直し用に残す

以下の `$S` はこのプラグインの `scripts/`（このファイルから見て `../../scripts`）。講座の直下で実行する。

## 0. 前提（最初に1回だけ確かめる）

| もの | 確かめ方 |
|---|---|
| faceless-explainer のスキル（`assemble-index.mjs`・`transitions.mjs`・`audio.mjs`） | `course.yaml` の faceless_scripts（既定 `~/.claude/skills/faceless-explainer/scripts`）にあるか |
| Hyperframes | `npx --yes hyperframes@<版> --version`。**版は講座の途中で変えない**（描画が変わり、撮り直しになる） |
| node・ffmpeg・ffprobe | PATH にあるか |
| Python の依存・実行ファイル | `python $S/deps.py slide tts stt-google hira`（足りないものを並べる。入れるのは `pip install -r $S/requirements.txt`） |
| Google Cloud の認証 | 制作者が `gcloud auth application-default login` を済ませているか（TTS・STT・Vertex AI）。プロジェクト名は環境変数 GOOGLE_CLOUD_PROJECT（リポジトリに書かない） |

**スクリプトに `--help` を渡さない。** 本処理が走るものがある（`audio.mjs --help` が原音声を上書きした）。使い方はソースの先頭を読む。

## 1. 講座の準備（講座ごとに1回）

1. `templates/course.example.yaml` を講座の直下に `course.yaml` として写し、受講者像・章フォルダ・Hyperframes の版・話者を埋める。
   `python $S/course_config.py` で読めたかを確かめる
2. 雛形 `videos/_template/`（course.yaml の template_dir）に `templates/slide-unit/` の中身を写す。色を変えるときは `frame.md` の colors: の値だけを変える
3. 書体を `videos/_template/assets/fonts/` に置く: `biz-udpgothic-japanese-400-normal.woff2`・`-700-normal.woff2`（npm の `@fontsource/biz-udpgothic`。SIL OFL）。
   slide_kit.py がこの2つで字幅を実測して、はみ出しを生成の時点で止める
4. 講座の部品 `videos/_shared/<講座>_parts.py`（course.yaml の parts_dir）を `templates/slide_parts.example.py` から作り、CHAPTERS を講座の並びで埋める
5. 話者の指示書 `tts-instruction.md`（1行目 `Voice：<名前>`）と読みの辞書 `tts-readings.tsv`（空でよい）を置く
6. `.gitignore` に `videos/_audio-backup/`・`videos/*/renders/`・`videos/*/snapshots/`・`videos/_lectures/` を足す
7. 講座の教訓ファイル（`templates/course-lessons.md` から）と、slide-reviewer の講座の追加観点（`templates/slide-reviewer-extra.md` → `.claude/slide-reviewer-extra.md`）を置く

## 2. 1ユニットの流れ

```bash
export PYTHONIOENCODING=utf-8
python $S/make_unit.py <unit> "<タイトル>" <doc-id>       # 入れ物（既にあるファイルは上書きしない）
```

1. **台本** `videos/<unit>/SCRIPT.md` を書く（字下げ4つの行だけが音声になる。`## Line N — 名前 (Frame N)`）。
   ハンズオンの本体は、撮った結果から書く（生成 AI の返答は毎回変わるので、先に書くと画面と合わない）
2. **音声の前のレビュー**（音声のあとに直すと語末が全部ずれる）。並べて回し、高・中を 0 にしてから次へ
   - 初学者役: `templates/script-review_prompt.md`
   - 事実の照合: `templates/fact-check_prompt.md`（台本と小テストの事実の文ごとに根拠の原文と突き合わせる）
   - 日本語: `references/japanese-check.md`（講座が決めたチェックの道具を通す）
3. **音声**
   ```bash
   python $S/tts.py <unit>                  # 作った直後に <audio_backup_dir>/<日付>/<unit>/after-tts/ へ自動で退避
   python $S/check_reading.py videos/<unit> # STT で台本と突き合わせる（漢字・かなだけ）
   python $S/hira_check.py videos/<unit>/assets/voice/05.wav   # 英字を含む行は音をひらがなで確かめる
   python $S/hira_narrow.py videos/<unit>/assets/voice/05.wav <正しい読み> <疑う読み>   # 割れたら狭い窓で数える
   python $S/pad_audio.py videos/<unit>     # 行頭 0.6 秒・行末 1.2 秒（pad-before/ に自分で退避する）
   python $S/check_clicks.py videos/<unit> --wav-only
   python $S/make_beats.py videos/<unit>    # 語末の実測表 _beats.md
   (cd videos/<unit> && node <faceless_scripts>/audio.mjs sync-durations --audio-meta ./audio_meta.json --storyboard ./STORYBOARD.md)
   python $S/dump_beats.py <unit>
   ```
   - 録り直すのは**明らかな誤読（疑う読みが過半数）と文の脱落だけ**。STT の揺れで録り直さない（`references/tts-readings.md`「読みの確認を過剰にしない」）
   - 誤読した語は `tts-readings.tsv` に足して `--only <frame>` で作り直す。読めた時点で止める（`redo_until.py`）
4. **画面** `slides.py` を書く（`render_pages`・`E(frame, "語")`・`s.reveal`）。`new_storyboard.py` で器を作ったら sync-durations をもう一度回す
5. **組んで検査する**
   ```bash
   python $S/unit_build.py <unit>          # slides.py → assemble-index → transitions → lint・check → check_crossfade → snapshot
   python $S/check_coverage.py videos/<unit>
   python $S/check_idle.py videos/<unit>
   python $S/check_late_reveals.py videos/<unit>
   python $S/check_nth.py videos/<unit>
   python $S/check_spacing.py videos/<unit>
   python $S/sheet.py <unit> 1 4 7 ...    # 着地の画像を並べて Read で見る
   python $S/slide_table.py videos/<unit> --write <ユニット doc>
   ```
6. **slide-reviewer**（エージェント）に渡す。ハンズオンの本体は **transcript-reviewer** にも渡す（映っている画面と台本の主張）。高・中を 0 にする。
   直したら同じレビュー担当に確認を1回だけ回す
7. **レンダリング**は、レビューが通ったユニットをまとめて1本ずつ順に回す（メモリ。ほかの重い処理と重ねない）
   ```bash
   python $S/render_units.py <unit> [<unit> ...]   # バックグラウンドで。終わりの通知を受けたらすぐ次へ
   python $S/render_status.py <lecture-id> <unit> ...   # 報告の前に必ず数える
   ```

## 3. ハンズオンの本体

- 画面は [[record-practice-screen]] で1状態ずつ撮り、塗り（`ocr_mask.py`）と塗り残しの点検（`leak_check_ocr.py`）を済ませた `masked/` の静止画を使う
- 本体のユニット名は course.yaml の handson_suffix（既定 `-handson`）で終える。make_unit.py が Line 1 の型を置く
- タイトルは細い帯、画面はほぼ全面: `render_pages(..., compact=True)`、置き場所 `X, Y, W, MAXH = 40, 70, 1840, 1002`
- エディターは窓全体を映す。字は撮るときに大きくする（切り出して拡大しない）
- 強調（押す場所・打つ欄・見る場所）は全区間に入れ、コンタクトシートで全数見る

## 4. 1本の講義にする

```bash
python $S/make_lecture.py <lecture-id> lecture-<章>-<レク>-open <unit> ... lecture-<章>-<レク>-close
```

- 各ユニットの `renders/video.mp4` を再エンコードなしでつなぐ（設定が食い違えば止まる）。つなぎ目に間を足さない
- 区切りの札が要るときは `make_bridge.py`（ユニットとユニットの間に「ここまでが〇〇でした。次は△△です。」の1枚）
- 30 分を超えたら講義を分ける
- 台本の通し読み用の写しは `lecture_script_view.py`、小テストは `references/quiz-authoring.md` と `templates/quiz-review_prompt.md`
- Udemy に入れるのは [[publish-video-course]]

## 必ず回す検査

| 時点 | 検査 |
|---|---|
| 音声の前 | 初学者役・事実の照合・日本語のチェック（高・中 0） |
| 音声の直後 | 退避（tts.py が自動）・check_reading・英字の行は hira_check・check_clicks |
| 組んだあと | unit_build（lint・check・check_crossfade）・check_coverage・check_idle・check_late_reveals・check_nth・check_spacing・コンタクトシートの目視 |
| 見せる前 | slide-reviewer（ハンズオンは transcript-reviewer も）。高・中 0 |
| レンダリングのあと | render_status・check_clicks（動画）・make_lecture の尺の差 |

## 区切りでやること

- 失敗と手間は講座の教訓ファイルに1行ずつ足す。制作者から新しい指摘を受けたら、その場でレビュー担当の観点に1項目足す（`references/self-improvement.md`）
- 道具や型を直したくなったら、講座に写して直さず、このプラグインを直す（直しが片方の講座にしか入らなくなる）
