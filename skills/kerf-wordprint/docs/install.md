# Agent 安裝指引

收到安裝 Wordprint 的請求時，由 agent 操作終端機、下載與放置檔案，依本流程完成驗證，遇到具體阻礙時回報。預設只安裝到目前專案，使用者指定其他範圍時才改變安裝位置。

## 1. 放置 skill 檔案

| Agent | 專案內的安裝位置 |
| --- | --- |
| Codex | `.agents/skills/kerf-wordprint/` |
| Claude Code | `.claude/skills/kerf-wordprint/` |

先檢查目的地。若已是完整的 Wordprint，沿用它並重新驗證；若包含其他內容或無法確認來源，保留內容並回報路徑衝突，不覆寫既有 skill。

目的地不存在時，把 repo 下載到暫存目錄，只複製 `skills/kerf-wordprint/`。路徑由 agent 換成本次專案的絕對路徑，Claude Code 將 `.agents` 換成 `.claude`。

macOS／Linux：

```sh
WORDPRINT_SKILL="/absolute/path/to/project/.agents/skills/kerf-wordprint"
KERFNOTES_TMP="$(mktemp -d)"
git clone --depth 1 https://github.com/kerfnotes/skills.git "$KERFNOTES_TMP/skills"
git -C "$KERFNOTES_TMP/skills" rev-parse HEAD
mkdir -p "$(dirname "$WORDPRINT_SKILL")"
cp -R "$KERFNOTES_TMP/skills/skills/kerf-wordprint" "$WORDPRINT_SKILL"
```

Windows PowerShell：

```powershell
$WordprintSkill = 'C:\absolute\path\to\project\.agents\skills\kerf-wordprint'
$KerfnotesTmp = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid())
git clone --depth 1 https://github.com/kerfnotes/skills.git (Join-Path $KerfnotesTmp 'skills')
git -C (Join-Path $KerfnotesTmp 'skills') rev-parse HEAD
New-Item -ItemType Directory -Force (Split-Path $WordprintSkill) | Out-Null
Copy-Item -Recurse (Join-Path $KerfnotesTmp 'skills\skills\kerf-wordprint') $WordprintSkill
```

`rev-parse HEAD` 印出的是來源 commit，交付時要列出。複製完成後暫存目錄可以刪除。

## 2. 檢查 skill 本身

在安裝位置執行，確認轉錄紀錄的驗證與輸出程式可用：

```sh
python3 -m unittest discover -s tests
```

Windows 用 `py -3 -m unittest discover -s tests`。需要 Python 3.10 以上。

## 3. 準備本機工具與模型

依 [setup.md](../references/setup.md) 偵測系統、沿用已安裝的工具，只補缺少的項目：FFmpeg、OpenCC、Qwen3-ASR 0.6B、Qwen ForcedAligner，以及說話者分群工具。工具裝在獨立環境，不放進 skill 資料夾。

Apple Silicon Mac 另外建置離線說話者 bridge（需要 Xcode Command Line Tools，`xcode-select --install`）：

```sh
sh "$WORDPRINT_SKILL/scripts/community1-bridge/build.sh"
```

最後一行印出 `Offline downloader guards passed; no models loaded.` 才算成功。產物在 `scripts/community1-bridge/build/`，不進 Git；沒有建置時，轉錄流程會退回會連網的 `speech diarize`。

Community-1 的官方下載需要 Hugging Face 帳號、同意使用條件與 access token。這一步請使用者本人完成；agent 不代為同意條款，也不把 token 寫進指令、檔案或 Git。1.7B 只在使用者要求時才下載。

## 4. 短音檔驗證

用一段 10～30 秒、至少兩人說話的音檔跑完整流程：轉錄、對時、說話者分群、輸出逐字稿。macOS 可用內建語音合成自行產生：

```sh
say -v Meijia -o a.aiff "大家好，今天我們來測試本機轉錄。"
say -v "Eddy (Chinese (Taiwan))" -o b.aiff "好的，我是第二位說話者。"
ffmpeg -i a.aiff -i b.aiff -filter_complex "[0][1]concat=n=2:v=0:a=1" -ac 1 -ar 16000 sample.wav
```

其他系統請使用者提供可分享的短錄音。Mac 上用 `head -1 "$(which mlx-qwen3-asr)"` 找到 worker 要用的 Python，再跑：

```sh
"$WORKER_PYTHON" "$WORDPRINT_SKILL/scripts/qwen_worker.py" --audio sample.wav --run-directory run-check --model 0.6B
python3 "$WORDPRINT_SKILL/scripts/transcript.py" render run-check/normalized-run.json --output out-check
sandbox-exec -p '(version 1)(allow default)(deny network*)' "$WORKER_PYTHON" "$WORDPRINT_SKILL/scripts/qwen_worker.py" --audio sample.wav --run-directory run-offline --model 0.6B
```

驗證通過需同時符合：每個階段結束碼為 0；`run-check/state.json` 的 stage 是 `complete`；逐字稿涵蓋整段音檔；分出兩位說話者；`scripts/transcript.py validate` 通過；`out-check/transcript.html` 開得起來；斷網重跑（上面第三行）仍是 `complete`。

## 5. 交付結果

列出：安裝絕對路徑、來源 commit、作業系統與晶片、各工具版本、實際使用的模型 ID、測試結果、短音檔驗證結果，以及未驗證或受阻的項目。分開寫「套件已安裝」「可以載入」「整套流程在這台電腦跑通」三種狀態，不以前者代替後者。

安裝位置與載入方式依 [Codex 官方文件](https://developers.openai.com/codex/skills#where-to-save-skills)及 [Claude Code 官方文件](https://code.claude.com/docs/en/skills)。
