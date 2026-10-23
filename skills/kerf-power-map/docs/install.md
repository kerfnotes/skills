# Agent 安裝指引

收到安裝 Power Map 的請求時，由 agent 操作終端機、下載與放置檔案，依本流程完成檢查，遇到具體阻礙時主動回報。預設只安裝到目前專案，使用者指定其他範圍時才改變安裝位置。Power Map 只有 Markdown 與 HTML 檔，不需要額外工具或模型。

## 1. 確認位置

| Agent | 專案內的安裝位置 |
| --- | --- |
| Codex | `.agents/skills/kerf-power-map/` |
| Claude Code | `.claude/skills/kerf-power-map/` |

先檢查目的地：

- 有 `references/map.md` 與 `references/books.md`：已是這一版，沿用它並重新檢查；更新版本屬於另一項工作。
- 有 `references/board.md` 或 `references/method.md`：是 2026-10-23 前的舊版 Power Map。保留既有內容，回報路徑與舊版本狀態，請使用者決定要不要換成新版，不要直接覆寫。舊版在 repo 裡已改名為 `kerf-power-map-deprecated`。
- 包含其他內容、失效連結或無法確認來源：保留既有內容並回報路徑衝突，不覆寫既有 skill，也不執行清理指令。

## 2. 取得 skill 檔案

目的地不存在時，把 repo 下載到暫存目錄，只複製 `skills/kerf-power-map/`。路徑由 agent 換成本次專案的絕對路徑；使用 Claude Code 時將 `.agents` 換成 `.claude`。

macOS／Linux：

```sh
POWER_MAP_SKILL="/absolute/path/to/project/.agents/skills/kerf-power-map"
KERFNOTES_TMP="$(mktemp -d)"
git clone --depth 1 https://github.com/kerfnotes/skills.git "$KERFNOTES_TMP/skills"
git -C "$KERFNOTES_TMP/skills" rev-parse HEAD
mkdir -p "$(dirname "$POWER_MAP_SKILL")"
cp -R "$KERFNOTES_TMP/skills/skills/kerf-power-map" "$POWER_MAP_SKILL"
```

Windows PowerShell：

```powershell
$PowerMapSkill = 'C:\absolute\path\to\project\.agents\skills\kerf-power-map'
$KerfnotesTmp = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid())
git clone --depth 1 https://github.com/kerfnotes/skills.git (Join-Path $KerfnotesTmp 'skills')
git -C (Join-Path $KerfnotesTmp 'skills') rev-parse HEAD
New-Item -ItemType Directory -Force (Split-Path $PowerMapSkill) | Out-Null
Copy-Item -Recurse (Join-Path $KerfnotesTmp 'skills\skills\kerf-power-map') $PowerMapSkill
```

`rev-parse HEAD` 印出的是來源 commit，交付時要列出。若缺少 Git，可由 agent 下載 [main 分支 ZIP](https://github.com/kerfnotes/skills/archive/refs/heads/main.zip)，只複製其中的 `skills-main/skills/kerf-power-map/`；確認 `SKILL.md` 位於目的地根目錄，而不是多包一層資料夾。複製完成後暫存目錄可以刪除。每個指令若失敗就先處理原因，成功後才進下一步。

## 3. 完成檢查

在安裝後的 skill 根目錄確認：

- `SKILL.md` 存在，`name` 是 `kerf-power-map`，與資料夾名稱相同。
- `references/books.md`、`references/map.md`、`references/map-template.html`、`references/stories.md` 存在且非空。
- `references/examples/` 有 `index.md`，以及它列出的範例 `.md` 與對應的 `.html` 地圖。
- `references/case-library/index.md` 存在，且各分類資料夾內有案例頁。
- 從使用者專案重新開啟 agent 或開新對話後，skill 清單裡看得到 `kerf-power-map`。Codex 可明確呼叫 `$kerf-power-map`；Claude Code 可用 `/kerf-power-map`。`agents/openai.yaml` 是顯示與提示資料，不能代替安裝路徑。

無法確認 agent 是否已載入 skill 時，回報「檔案已驗，agent 載入未驗」，不宣稱完整可用，也不為了載入而關閉使用者正在工作的對話。

## 4. 交付結果

交付時列出：安裝絕對路徑、來源 commit（ZIP 則列下載來源）、上述檢查結果，以及未驗證或受阻的項目。只清理本次下載的暫存。

安裝位置與載入方式依 [Codex 官方文件](https://developers.openai.com/codex/skills#where-to-save-skills)及 [Claude Code 官方文件](https://code.claude.com/docs/en/skills)為準。
