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

在安裝位置執行，確認轉錄紀錄的驗證與輸出程式可用（需要 Python 3.10 以上；Windows 用 `py -3`）：

```sh
python3 -m unittest discover -s tests
```

## 3. 準備本機工具與模型

先跑 `python3 "$WORDPRINT_SKILL/scripts/doctor.py" --model 0.6B --fix`：依序補齊標 `agent` 的例行安裝（Homebrew 套件、`mlx-qwen3-asr`、確認空間後下載所選 ASR 與 ForcedAligner 模型、說話者模型、建置 bridge），標 `you` 的（安裝 Homebrew、Xcode 命令列工具、完整磁碟取用權、Gemini 金鑰）一次只交給使用者一步，最後列出哪些路線已能用。不加 `--fix` 只檢查。明確選用 1.7B 時，所有 doctor 檢查與安裝命令都傳 `--model 1.7B`。判讀所選路線的檢查結果，勿只看 exit 0；Colab 可用也會讓 doctor 成功退出。沿用已能用的工具，只補缺少的項目。例行安裝由 agent 完成；帳號、同意條款與 token 只請使用者本人處理，agent 不代為同意，token 不進指令、檔案、run 紀錄或 Git。工具裝在獨立環境，不放進 skill 資料夾。

- Apple Silicon Mac：本機 worker，`mlx-qwen3-asr` 跑 Qwen3-ASR 0.6B／1.7B 與 ForcedAligner 0.6B，說話者用下方離線 bridge。
- Windows、Intel Mac、Linux 等：`doctor.py --fix` 用 uv 建 `~/.wordprint/torch-venv`（qwen-asr、NeMo、OpenCC Python 版，約 1.7 GB；Windows 用 winget 裝 uv 與 FFmpeg），跑 `scripts/torch_worker.py`；沒有 Python 時先 `winget install -e --id astral-sh.uv`，再用 `uv run --python 3.12 scripts/doctor.py --fix`。不想在本機裝，就用 `colab/wordprint.ipynb`。Gemini 引擎在哪都能用，只需 FFmpeg。

快取檢查不再以資料夾存在判定成功。Qwen 依 `refs/main` 指向的 snapshot 檢查必要設定、tokenizer 與全部權重分片；CoreML 依 bundle 設定檢查必要模型檔和權重。缺少、空白或不可讀的檔案會列出補齊方式。通過僅表示必要檔案齊全，沒有驗證權重 hash 或模型可載入性，仍須以下方實跑確認。Community-1 已內含分說話者所需的 embedding；獨立 WeSpeaker 用於選用的跨視窗聲音比對，doctor 分別列出必要的 `speaker-models` 與選用的 `speaker-embeddings`，後者缺少不會阻擋基本 `local-speakers` 路線。`--fix` 會補齊各自缺少的 bundle；只有檢查時不下載。

