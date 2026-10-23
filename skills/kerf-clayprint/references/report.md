# 文字稿 → HTML 報告與 PDF

報告供讀者連續閱讀、轉寄與列印；先寫清楚每節判斷，再選擇能支撐它的段落、表格或圖。內容寫在 `report.json`，由 `scripts/report.js` 產生 HTML，`scripts/pdf.js` 印成 PDF。元件和簡報一樣只放有內容的，需要但原稿沒給的資料，在原位標「未提供」。

完整示例見 [examples/report.json](../examples/report.json) 與產物 [examples/report.html](../examples/report.html)，原稿見 [explain-script.md](../evals/fixtures/explain-script.md)：三節加目錄、封面橫幅、自動編號的兩張圖與一張表（其中一張圖 `wide: true`）、一段引言。兩張圖的資料在 [時間圖 JSON](../examples/report-time.json) 與 [品質圖 JSON](../examples/report-quality.json)。[assets/report.html](../assets/report.html) 是同一套元件的 HTML 原型，供手工修改既有報告時參考。

## 流程

固定三步：產生 HTML → 驗收 → 印 PDF。

1. 讀原稿，寫下讀者要帶走的一句話；替每節先寫一句判斷。確認對象及其先備知識，依 [SKILL.md 原則 6](../SKILL.md#原則)安排解釋並在交付前檢查理解斷點；核對單位、期間、來源與缺口，不補造數字。
2. 寫 `out/report.json`：封面、摘要，再依判斷寫各節的元件。摘要左側放建議，右側只放支撐它的數字。欄位見下方〈report.json〉。有數據才放圖：每張圖的輸入另存 JSON（格式見[圖表選單](charts.md)），圖表 JSON 必須填 `source`；無數字時使用段落、清單或流程。
3. 產生 HTML：`node scripts/report.js out/report.json out/report.html`，結尾印「完成：N 節、M 張圖，K 項警告」（節數含摘要）。
4. 驗收：`node evals/check-report.mjs out/report.html script.md`，核對所有可見文字與 SVG 數字、未填的 `{{…}}` 示意文字，以及每張圖都有含「來源」的圖說。座標軸刻度（`data-tick`）和簡報驗收一樣不核對，產生器加的「圖 N」「表 N」標籤（`data-label`）也不核對；其他數字，包括摘要、引言與資料標籤，都必須出現在原稿，或在同節寫出可核對的加減算式。範例：`node scripts/report.js examples/report.json out/report.html`，再 `node evals/check-report.mjs out/report.html evals/fixtures/explain-script.md`。
5. 印 PDF：`node scripts/pdf.js out/report.html out/print`（見下方〈列印 PDF〉）。逐條處理警告後重印，再逐頁看 `page-NN.png`。找不到瀏覽器時 PDF 標「受阻」並附原因，HTML 與驗收照常交付。
6. 要轉寄就用瀏覽器看手機寬度：寬表格與圖應在自己的容器內橫向捲動，頁面本身不應橫向溢出。驗收器與列印檢查都無法代替視覺檢查。
7. 交付 HTML、PDF、`report.json` 與每張圖的輸入 JSON。和簡報一樣，交付說明集中列出：讀者要帶走的那句話、缺的資料、時間不夠還沒修好的地方。

## report.json

根物件：

| 欄位 | 說明 |
| --- | --- |
| `title` | 報告標題；也印在第 2 頁起的頁尾。 |
| `message` | 讀者要帶走的一句話，印在封面。 |
| `kicker` | 選用，封面標題上方的小字。 |
| `meta` | 選用，封面資訊 `[{label, value}]`，建議至多三項，超過會警告；一律留在封面。 |
| `cover` | 選用。省略時第 1 頁是印到紙邊的封面橫幅，下面接目錄與摘要；填 `"page"` 時第 1 頁只有整頁封面，目錄與摘要移到第 2 頁、接著各節。 |
| `summary` | 選用，`{kicker?, claim, body?, items}`：`claim` 寫建議，`items` 建議 2～3 格 `{label, value, unit?, digits?}`，超出會警告。 |
| `sections` | 依閱讀順序排列的節；三節以上自動加目錄。 |

摘要的 `value` 填數字或文字；`null` 在原位標「未提供」，`0` 是觀察值。數字沒填 `digits` 時照數值本身的小數位顯示（24.7 印成 24.7），填了才照位數四捨五入，和簡報一致。

目錄只在三節以上出現，列「節小字：節標題」，不印頁碼（摘要不算一節）。

每節是 `{id?, kicker?, claim, lede?, blocks, sources?}`：`claim` 寫本節判斷，`lede` 交代範圍與口徑，`id` 是目錄錨點（英文開頭，省略時自動編號；`section-N` 與 `summary-title` 保留給產生器），`sources` 是本節末「來源與附註」的文字陣列。`blocks` 依順序放元件，欄位盡量和簡報版型相同：

| `type` | 用途 | 欄位 |
| --- | --- | --- |
| `text` | 段落，說明原因、限制或下一步。 | `text` |
| `callout` | 需要讀者停下來記住的一句結論。螢幕是色框；列印是引言：24 pt 強調色、一般字重、無框，對齊左 22 mm 線。 | `text` |
| `chart` | 有數據可畫時。 | `title`（圖上方標題與無障礙名稱）、`chart`（圖表 JSON 路徑，相對於 `report.json`；或圖表物件）、選用 `note`（圖下方附註）、`wide` |
| `table` | 需要逐格比對精確數值。 | 同[表格圖種](charts.md#表格-table)：`columns`、`rows`、選用 `total`、`emphasis`、`caption`（表上方標題）；另可選 `note`、`source`（表下方小字）與 `wide` |
| `compare` | 在幾個方案間取捨。 | 同簡報 `compare`：`rows`、`options: [{name, recommended?, values}]`、選用 `caption` |
| `list` | 逐項列出原因、觀察或待查問題。 | `items: [{heading, body?}]` |
| `process` | 有先後順序與目前位置。 | `steps: [{heading, body?}]`、選用 `focus`（零起算） |
| `close` | 已確認的工作。 | 同簡報 `close`：`rows: [{task, owner?, due?}]`、選用 `caption`；沒人填的欄整欄省略 |
| `missing` | 論證需要但原稿沒給的資料。 | `text`，畫面顯示「未提供：…」 |

圖與表的結構：

- 圖與表各自自動編號。圖上方是「圖 N」標籤與 `title`；圖下方的圖說（figcaption）依序是單位、期間、附註、來源，由圖表 JSON 的 `unit`、`period`、`note`、`source` 與元件的 `note` 組成，缺值項目也寫進附註。
- 表的「表 N」標籤與 `caption` 在表上方；填了 `note` 或 `source` 就在表下方印「附註：…｜來源：…」。
- 預設寬度是正文欄，列印時可伸到離右紙邊 14 mm（A4 寬 146 mm）；`wide: true` 從左 22 mm 線起全寬（A4 寬 174 mm），適合長標籤或多欄。
- 列印時圖、表、引言、摘要、清單（`list`）、流程（`process`）、比較（`compare`）與追蹤事項表（`close`）都整塊不切頁；表格超過八列才可分頁，並在下一頁重複表頭。

報告與簡報共用目前生效的設計層，預設為 clay。`scripts/report.js` 產生時同時寫入樣式與圖表顏色；換成 blue 就用 `CLAYPRINT_TOKENS=design/tokens.blue.json node scripts/report.js out/report.json out/report.html` 重建。手工組成的報告用 `node scripts/theme-css.js report.html` 同步樣式，其中由 `scripts/svg.js` 產生的圖也要用同一設計層重產。沒有檔名時，`node scripts/theme-css.js` 會把 CSS 印到終端。

## 列印版面

螢幕 HTML 維持 940 px 版面與米色底；列印另有一套版心，不需手動設定：

- 紙張預設 A4 白紙。版心左 50 mm、正文欄 135 mm、右 25 mm，上 12 mm、下 15 mm；節標題、目錄、引言與全寬圖對齊左 22 mm 線。
- 字級：正文 10.5 pt、行距 16 pt；節標題 24 pt 強調色加一條色線；摘要的建議句 16 pt；小節與圖表標題 12 pt；軸標約 8 pt；圖說、來源與頁尾 7 pt。
- 頁尾在右下：「報告名 | 頁碼 / 總頁數」；手工 HTML 的 `<html>` 沒有 `--report-title` 時只印「頁碼 / 總頁數」。第 1 頁沒有頁尾，封面印到紙邊。
- 第 1 頁放封面、目錄與摘要並以分頁結束，各節從第 2 頁開始；節與節在頁中接續，不另起新頁。節標題與其後第一段同頁。第 1 頁放不下時，溢到第 2 頁的部分會多縮排，請縮短摘要。
- 圖、表、引言、摘要、清單、流程、比較與追蹤事項表整塊不切：剩餘空間放不下就整塊移到下一頁，上一頁留白。排元件順序時把長的清單或表放在段落之後、不要接在另一個整塊元件後面，或拆成兩個較短的元件。

## 列印 PDF

從 skill 根目錄執行（範例：先 `node scripts/report.js examples/report.json out/report.html`）：

```sh
node scripts/pdf.js out/report.html out/print
```

第二個參數是輸出資料夾，會產生 `report.pdf`（檔名沿用 HTML 主檔名）、每頁 `page-NN.png` 與整份縮圖 `sheet.png`；只有一頁時沒有 `sheet.png`（`report.js` 產生的報告至少兩頁，手工單頁 HTML 才會遇到）。`--letter` 改印 Letter，左右邊界維持同樣的毫米數；`--paper clay` 改印米色滿版；兩者可並用。這兩個選項會在 HTML 同一資料夾寫一份暫存副本，在 `<html>` 加上 `data-size="letter"`、`data-paper="clay"`，印完即刪除，來源 HTML 不變。

腳本依序找 `CLAYPRINT_CHROME` 指定的執行檔、PATH 上的 `google-chrome`、`chromium`、`chrome`、`msedge`，再找 macOS 與 Windows 的 Chrome、Chromium、Edge、Brave 安裝位置，以 headless 模式列印；另需 Poppler 的 `pdftoppm`、`pdftotext` 與 `ffmpeg`。不認得的參數（例如打錯的 `--leter`，或把 `--paper clay` 包成一個參數）與 `clay` 以外的紙色會印用法並以結束碼 2 結束。找不到瀏覽器時印「找不到 Chrome、Edge、Chromium 或 Brave；設 CLAYPRINT_CHROME 指向瀏覽器執行檔後重跑。」並以非零結束碼結束。

### 讀輸出

結尾固定兩行，範例報告印出：

```text
PDF：…/out/print/report.pdf；每頁 PNG 與 sheet.png 在 …/out/print
印出 4 頁（A4）；填滿率 79／98／89／41%。
```

填滿率是每頁最後一列墨水的位置占版心高度的比例：從上邊界 12 mm 量到離紙底 15 mm，頁尾不算。第 1 頁從紙張上緣算起，因為封面印到紙邊。末頁不檢查填滿率。

### 警告

警告寫在結尾兩行之前，只提醒、不改結束碼。逐條處理後重印：

| 警告 | 原因與改法 |
| --- | --- |
| `第 1 頁只填 X%：縮短摘要或目錄，或把下一節的開頭段落放進第 1 頁前的摘要。` | 第 1 頁固定在摘要後分頁；低於 70% 通常是摘要整塊放不下，被推到第 2 頁。縮短摘要或目錄，讓摘要留在第 1 頁。 |
| `第 N 頁只填 X%：把被推到下一頁的整塊元件前移，或在它前面加一段文字。` | 第 2 頁起、末頁以外低於 70%，通常是下一個圖、表、引言、清單、流程、比較或追蹤事項表整塊放不下，被推到下一頁。把那個元件移到較前面，或在它前面補一段文字填滿這頁。 |
| `內容超出右邊界，整份被縮成 X%（第 N 頁起）：…` | 有內容比版面寬，Chrome 把整份文件等比縮小（正文欄左緣離開 50 mm 線），所以只警告一次。減少表格欄數或設 `wide: true`。 |
| `第 N 頁內容超出右邊界約 M mm：…` | 有墨水伸到離右紙邊 14 mm 以外；Chrome 遇到右側溢出會整頁縮小。減少表格欄數或設 `wide: true`。封面橫幅與色線本來就印到紙邊，不算溢出。 |
| `圖 N 的標題在第 A 頁、來源在第 B 頁：…` | 圖被切開：標籤所在頁和其後第一行「來源」不同頁。縮短圖上方的段落，或改小圖。 |
| `表 N 跨第 A–B 頁：…` | 八列以內的表被切開。只檢查填了 `source` 的表；超過八列的表本來就可分頁。縮短表上方的段落。 |

印完逐頁看 PNG，尤其留意多頁表格、圖說與圖是否分離，以及封面與章節開頭的位置。轉寄前在手機寬度看一次。
