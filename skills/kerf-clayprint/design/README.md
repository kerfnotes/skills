# Clayprint 設計層

Clayprint 的視覺規格。預設使用 clay 配色，原本的 B′ 深藍保留為第二套設計層範例；顏色、字級、邊界、線寬與斜線填色都由設計層提供。

- `tokens.json`：預設的 clay 設計層。
- `tokens.blue.json`：原本的 B′ 深藍設計層範例。
- `read.json`：閱讀版（`mode: "read"`）疊在設計層上的覆寫：字級、上下邊界（含標題到 `lede` 的 `ledeGap`、columns 正文到 `takeaway` 的 `takeawayGap`，各至少一個正文行高）、證據圖寬與容量（含填滿門檻 `minFill`、points 點數、panels 註行數）。現場與閱讀版都以精確行距（pt）排字，PowerPoint 的行高與版型估算一致；行高實值見 [spec.md](spec.md)。
- 設計層可選的 `screen.type` 區塊：HTML 的 CSS px 字級，`body`、`small`、`sub`、`title`、`display` 分別控制正文、小字、小標題、節標題與封面標題。內建 clay／blue 明填現行的 16／12／18／28／52 px，與簡報 `type`、閱讀版 `read.json`、列印 `print.type` 分開。舊自訂設計層未填的欄位，維持原本對應簡報字級除以 2 的換算（`small` 對應 `type.label.px`）；填齊即可獨立控制。報告 SVG 圖表採獨立預設，見下方全交付索引。
- 設計層的 `print` 區塊：報告列印的邊界（mm；`indent`、`gutter` 是 22／14 mm 線內側的正文內距）與字級（pt），由 `scripts/theme-css.js` 輸出成 `--cp-print-*` 變數；缺少時用預設值。
- `spec.md`：頁面格線、字級、線寬、刻度、來源列、標註規則、資料顯示、版型與 PowerPoint 輸出對應；色碼保留原始設計紀錄。
- `claude-design/`：第一版在 Claude Design 製作的 8 頁版型與 13 種圖表樣張，保留原始名稱與檔名。要在 Claude Design 裡打開才看得到畫面；匯出時附帶的執行檔沒有放進來。

## 全交付字級索引

先依交付用途選此表，再讀對應流程。數值是正式預設；實際預覽用來找套用回歸，不需再請使用者核准這組字級。自訂模板或使用者明確指定值優先，保留未授權修改的內容。

