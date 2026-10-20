# 轉錄引擎

表單的 `engine` 三選一。速度與品質是相對描述，不是量測承諾。

| engine | 速度 | 品質 | 上傳 | 限制 | 狀態 |
| --- | --- | --- | --- | --- | --- |
| `qwen-0.6b` | 最快的本機選項 | 堪用 | 不上傳 | 需本機已快取 Qwen3-ASR-0.6B | 可用（預設） |
| `qwen-1.7b` | 約慢 2～3 倍 | 較準 | 不上傳 | 需本機已快取 Qwen3-ASR-1.7B | 可用 |
| `gemini-3.5-transcribe` | 最快 | 最準 | 上傳 Google，計費 | 單段 30 分鐘 | 階段 B，尚未實作 |

兩個 Qwen 選項共用同一條 worker 管線：ForcedAligner-0.6B 對時、Community-1 分說話者，`run.json` 的 `model` 記實際模型 ID 與 revision。

## Gemini（階段 B 規格，尚未實作）

選到 Gemini 時，本階段告訴使用者「Gemini 尚未實作」，改跑 `qwen-0.6b`，並在回報與 run 紀錄寫明這次改跑。

階段 B 實作時依下列規格：

- 端點：Interactions API `POST /v1beta/interactions`。
- 設定：`generation_config.transcription_config.mode = {"type": "verbatim", "diarization_mode": "speaker", "timestamp_granularities": ["word"]}`。
- 回應：`steps[].content[].annotations[]` 的 `word_info` 含 `text`、`speaker`、`start_offset`、`end_offset`，轉成 [run-format.md](run-format.md) 的 chunks／words／turns。
- 單段上限 30 分鐘；更長的錄音要切段並記錄每段 offset。
- 金鑰只讀環境變數 `GEMINI_API_KEY` 或 Wordprint 自建的 Keychain 項目；不讀其他 app 的 Keychain 項目，不把金鑰寫進指令列、檔案或 run 紀錄。
- 上傳前向使用者揭露：檔案會傳到 Google、會計費；`run.json` 記錄引擎。
