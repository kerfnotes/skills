# 文字稿 → HTML 報告

報告供讀者連續閱讀、轉寄與列印；先寫清楚每節判斷，再選擇能支撐它的段落、表格或圖。內容寫在 `report.json`，由 `scripts/report.js` 產生 HTML；元件和簡報一樣只放有內容的，需要但原稿沒給的資料，在原位標「未提供」。完整示例見 [examples/report.json](../examples/report.json) 與產物 [examples/report.html](../examples/report.html)，原稿見 [explain-script.md](../evals/fixtures/explain-script.md)。[assets/report.html](../assets/report.html) 是同一套元件的 HTML 原型，供手工修改既有報告時參考。

## 流程

1. 讀原稿，寫下讀者要帶走的一句話；替每節先寫一句判斷。確認對象、單位、期間、來源與缺口，不補造數字。
2. 寫 `out/report.json`：封面、摘要，再依判斷寫各節的元件。摘要左側放建議，右側只放支撐它的數字。欄位見下方〈report.json〉。
3. 有數據才放圖。每張圖的輸入另存 JSON（格式見[圖表選單](charts.md)），在 `chart` 元件填相對於 `report.json` 的路徑。圖與表各自自動編號：圖上方是「圖 N」標籤與標題，圖下方的圖說由圖表 JSON 的單位、期間、`note`、元件的 `note` 與來源自動組成，所以圖表 JSON 必須填 `source`；表格同樣「表 N」與標題在上，元件填了 `note` 或 `source` 就在表下方列出。無數字時使用段落、清單或流程。
4. 執行 `node scripts/report.js out/report.json out/report.html` 產生報告，再執行 `node evals/check-report.mjs out/report.html script.md`，核對可見文字與 SVG 數字、未填範本標記及每圖來源。座標軸刻度（`data-tick`）和簡報驗收一樣不核對，產生器加的「圖 N」「表 N」標籤（`data-label`）也不核對；資料標籤與衍生值仍須來自原稿，或在同節寫出可核對的加減算式。範例：`node scripts/report.js examples/report.json out/report.html`，再 `node evals/check-report.mjs out/report.html evals/fixtures/explain-script.md`。
5. 執行 `node scripts/pdf.js out/report.html out/print` 輸出 PDF（見下方〈列印 PDF〉），處理警告後逐頁看 `page-NN.png`，檢查分頁、圖表與表格有無切斷；要轉寄就用瀏覽器看手機寬度，檢查閱讀順序與表格橫向捲動。驗收器無法代替視覺檢查。
6. 交付 HTML、`report.json` 與每張圖的輸入 JSON。和簡報一樣，交付說明集中列出：讀者要帶走的那句話、缺的資料、時間不夠還沒修好的地方。

## report.json

根物件有 `title`、`message`（讀者要帶走的一句話）、選用的 `kicker`、`meta`（封面資訊，至多三項 `{label, value}`）、`summary` 和依閱讀順序排列的 `sections`。三節以上自動加目錄（只列節標題，不印頁碼）。列印時第一頁是印到紙邊的封面色帶加目錄與摘要，各節從第二頁開始並在頁中接續；選用 `cover: "page"` 改成整頁封面，目錄與摘要移到第二頁。

`summary` 是 `{kicker?, claim, body?, items}`：`claim` 寫建議，`items` 建議 2～3 格 `{label, value, unit?, digits?}`。`value` 填數字或文字；`null` 在原位標「未提供」，`0` 是觀察值。

每節是 `{id?, kicker?, claim, lede?, blocks, sources?}`：`claim` 寫本節判斷，`lede` 交代範圍與口徑，`id` 是目錄錨點（英文，省略時自動編號），`sources` 是本節末「來源與附註」的文字陣列。`blocks` 依順序放元件，欄位盡量和簡報版型相同：

