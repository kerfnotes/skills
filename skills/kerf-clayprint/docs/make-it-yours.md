# 把 Clayprint 改成你的

**外觀**（顏色、字型、字級、間距、線寬）從[設計層](../design/README.md)改起。**內容流程、版型、圖種**還要調整 [SKILL.md](../SKILL.md)、[references/](../references/layouts.md) 與 `scripts/`，並更新相關測試。PowerPoint 內的字型由設計層的 `font.slide` 決定（預設微軟正黑體）；字寬估算以正黑體校準，換字型後要看預覽確認換行。

## 五個步驟

| 步驟 | 可以怎麼問 AI | 要拿到什麼才往下走 | Clayprint 對應 |
| --- | --- | --- | --- |
| 選參考與用途 | 這份參考哪些做法適合我的觀眾和用途？把保留與改動分開說明。 | 借用什麼、改什麼及理由。 | 填 [design/brief.md](../design/brief.md) 的參考、用途、取捨。 |
| 把要求說具體 | 這張圖要表達重點、順序，還是類別？依目的提出用色，說明各色用途。 | 看得懂的樣張與說得清楚的選擇。 | 改 `design/tokens.json` 的副本；圖種見 [references/charts.md](../references/charts.md)。 |
| 看成品與差距 | 把輸出轉成圖片和參考並排，先改最影響閱讀的一處給我比。 | 實際頁面與修改前後；分別檢查圖表和整份簡報。 | `node scripts/pptx.js examples/story.json out/mine.pptx`；可用 `node scripts/preview.js out/mine.pptx out/preview`。 |
| 整理成 skill | 哪些決定留在指引、哪些是設計設定、哪些要寫成程式或範本？ | AI 找得到指引，程式讀得到設定。 | `SKILL.md`、`references/`、`design/tokens.json`、`scripts/`。 |
| 驗證與保存 | 用 0、缺值、極小值重現問題；修好後保留測試，再用新稿看完整輸出。 | 錯誤能重現、測試通過、成品看過。 | `node scripts/check-design.js design/tokens.json`、`node evals/check.mjs examples/story.json evals/fixtures/example-script.md`、`npm test`。 |

## 只換外觀：從副本走一次

以下從 Clayprint 根目錄執行。先複製設計層；把你的參考與需求填進 [design/brief.md](../design/brief.md)，請 AI 依副本的完整結構修改顏色、字級、線寬與適用字型，保留未改欄位。

```sh
mkdir -p out
cp design/tokens.json out/mine.json
node scripts/check-design.js out/mine.json
node scripts/pptx.js examples/story.json out/original.pptx
CLAYPRINT_TOKENS=out/mine.json node scripts/pptx.js examples/story.json out/mine.pptx
```

檢查若有「失敗」，先修好再建檔；「警告」要看是否需直接標值或改用表格。有 PowerPoint，或裝了 LibreOffice，且有 `pdftoppm`、`ffmpeg` 時，分別執行 `node scripts/preview.js out/original.pptx out/preview-original` 與 `node scripts/preview.js out/mine.pptx out/preview-mine`。用同一份 `examples/story.json` 的兩版逐頁並排，先改最弱的一頁。PowerPoint 與 LibreOffice 都沒有時，可先看 SVG 圖表，整頁仍待預覽。

報告也用同一設計層；由 `report.json` 重建時，樣式與圖表會一起換色：

```sh
CLAYPRINT_TOKENS=out/mine.json node scripts/report.js examples/report.json out/mine-report.html
node evals/check-report.mjs out/mine-report.html evals/fixtures/explain-script.md
```

用瀏覽器看報告。手工組成的 HTML 報告用 `CLAYPRINT_TOKENS=out/mine.json node scripts/theme-css.js 報告.html` 只換樣式；其中由 `scripts/svg.js` 產生的 SVG，要用同一份圖表 JSON 重產。

### 故意做壞，再修好

[測試案例](../tests/fixtures/tokens.focus-gray.json)的配色只把預設 `color.focus` 改成與 `color.gray` 相同。複製它，執行 `node scripts/check-design.js out/focus-gray.json`：

```sh
cp tests/fixtures/tokens.focus-gray.json out/focus-gray.json
node scripts/check-design.js out/focus-gray.json
```

實際失敗訊息：

```text
失敗：color.focus #8F8D86 與 gray #8F8D86 在正常色覺下色差 ΔE 0.00（門檻 ≥ 15）：拉開 focus 與 gray 的亮度或色相，讓重點可辨識
Clayprint 設計層 focus-gray-test：未通過 47 項檢查，4 項失敗、2 項警告。
```

把 `out/focus-gray.json` 的 `color.focus` 改回 `#C2553A`，再執行 `node scripts/check-design.js out/focus-gray.json`。實際結果是 `Clayprint 設計層 focus-gray-test：通過 47 項檢查，0 項失敗、2 項警告。`；兩項是預設類別色警告。這示範的是檢查門檻，最後仍要看頁面是否符合用途。

## 守住資料判斷

| 判斷 | 程式與測試 |
| --- | --- |
| 0 是觀察值 | `scripts/core.js` 的 `formatValue`、`prepare`；`tests/core.test.js`、`tests/charts.test.js`。 |
| 缺值要揭露 | `scripts/core.js` 的圖表模型、`scripts/pptx.js` 的 `sourceRow`；`tests/null-behavior.test.js`。 |
| 增減好壞依指標判定 | `scripts/core.js` 的 `delta`；`tests/core.test.js`、`tests/charts.test.js`。 |
| 沒內容的版面格可省略，缺少的資料不能藏 | `scripts/pptx.js` 的 `emptyCell`、`sourceRow`；`tests/layouts-phase2.test.js`、`tests/null-behavior.test.js`。 |
| 類別超過上限按規則併入「其他」 | `scripts/core.js` 的 `categoryColors`、`KINDS.share`；`tests/core.test.js`、`tests/charts.test.js`。 |
| 每頁有來源列 | `scripts/pptx.js` 的 `sourceRow`、`evals/check.mjs`；`tests/evals.test.js`。 |

要改這些判斷，先寫新用途與預期結果，再一起改規則和測試；不要為了讓檢查通過而刪測試。
