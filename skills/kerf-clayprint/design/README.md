# Clayprint 設計層

Clayprint 的視覺規格。預設使用 clay 配色，原本的 B′ 深藍保留為第二套設計層範例；顏色、字級、邊界、線寬與斜線填色都由設計層提供。

- `tokens.json`：預設的 clay 設計層。
- `tokens.blue.json`：原本的 B′ 深藍設計層範例。
- `read.json`：閱讀版（`mode: "read"`）疊在設計層上的覆寫：字級、上下邊界（含標題到 `lede` 的 `ledeGap`、columns 正文到 `takeaway` 的 `takeawayGap`，各至少一個正文行高）、證據圖寬與容量（含填滿門檻 `minFill`、points 點數、panels 註行數）。閱讀版以精確行距（pt）排字，PowerPoint 的行高與版型估算一致。
- 設計層可選的 `screen.type` 區塊：HTML 的 CSS px 字級，`body`、`small`、`sub`、`title`、`display` 分別控制正文、小字、小標題、節標題與封面標題。內建 clay／blue 明填現行的 16／12／18／28／52 px，與簡報 `type`、閱讀版 `read.json`、列印 `print.type` 分開。舊自訂設計層未填的欄位，維持原本對應簡報字級除以 2 的換算（`small` 對應 `type.label.px`）；填齊即可獨立控制。圖表 SVG 的 viewBox 字級仍沿用既有圖表設計規則。
- 設計層的 `print` 區塊：報告列印的邊界（mm；`indent`、`gutter` 是 22／14 mm 線內側的正文內距）與字級（pt），由 `scripts/theme-css.js` 輸出成 `--cp-print-*` 變數；缺少時用預設值。
- `spec.md`：頁面格線、字級、線寬、刻度、來源列、標註規則、資料顯示、版型與 PowerPoint 輸出對應；色碼保留原始設計紀錄。
- `claude-design/`：第一版在 Claude Design 製作的 8 頁版型與 13 種圖表樣張，保留原始名稱與檔名。要在 Claude Design 裡打開才看得到畫面；匯出時附帶的執行檔沒有放進來。

從 skill 根目錄執行；`CLAYPRINT_TOKENS` 可指定另一份設計層，相對路徑從目前工作目錄解析：

```sh
node scripts/pptx.js examples/story.json out/story.pptx
CLAYPRINT_TOKENS=design/tokens.blue.json node scripts/pptx.js examples/story.json out/story-blue.pptx
node scripts/check-design.js
node scripts/check-design.js design/tokens.blue.json
npm test
```

`node scripts/check-design.js [tokens.json]` 省略檔案時檢查目前生效的設計層；明確指定檔案則只檢查該檔。檢查涵蓋文字對比、標籤可讀性、焦點與類別的色差、色盲模擬，以及有序配色的明暗與色相。警告會列出需要直接標值或表格的情況；有失敗時結束碼為 1，通過為 0。`npm test` 同時要求 clay 與 blue 通過設計層檢查。

範例資料都是虛構的「河港市共享單車」。