| `type` | 用途 | 欄位 |
| --- | --- | --- |
| `text` | 段落，說明原因、限制或下一步。 | `text` |
| `callout` | 需要讀者停下來記住的一句結論；列印時是 24 pt 強調色、無框的引言。 | `text` |
| `chart` | 有數據可畫時。 | `title`（圖上方標題與無障礙名稱）、`chart`（圖表 JSON 路徑或物件）、選用 `note`（圖下方附註）、`wide`（`true` 時列印從左 22 mm 起全寬） |
| `table` | 需要逐格比對精確數值；列印時八列以內不分頁，超過八列才分頁並重複表頭。 | 同[表格圖種](charts.md#表格-table)：`columns`、`rows`、選用 `total`、`emphasis`、`caption`（表上方標題）；另可選 `source`、`note`（表下方小字）與 `wide` |
| `compare` | 在幾個方案間取捨。 | 同簡報 `compare`：`rows`、`options: [{name, recommended?, values}]`、選用 `caption` |
| `list` | 逐項列出原因、觀察或待查問題。 | `items: [{heading, body?}]` |
| `process` | 有先後順序與目前位置。 | `steps: [{heading, body?}]`、選用 `focus`（零起算） |
| `close` | 已確認的工作。 | 同簡報 `close`：`rows: [{task, owner?, due?}]`、選用 `caption`；沒人填的欄整欄省略 |
| `missing` | 論證需要但原稿沒給的資料。 | `text`，畫面顯示「未提供：…」 |

報告與簡報共用目前生效的設計層，預設為 clay。`scripts/report.js` 產生時同時寫入樣式與圖表顏色；換成 blue 就用 `CLAYPRINT_TOKENS=design/tokens.blue.json node scripts/report.js out/report.json out/report.html` 重建。手工組成的報告用 `node scripts/theme-css.js report.html` 同步樣式，其中由 `scripts/svg.js` 產生的圖也要用同一設計層重產。沒有檔名時，`node scripts/theme-css.js` 會把 CSS 印到終端。

範例兩圖的資料分別在 [時間圖 JSON](../examples/report-time.json) 與 [品質圖 JSON](../examples/report-quality.json)。

## 列印 PDF

驗收通過後，從 skill 根目錄執行（範例：先 `node scripts/report.js examples/report.json out/report.html`）：

```sh
node scripts/pdf.js out/report.html out/print
```

第二個參數是輸出資料夾，會產生 `report.pdf`（檔名沿用 HTML 主檔名）、每頁 `page-NN.png` 與整份縮圖 `sheet.png`。預設 A4 白紙；`--letter` 改印 Letter，`--paper clay` 改印米色滿版，兩者可並用。這兩個選項會在 HTML 同一資料夾寫一份暫存副本並在 `<html>` 加上 `data-size="letter"`、`data-paper="clay"`，印完即刪除，來源 HTML 不變。

腳本依序找 `CLAYPRINT_CHROME` 指定的執行檔、PATH 上的 `google-chrome`、`chromium`、`chrome`、`msedge`，再找 macOS 與 Windows 的 Chrome、Chromium、Edge、Brave 安裝位置，以 `--headless --disable-gpu --no-pdf-header-footer --print-to-pdf` 列印；另需 Poppler 的 `pdftoppm`、`pdftotext` 與 `ffmpeg`。找不到瀏覽器時結束碼非零並提示設定 `CLAYPRINT_CHROME`；此時 PDF 標「受阻」並附原因，HTML 與驗收照常交付。

結尾固定印「印出 N 頁（A4）；填滿率 79／97／67／41%。」。填滿率是每頁最後一列墨水在版心（上 12 mm 到離底 15 mm）的高度占比，第 1 頁從紙邊算起。下列警告只提醒、不改結束碼，逐條處理後重印：

| 警告 | 意思與改法 |
| --- | --- |
| 第 N 頁只填 X% | 末頁以外低於 70%，通常是下一個圖或表放不下被推到下一頁。把下一節開頭提上來，或把這頁的圖設 `wide: true` 拉高。 |
| 第 N 頁內容超出右邊界約 M mm | 有墨水伸到離右紙邊 14 mm 以外，Chrome 會整頁縮小。減少表格欄數或設 `wide: true`。 |
| 圖 N 的標題在第 A 頁、來源在第 B 頁 | 圖被切開。縮短圖上方的段落，或改小圖。 |
| 表 N 跨第 A–B 頁 | 八列以內的表格被切開（只檢查有 `source` 的表）。縮短表上方的段落。 |

印完逐頁檢查，尤其留意多頁表格、圖說與圖是否分離，以及封面與章節開頭的位置。轉寄前在手機寬度看一次；寬表格應在自己的容器內橫向捲動，頁面本身不應橫向溢出。