Mac：原生 ARM 的 Python 與 Homebrew，`ffmpeg`／`ffprobe`、OpenCC，`mlx-qwen3-asr` 裝在獨立環境（例如 `uv tool install mlx-qwen3-asr`）。模型預設準備 `Qwen/Qwen3-ASR-0.6B` 與 `Qwen/Qwen3-ForcedAligner-0.6B`；使用者選 1.7B 時，doctor 改用 `--model 1.7B`，只準備該 ASR 與同一對齊模型；下載前看大小與剩餘空間，之後一律離線讀快取。說話者模型 `aufklarer/Pyannote-Community-1-CoreML` 的快取放在 `~/Library/Caches/qwen3-speech/models/`，由 [speech-swift](https://github.com/soniqo/speech-swift#homebrew) 的 `speech`（macOS 15+）在安裝時連網抓取；`speech embed-speaker` 也用來比對長錄音不同視窗的聲音。

OpenCC 要有**命令列程式與 `s2twp.json`**，只有 Python binding 不夠；先試轉一句，不在 PATH 就用 `--opencc` 指定路徑。

Apple Silicon Mac 另外建置離線說話者 bridge（需要 Xcode Command Line Tools，`xcode-select --install`）：

```sh
sh "$WORDPRINT_SKILL/scripts/community1-bridge/build.sh"
```

最後一行印出 `Offline downloader guards passed; no models loaded.` 才算成功。產物在 `scripts/community1-bridge/build/`，不進 Git；沒有建置時，轉錄照樣完成但沒有說話者（stage `partial`）。

授權：Qwen 模型與 MLX 實作為 Apache-2.0。Community-1 為 CC-BY-4.0（Mac 用 CoreML 版本）。PyTorch worker 與 Colab 的說話者模型 NVIDIA Nemotron-3-Diarization 為 OpenMDW-1.1，不需帳號或 token；NeMo 釘在 commit `16b0ff2`（PyPI 3.0.0 載不了這個模型）。CoreML 版本另有上游模型卡與標示。只從上游下載，不打包權重、不繞過條件。下載或權限缺少時是安裝失敗，不能當成空白的成功逐字稿。

## 4. 短音檔驗證

用一段 10～30 秒、至少兩人說話的音檔跑完整流程：轉錄、對時、說話者分群、輸出逐字稿。macOS 可用內建語音合成自行產生：

```sh
say -v Meijia -o a.aiff "大家好，今天我們來測試本機轉錄。"
say -v "Eddy (Chinese (Taiwan))" -o b.aiff "好的，我是第二位說話者。"
ffmpeg -i a.aiff -i b.aiff -filter_complex "[0][1]concat=n=2:v=0:a=1" -ac 1 -ar 16000 sample.wav
```

其他系統改用 Colab 筆記本跑同一段錄音。Mac 上用 `head -1 "$(which mlx-qwen3-asr)"` 找到 worker 要用的 Python，再跑：

```sh
"$WORKER_PYTHON" "$WORDPRINT_SKILL/scripts/qwen_worker.py" --audio sample.wav --run-directory run-check --model 0.6B
python3 "$WORDPRINT_SKILL/scripts/transcript.py" render run-check/normalized-run.json --output out-check
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 "$WORKER_PYTHON" "$WORDPRINT_SKILL/scripts/qwen_worker.py" --audio sample.wav --run-directory run-offline --model 0.6B
```

驗證通過需同時符合：每個階段結束碼為 0；`run-check/state.json` 的 stage 是 `complete`；逐字稿涵蓋整段音檔；分出兩位說話者；`scripts/transcript.py validate` 通過；`out-check/transcript.html` 開得起來；離線快取模式重跑（上面第三行）仍是 `complete`。這只驗證快取可用；環境變數不是整個 Python 程序的網路隔離。worker 內的 Community-1 bridge 已自行套用 deny-network sandbox，外層再套 sandbox-exec 會在部分 macOS 環境觸發巢狀 sandbox 錯誤；完整斷網驗證需在實際斷網環境另測。

## 5. 交付結果

列出：安裝絕對路徑、來源 commit、作業系統與晶片、各工具版本、實際使用的模型 ID 與 revision、測試結果、短音檔驗證結果，以及未驗證或受阻的項目。分開寫「套件已安裝」「可以載入」「整套流程在這台電腦跑通」三種狀態，不以前者代替後者；沒有量測就不承諾記憶體需求或速度。

上游：[Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR)、[mlx-qwen3-asr](https://github.com/moona3k/mlx-qwen3-asr#installation)、[CoreML Community-1](https://huggingface.co/aufklarer/Pyannote-Community-1-CoreML)、[Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)、[Nemotron-3-Diarization](https://huggingface.co/nvidia/Nemotron-3-Diarization)、[OpenCC](https://github.com/BYVoid/OpenCC#installation)。

安裝位置與載入方式依 [Codex 官方文件](https://developers.openai.com/codex/skills#where-to-save-skills)及 [Claude Code 官方文件](https://code.claude.com/docs/en/skills)。
