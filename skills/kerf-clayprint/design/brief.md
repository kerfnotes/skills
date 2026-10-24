# 設計層需求範本

把方括號填好，連同可公開的參考圖片或連結及 `design/tokens.json` 交給 AI。

- 參考（圖片或連結）：[貼上；指出想借用的細節]
- 用途與觀眾：[成品要幫誰做什麼決定]
- 要保留什麼：[例如閱讀順序、留白、直接標值]
- 要改什麼：[例如色彩、字級、線寬；說明原因]
- 必須沿用的品牌色：[色碼與用途；沒有就寫無]
- 語氣：[例如冷靜、活潑、嚴謹]
- 字型限制：[製作與收件環境可用的字型；寫明 PowerPoint 需要的中文字型]
- 要避開的做法：[例如低對比、難辨的類別色]

各媒介字級與單位依[全交付字級索引](README.md#全交付字級索引)；保留螢幕、投影片與列印的獨立設定。

請依 `design/tokens.json` 的**完整結構**輸出可儲存的 JSON，不要省略未修改的欄位，也不要只給色票或說明。頂層 key 須保留 `name`、`version`、`slide`、`margin`、`chartArea`、`font`、`type`、`stroke`、`sourceRow`、`color`、`textOnFill`、`categoryRules`、`delta`、`dataDisplay`、`heatmap`、`fill`、`layoutFields`、`export`；未要求改的規則照原檔保留。

請逐一說明並設定色彩職務：`color.text` 正文、`textSecondary` 次要文字、`title` 標題、`grid` 格線、`gray` 非重點、`focus` 單一重點、`ordered` 有序深淺、`categorical` 無序類別、`other` 併入其他、`better` 改善、`worse` 惡化、`unchanged` 不變、`dark` 深底、`onDark` 深底字與一般淺底、`tint` 淡底；同步更新 `textOnFill` 的字色對照，以及 `type`、`fill` 內對應的色碼。`font` 的字型陣列（SVG／報告用）與 `font.slide`（PowerPoint 內唯一使用的字型，收件者電腦必須有，預設微軟正黑體）、`type` 的字級與字重、`stroke` 的線寬也要依需求調整。不要把正負號當成好壞的替代訊號。

拿到後先跑 `node scripts/check-design.js 你的檔`，修正失敗並評估警告，再看實際成品。
