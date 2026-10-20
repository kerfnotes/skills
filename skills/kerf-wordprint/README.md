# Wordprint

Wordprint 在你自己的電腦上把錄音轉成逐字稿，附時間戳與說話者標記。開始時會開一頁表單，一次選好錄音（語音備忘錄或本機檔案）、引擎、參與者、摘要種類與要不要開 Mail 草稿；之後轉錄、分說話者、產出可點選跳播的閱讀頁，需要時再做摘要報告與 Mail 草稿。也可以合併多段錄音、替既有逐字稿補上說話者，或在確認姓名後改標。

預設全部在本機處理。只有你在表單明確選 Gemini 才會上傳，上傳前會先告訴你，`run.json` 也會記錄用了哪個引擎。Gemini 目前還在規劃中，選了會先改用本機 Qwen 0.6B 並告訴你。

## 它做什麼

- 用 Qwen3-ASR 轉錄，預設小模型 0.6B；在表單選或說「用大模型」就改用 1.7B。
- 用 Qwen ForcedAligner 對時間，用 Community-1 分出說話者。
- 原始辨識文字另存一份，繁體閱讀版由 OpenCC 轉換；改姓名不必重新轉錄。
- 說話者一律先以「說話者 1、2」標示。提供線索時最多標成「可能是某某」，你確認後才算定案。
- 閱讀頁 `transcript.html` 是單檔文字頁，可一鍵複製 Markdown 或開寄信。要回聽，閱讀頁得和同資料夾的 `playback.wav` 放在一起，點任一段就跳到該處播放；沒有音訊的那份不顯示播放器。時間完整時另附 `transcript.srt` 字幕。
- 選了摘要，會依會議／訪談／演講模板寫 `notes.md`；有裝 [Clayprint](../kerf-clayprint/) 就再排成 `notes.html`（和 PDF）。決議只收明確同意的事，負責人與期限沒說就寫「待確認」。
- Mail 草稿只會打開讓你檢查，不會自動寄出；只附 `transcript.html`、`notes.html`、`notes.pdf`，不附音檔，所以收件人的閱讀頁只能讀、不能回聽。

## 交給 agent 安裝

把這段交給 Codex 或 Claude Code：

```text
請把 https://github.com/kerfnotes/skills 裡的 Wordprint（skills/kerf-wordprint）安裝到目前專案。
先讀 skills/kerf-wordprint/docs/install.md，依目前使用的 agent 選擇安裝路徑，
自行完成環境檢查、模型準備與短音檔驗證，回報安裝路徑、版本及驗證結果。
```

Codex 的專案路徑是 `.agents/skills/kerf-wordprint/`；Claude Code 是 `.claude/skills/kerf-wordprint/`。安裝 skill 不會下載模型；[agent 安裝指引](docs/install.md)說明怎麼準備本機工具、模型與驗證。安裝完成後可直接說「把這個音檔轉成逐字稿」；Codex 也可用 `$kerf-wordprint`，Claude Code 可用 `/kerf-wordprint`。

## 已知限制

- 表單、語音備忘錄讀取與轉錄流程只在 Apple Silicon Mac 驗證過；Windows 的安裝路線有寫，但尚未實測。
- Mail 草稿目前只驗證過 dry-run（印出 AppleScript）；真實草稿要等你授權 macOS 自動化權限後再驗收。
- 讀語音備忘錄需要給終端機「完整磁碟取用權」；不想給，就把備忘錄拖到資料夾再選路徑。
- 第一次開 Mail 草稿時，macOS 會問是否允許控制 Mail，要你本人按允許。
- Windows 等使用 pyannote 的路線，Community-1 官方下載需要 Hugging Face 帳號、同意使用條件並設定 token，這一步要你本人完成；Mac 的 CoreML 路線另有模型來源。
- 結構檢查只確認時間涵蓋、文字未被改動與標記一致，不代表辨識正確；重要內容仍須回聽。
- 說話者分群是模型推測，不是身分證明。

授權：[MIT](LICENSE)。模型各有授權，見 [setup.md](references/setup.md)。
