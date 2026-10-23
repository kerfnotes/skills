# Kerf Skills

[Kerf](https://www.youtube.com/@kerfnotes) 在影片裡做過、分享過的 AI skills，全部放在這裡。每個資料夾都是一個完整的 skill，可以單獨安裝到 Codex 或 Claude Code。

| Skill | 做什麼 | 介紹影片 |
| --- | --- | --- |
| [Clayprint](skills/kerf-clayprint/) | 把文字稿整理成提出判斷、附上來源的簡報或 HTML 報告 | [從需要，到自己的工具](https://youtu.be/dIQ2amlA6HY) |
| [Wordprint](skills/kerf-wordprint/) | 在本機把錄音轉成逐字稿，附時間戳與說話者標記 | 製作中 |
| [Power Map](skills/kerf-power-map/) | 職涯策略軍師：用三本書的框架看懂誰拍板、這局該合作還是該硬，給能寄的稿或下一步，附一張權力地圖 | — |

## 安裝

打開想要的 skill 資料夾，照它 README 裡的「交給 agent 安裝」，把那段話交給 Codex 或 Claude Code。agent 會下載、安裝並驗證。

已經在用 [`skills`](https://www.npmjs.com/package/skills) CLI 的話，也可以列出全部 skill 再挑：

```sh
npx skills add kerfnotes/skills --list
```

授權：[MIT](LICENSE)。
