# 轉錄引擎

表單的 `engine` 四選一。速度與品質是相對描述，不是量測承諾。

| engine | 速度 | 品質 | 在哪裡跑 | 限制 | 狀態 |
| --- | --- | --- | --- | --- | --- |
| `qwen-0.6b` | 最快的本機選項 | 堪用 | 本機 | 需本機已快取 Qwen3-ASR-0.6B | 可用（預設） |
| `qwen-1.7b` | 約慢 2～3 倍 | 較準 | 本機 | 需本機已快取 Qwen3-ASR-1.7B | 可用 |
| `gemini-3.5-transcribe` | 最快 | 最準 | 上傳 Google，計費 | 含說話者與逐詞時間每段 30 分鐘，腳本自動切 25 分鐘段；最多 8 人 | 已實作，真實 API 呼叫未驗證 |
| `colab` | 視 Colab GPU | 同 Qwen（預設 1.7B） | Google Colab GPU | 要 Google 登入；分說話者要 Hugging Face token；整段一次分說話者 | ASR／對時本機 CPU 驗證；GPU、說話者與完整 Colab 未驗證 |

兩個 Qwen 選項共用同一條 worker 管線：ForcedAligner-0.6B 對時、Community-1 分說話者，`run.json` 的 `model` 記實際模型 ID 與 revision。

## Gemini

`scripts/gemini_transcribe.py`，只用標準庫與 ffmpeg，run 目錄規則與輸出和 worker 相同。

- 解碼成 canonical PCM 後切成 ≤25 分鐘的 WAV 段，經 Files API 上傳，再呼叫 Interactions API `POST /v1beta/interactions`，`transcription_config.mode = {"type": "verbatim", "diarization_mode": "speaker", "timestamp_granularities": ["word"]}`；狀態為 `in_progress`／`queued` 時輪詢。
- `word_info` 的 `start_offset`／`end_offset` 加上段落 offset。chunk 一段一個；`complete`／`truncated` 由互動狀態決定（`completed` 才算未截斷）。output_text 與逐詞不一致時保留 output_text、整份標為 partial 並在 state.json 警示。
- 說話者：單段為 S1、S2…（依首次發言）；多段為 `part-N-spk_M`，不跨段推定是同一人。
- 不送 custom vocabulary（官方確認不能與說話者或逐詞時間併用），參與者名單只當 `participant_candidates`。
- 轉完刪除 Google 端的上傳檔與互動紀錄（否則檔案留 48 小時、互動最多留 55 天）；刪不掉會寫進警示。
- 金鑰只讀環境變數 `GEMINI_API_KEY`，或 Wordprint 自建的 Keychain 項目（使用者自行執行 `security add-generic-password -s kerf-wordprint-gemini -a wordprint -w`）。不讀其他 Keychain 項目，金鑰不進指令列、檔案或 run 紀錄。
- `model` 記 `{"id": "gemini-3.5-transcribe", "size": null}`；state.json 記 `engine` 與 `network: "uploaded to Google Gemini API"`。

## Colab

`colab/wordprint.ipynb` 自含：上傳音檔 → ffmpeg 解碼 → `qwen_asr.Qwen3ASRModel` 加 ForcedAligner（qwen-asr 會自己把長音訊切成 ≤180 秒的段並換算成全段時間）→ 有 `HF_TOKEN` 時用 pyannote Community-1 分說話者 → 下載 `normalized-run-*.json`。生成長度碰到 `MAX_NEW_TOKENS` 的結果標 `truncated: true`。沒有 token 時照樣轉錄，`turns: []`、`diarization_complete: false`。

說話者是整段錄音一次分完，長的多人錄音從頭到尾是同一組 ID；Gemini 每 25 分鐘一段（`part-N-spk_M`）、本機 Qwen 每 20 分鐘一個視窗（`window-N-speaker-M`），各段各自編號。三者的速度與準確度都沒有實測比較。筆記本不回傳音訊；本機播放器由 agent 重新解碼原檔設定 `pcm`（見 SKILL.md）。
