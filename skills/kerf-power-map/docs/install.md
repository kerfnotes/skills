# Agent 安裝指引

收到安裝 Power Map 的請求時，由 agent 操作終端機、下載與放置檔案，依本流程完成檢查，遇到具體阻礙時回報。預設只安裝到目前專案，使用者指定其他範圍時才改變安裝位置。Power Map 只有 Markdown 與 HTML 檔，不需要額外工具或模型。

## 1. 放置 skill 檔案

| Agent | 專案內的安裝位置 |
| --- | --- |
| Codex | `.agents/skills/kerf-power-map/` |
| Claude Code | `.claude/skills/kerf-power-map/` |

先檢查目的地。若已是完整的 Power Map，沿用它並重新檢查；若包含其他內容或無法確認來源，保留內容並回報路徑衝突，不覆寫既有 skill。

目的地不存在時，把 repo 下載到暫存目錄，只複製 `skills/kerf-power-map/`。路徑由 agent 換成本次專案的絕對路徑，Claude Code 將 `.agents` 換成 `.claude`。

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

`rev-parse HEAD` 印出的是來源 commit，交付時要列出。若缺 Git，可下載 [main 分支 ZIP](https://github.com/kerfnotes/skills/archive/refs/heads/main.zip)，只複製其中的 `skills-main/skills/kerf-power-map/`。確認 `SKILL.md` 位於目的地根目錄，而不是多包一層。複製完成後暫存目錄可以刪除。

## 2. 檢查

- `SKILL.md` 的 `name` 是 `kerf-power-map`，與資料夾名稱相同。
- `references/case-library/index.md` 存在，且分類資料夾內有案例頁。
- 重新開啟 agent 或新對話後，skill 清單裡看得到 `kerf-power-map`。

## 3. 交付結果

列出：安裝絕對路徑、來源 commit、上述檢查結果，以及未驗證或受阻的項目。

安裝位置與載入方式依 [Codex 官方文件](https://developers.openai.com/codex/skills#where-to-save-skills)及 [Claude Code 官方文件](https://code.claude.com/docs/en/skills)。
