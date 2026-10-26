# Kerf Skills：給 Codex 與 Claude Code 的 AI 工作工具

[Kerf（kerfnotes）](https://www.youtube.com/@kerfnotes) 在影片裡做過、分享過的 AI skills：Clayprint 做簡報與報告、Wordprint 整理錄音逐字稿、Power Map 分析職場關係與職涯抉擇。每個資料夾都是一個完整的 skill，可以單獨安裝到 Codex 或 Claude Code，再用自然語言交代工作。

如果你已經在用 Codex 或 Claude Code，需要把文字稿做成會議簡報、把錄音整理成可回聽的逐字稿，或想釐清職場局面，可以從下面挑一個開始。各工具的環境需求與驗證限制寫在各自的 README。

| Skill | 做什麼 | 介紹影片 |
| --- | --- | --- |
| [Clayprint](skills/kerf-clayprint/) | 把文字稿整理成提出判斷、附上來源的 PowerPoint 簡報或 HTML／PDF 報告 | [從需要，到自己的工具](https://youtu.be/dIQ2amlA6HY) |
| [Wordprint](skills/kerf-wordprint/) | 在本機把錄音轉成逐字稿，附時間戳與說話者標記 | 製作中 |
| [Power Map](skills/kerf-power-map/) | 職涯策略軍師：用三本書的框架看懂誰拍板、這局該合作還是該硬，給能寄的稿或下一步，附一張權力地圖 | 尚無介紹影片 |

## 可以怎麼用

安裝對應 skill 後，把文字稿或音檔交給 agent，或直接描述你的局面。例如：

- **Clayprint**：「用 Clayprint 把這份文字稿做成簡報，給主管決定要不要擴大試行。」可先看 [AI 伺服器出口示範稿](skills/kerf-clayprint/examples/showcase/ai-exports.md)與[簡報、報告範例](skills/kerf-clayprint/README.md#範例)。
- **Wordprint**：「把今天早上兩段語音備忘錄合併，分出說話者，寫一份會議摘要。」預設在本機轉錄；平台支援與實測範圍見 [Wordprint README](skills/kerf-wordprint/README.md#驗證狀態)。
- **Power Map**：「我想內部轉調，但主管說月結沒人接，該怎麼讓他放人？」可先看[完整回覆與權力地圖範例](skills/kerf-power-map/README.md#範例)。

## 安裝

打開想要的 skill 資料夾，照它 README 裡的「交給 agent 安裝」，把那段話交給 Codex 或 Claude Code。agent 會下載、安裝並驗證。

已經在用 [`skills`](https://www.npmjs.com/package/skills) CLI 的話，也可以列出全部 skill 再挑：

```sh
npx skills add kerfnotes/skills --list
```

授權：[MIT](LICENSE)。
