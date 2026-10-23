---
name: kerf-clayprint
description: "Clayprint 把文字稿做成簡報／PowerPoint 或連續閱讀的 HTML 報告，也把既有 PowerPoint、Word、Excel、HTML 套用 Clayprint 樣式。適用於內容視覺化；不適用於軟體或架構藍圖、只要大綱、圖片提示詞簡報。"
---

# Clayprint

把文字稿整理成簡報或 HTML 報告，也能將既有檔案套用設計層；以原稿和原檔為內容依據。

## 原則

1. 觀點在前，證據在後。
2. 一頁一個清楚的判斷：標題 `claim` 寫結論，主題放頁首小字 `kicker`。
3. 先寫結論，再選最能支持它的圖或版型。
4. 放不下就刪內容或拆頁，不逐頁縮字級；閱讀型簡報是整份換成較小字級，不是例外。
5. `claim` 點名的數字與項目要在當頁可見，強調項目要與主張一致。

每個版型都有對應的主張；原稿無法支持時就換版型，未決事項用沒有 `tag`／`focus` 的 `list` 或 `columns`。各版型的主張、欄位與容量見 [版型說明](references/layouts.md)。

常見骨架是工具箱，不是必填清單：

- 決策型：封面 → 主管摘要 → 現況／需求 → 證據 → 診斷或方案 → 決議事項；無數字時，封面後以帶 `focus` 的 `statement` 開場。每張證據頁都要被摘要或決議採用，孤立頁刪去。
- 說明型：封面 → 重點摘要 → 拆解 → 流程或時程 → 下一步。

簡報要會前寄出、讀者自己看而沒有人講解時，在 `story.json` 根層填 `"mode": "read"`，做成閱讀型簡報：字級較小、每頁容量較大，要說的話寫在頁面上，不寫在 `notes`。規則見[閱讀型簡報](references/layouts.md#閱讀型簡報)。

## 資料底線

- 不編造數字；沒有可畫的數字就不放圖表。無日期的流程用 `process`，不捏造月份。
- 畫面上的順序、期限、負責人與原因取自原稿；推論寫在 `notes`。
- 0 是觀察值。論證需要或讀者會預期看到的數字，若原稿未提供，在原位標「未提供」，並列入當頁來源列；若只是版面有那一格，而原稿沒提，就整格省略。缺值輸入與各圖處理方式見 [版型說明](references/layouts.md)和[圖表選單](references/charts.md)。
- 每頁填 `sources.source`；單位、期間只填已知內容。虛構稿註明「虛構示意資料」。推導值的算法與原始數字放當頁 `notes`；需要觀眾看見時寫 `sources.more`。`sources.more` 會上投影片，`notes` 不會；格式見 [驗收說明](evals/README.md)。

## 流程

以下指令從 skill 根目錄執行；需要 Node 22.7.0 以上。首次安裝、Node 版本不足或缺少套件時，先依 [agent 安裝指引](docs/install.md)完成安裝與驗證。先建立 `out/`，輸出統一放在此處；`script.md` 換成本次原稿。

1. 讀文字稿，確認聽眾、目的、可用數字、來源與資料缺口。使用者說明的背景優先；聽眾或目的不明且會改變取捨時，先問一次。
2. 選合適的骨架，寫故事線和每頁一句結論。
3. 依 [版型說明](references/layouts.md)挑支撐結論的版型；需要圖表時依 [圖表選單](references/charts.md)選圖。
4. 寫 `out/story.json`，每張內容頁在 `notes` 放 1～3 句講稿（要說的話、資料限制），計算另列；閱讀型簡報改把這些話寫在頁面上。執行 `node evals/check.mjs out/story.json script.md` 核對；範例：`node evals/check.mjs examples/story.json evals/fixtures/example-script.md`。
5. 執行 `node scripts/pptx.js out/story.json out/deck.pptx` 建檔。
6. 依 [預覽與交付](references/layouts.md#預覽與交付)執行 `node scripts/preview.js out/deck.pptx out/preview`；輸出 `page-N.png`、`sheet.png`（整份概覽）、`deck.pdf`。0 項容量警告只代表未偵測到溢出，仍逐頁找孤字與不均勻換行。
7. 依警告和預覽修正最弱的一頁，再重建、重驗。能派 subagent 時，可請不同 subagent 對照原稿與需求，分別檢查數字、版面和敘事，再整合修正。交付集中列：核心判斷、缺資料／未完成頁、最弱頁修改前後及原因、哪些圖為原生可編輯／SVG，以及「實際在 PowerPoint 改一個原生圖數值：完成／未驗」。編輯限制見 [設計差異](docs/design-diff.md)。

## 設計層與驗證

要改成自己的設計或流程時，讀 [改造步驟](docs/make-it-yours.md)。

預設 clay 設計層；切換 B′ 深藍範例與檢查自訂配色見 [設計層說明](design/README.md)。逐頁檢查判斷、數字、單位、期間、來源、缺值、遮擋與閱讀順序。驗收器通過只證明結構、數字對照和程式可建檔；獨立驗收見 [有數字稿](evals/with-numbers.md)與[無數字稿](evals/without-numbers.md)。

## 文字稿 → 報告

讀者要連續閱讀、轉寄或列印時，依 [報告流程](references/report.md)寫 `out/report.json`。
先寫讀者要帶走的一句話與每節判斷；有資料才加圖，圖表 JSON 填單位、期間與來源，圖說會自動組成。
執行 `node scripts/report.js out/report.json out/report.html` 產生報告，再用 `node evals/check-report.mjs out/report.html script.md` 核對。
核對通過後執行 `node scripts/pdf.js out/report.html out/print` 印成 PDF，處理填滿率與切頁警告並逐頁看 `page-NN.png`；找不到瀏覽器時 PDF 標「受阻」並附原因，其餘步驟繼續。

## 套用到既有檔案

先讀 [格式與保留原則](references/formats.md)，在副本上只換目標圖表或圖片。
Office 檔可用 `node scripts/extract.js 原檔 out.json` 擷取文字、表格與可讀的圖表快取。
交付時說明修改範圍、數據來源、讀不到的部分與實際預覽方式。