| 交付／用途 | 預設與單位 | preset 來源與套用方式 |
| --- | --- | --- |
| PPTX 現場 `present` | 正文 20 pt；圖表軸標／資料標籤／圖例 16 pt；頁標題 28、封面 52、副標 18、表格正文 16、表頭 12、一般標籤與來源／頁碼 12 pt | 自動生成：`tokens.json`／`tokens.blue.json` 的 `type`；設計 px ÷ 2 = PPTX pt。圖表與一般標籤／來源分開，原生與 SVG 圖表均採圖表預設。 |
| PPTX 閱讀 `read` | 正文 12 pt；圖表及表格 10 pt；來源／註腳／頁碼 9 pt；頁標題 22、封面 36、副標 14、一般標籤 10 pt | 自動生成：`read.json` 疊在當前設計層上，字級以設計 px 儲存，同樣除以 2。 |
| 螢幕 HTML | 正文 16、小字／來源 12、副標 18、節標題 28、封面 32–52 CSS px；圖表標籤 24 viewBox units | 自動生成：設計層 `screen.type`、報告圖表獨立預設與響應式 CSS。SVG 數字是內部座標單位，實際字級隨容器／viewBox 比例變動；不隨 present 圖表字級放大。 |
| HTML → print／PDF | 正文 11 pt、行距 16 pt；來源／圖說／小字 9 pt；節標題 24、副標／圖表標題 12、封面 30、摘要建議句 16 pt；圖表標籤與刻度均 24 viewBox units | 自動生成：設計層 `print.type`、`scripts/theme-css.js` 與報告 SVG 預設。A4 標準圖寬 146 mm、viewBox 寬約 980 時，24 units 約 10 pt；寬圖或其他尺寸另算。正文、表頭與小字使用列印 pt，不沿用螢幕 CSS px。 |
| 既有 PPTX | 依用途選上述 present／read pt 預設 | Agent 在副本上修改授權指定目標，保留內容與原生可編輯性；擷取快取不作全文重建模型。 |
| 既有 Word | 指定圖表 labels 10 pt、source／caption 9 pt；明確授權文字字級套版且無原模板時：封面 24、H1 16、H2 13、H3／方框標題 11 bold、正文 11、表格 10 pt | Agent 操作預設，沿用原模板優先；僅修改授權指定圖表／圖片或文字範圍，不新增 DOCX 全文生成器。 |
| 既有 Excel | 指定原生圖表 labels 10 pt、source 9 pt；明確授權工作表字級套版且無原模板時：工作表標題 16、節標題 12、表頭 10 bold、儲存格 10、註記 9 pt | Agent 操作預設；只改授權指定目標，保留公式、資料連結與工作表，不新增 XLSX 生成器。 |
| 既有 HTML | 螢幕與列印分別採上述 HTML／print 預設 | Agent 只套用授權容器／圖表／文字範圍，保留語意內容、表格與錨點。 |
| 獨立 SVG／PNG | 未指定使用場景時，以現場圖表 labels 16 pt 為名義基線；在 144 units/in 的設計尺度相當於 32 viewBox units | 沿用 `scripts/svg.js`／`scripts/png.js`。標準現場圖表區為 1144 × 669 units，名義約 7.94 × 4.65 in；加框／來源列後依實際 viewBox 與輸出尺寸重算。PNG 像素不自帶固定 pt，交付需記錄像素尺寸與預定實體尺寸。嵌入 Word／Excel／報告時依最終寬度重算為該媒介目標字級。 |

### 來源與尺寸換算

現場正文／圖表 20／16 pt、閱讀正文／圖表 12／10 pt，採用 [BCG 2018 Format Guide 第 26–27 頁的第三方轉載](https://www.scribd.com/document/895431699/Format-Guide)所載 Key Message／Detail 基線。這不是三家顧問公司的共同現行規範；繁中來源 9 pt、HTML、PDF、Office 與獨立圖檔等其餘數值均為 Clayprint 的媒介設計選擇。

PPTX pt 是原尺寸的名義字級。縮印後實際 pt = 名義 pt × 實際列印寬度 ÷ 原投影片寬度；13.333 in 投影片配滿 A4 橫式寬 297 mm 約為 0.88 倍，因此 12／10／9 pt 約成 10.5／8.8／7.9 pt，印表機邊界可能再縮小。這與直接生成 A4 報告的 11／9 pt 是不同路徑。

SVG 實際 pt = `font-size` viewBox units × 最終寬度（in）× 72 ÷ viewBox 寬度。先決定最終容器尺寸，再重算文字；不能把 SVG／PNG 縮放後仍稱固定 16 pt。預覽檢查換行、遮擋與來源，不用逐頁縮字、刪原稿數字或限制來消除警告；先修版型、合理重排或拆頁。

### 舊自訂設計層

未填的 `screen.type` 欄位維持舊換算：對應 `type` 的 `px / 2`，`small` 對應 `type.label.px`；填齊螢幕欄位才與簡報字級獨立。缺少 `print` 時由內建列印預設補足。舊圖表設定缺少專用 chart 欄位時沿用一般 label fallback；不要把自訂層 fallback 說成所有輸出都會強制升級。內建 preset 的跨媒介隔離與舊層相容性分開核對。

表頭線色由選用的 `color.tableRule` 決定，未填時用 `color.text`，與先前相同。`check-design.js` 只在填了這欄時核對色碼格式。

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
