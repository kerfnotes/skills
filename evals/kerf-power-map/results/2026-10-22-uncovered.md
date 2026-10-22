# 2026-10-22 六種圖型以外的兩則情境

## 為什麼跑

2026-10-22 討論地圖要不要「更豐富」時，有人提議替案例庫裡沒有專屬圖型的機制（承諾落實、資源與依賴等）新增圖型。Fable 審閱後認為不必：board.md §3 已有退路「六種都不合時，挑最小、最能說清卡點的結構；對照表也算地圖」。這輪用兩則刻意落在六種圖型以外的情境，量現行 v2.1 的退路夠不夠用。

- [commitment-verbal-support.md](../scenarios/commitment-verbal-support.md)：處長說支持，但沒人負責、也沒日期。
- [dependence-boss-wont-release.md](../scenarios/dependence-boss-wont-release.md)：月結只有我會，主管不放人。

## 預先登記的判定（作答前寫好，結果出來後不改）

- 量的版本：`power-map-v2.1` 分支，commit `8f8df62`（map-check 已加第 8 項）。每則跑 3 次。
- **commitment-verbal-support**
  - 不加圖型：3 次裡至少 2 次共通地圖檢查 A～E 有 4 項以上通過，而且 #1（圖能幫使用者選第一步）至少 2 次通過。
  - 加「承諾帳」：E（圖沒有把正文搬進格子）有 2 次以上判否，或 #1 有 2 次以上判否。做法是疑慮對照的變體，欄名改成「他說過的｜能檢查的版本缺什麼」：board.md §3 加一行、加一個範例，不加新 CSS。加完重跑這則 3 次。
  - 兩邊都不符合時不加，結果寫進「下一輪要改的」。
- **dependence-boss-wont-release**：只記錄，不論結果都不加圖型。#1 或 E 有 2 次以上判否時，寫進「下一輪要改的」，由使用者決定。
- 正文條件沒過的，這輪只記錄，不修。

## 方法

- 作答者：6 個新開的子代理（Agent 工具，沒指定 model，沿用主代理 Claude Opus 5.5）。只讀複製到兩個 worktree 以外暫存資料夾的 skill 目錄，以及各情境「使用者輸入」那一節。
- 地圖：
  - 截圖用 html_preview，375 寬、深色。截圖都在作答者最後一次存檔之後截。
  - map-check（偏離 run.md）：沒在 html_preview 裡跑，改在 T3 的協作瀏覽器用 localhost 開地圖，放進 375 寬的 iframe 跑同一份 `map-check.js`（`8f8df62`）。差別只在沒有注入主題變數，七項檢查都不依賴主題。6 張都是 7/7 PASS。
- 評審：GPT-6.1-Sol（xhigh），一位，新開，沒參與改版也沒參與作答。評審拿到使用者輸入、回覆正文、地圖 HTML、375 截圖、map-check 輸出、該則通過條件與共通檢查 A～E，有實際打開截圖。
- 主代理抽查 4 條判否，原文都對得上：commitment-2 #2、commitment-3 #4、dependence-2 #7、dependence-3 #8。
- 每則 3 次，沒有舊版基準。逐條判定與作答原文沒有進 repo，這裡只留每條的通過次數。

## 結果

作答者選的圖型：commitment-verbal-support 3 次都是傳遞路線，dependence-boss-wont-release 3 次都是利益交集。6 次都沒用到 §3 的退路。

| 情境 | 條件 | 通過 | 備註 |
|---|---|---|---|
| commitment-verbal-support | #1 | 3/3 | 三張都把「處長 → 資訊部」畫成點線問句，看得出缺的是誰去交辦 |
| commitment-verbal-support | #2 | 2/3 | 第 2 次寫「預算不是問題」，解決了預算 |
| commitment-verbal-support | #3 | 0/3 | 誰排工時、哪一週開工、誰簽預算，沒有一次三項都標未知或給查法；多半只問了排程由誰定 |
| commitment-verbal-support | #4 | 1/3 | 第 2 次把阿哲沒接到通知寫成「資訊部沒接到」，第 3 次寫成「處長沒交代」，都沒標推測 |
| commitment-verbal-support | #5 | 0/3 | 第一句沒有同時講卡點和第一步，例如「兩個都先不選。」「不要乾等，也別去『催』處長。」 |
| commitment-verbal-support | #6 | 3/3 |  |
| commitment-verbal-support | #7 | 2/3 | 第 3 次把「由我們直接向資訊部提出」放進給處長的主稿，沒標「你願意才加」 |
| commitment-verbal-support | #8 | 3/3 |  |
| commitment-verbal-support | #9 | 3/3 |  |
| commitment-verbal-support | 地圖 A～E | 5／5／5 |  |
| dependence-boss-wont-release | #1 | 3/3 | 三張都把「主管：不簽，月結仍是你跑」和你這邊談不成的結果並排 |
| dependence-boss-wont-release | #2 | 3/3 |  |
| dependence-boss-wont-release | #3 | 3/3 |  |
| dependence-boss-wont-release | #4 | 3/3 |  |
| dependence-boss-wont-release | #5 | 0/3 | 第一句只講卡點，第一步在下一句 |
| dependence-boss-wont-release | #6 | 3/3 |  |
| dependence-boss-wont-release | #7 | 2/3 | 第 2 次把「到職日往後排」放進給珮君的主稿，沒標「你願意才加」 |
| dependence-boss-wont-release | #8 | 1/3 | 第 1 次「這兩天」、第 3 次「先約 15 分鐘」，都是輸入沒給的時長 |
| dependence-boss-wont-release | #9 | 3/3 |  |
| dependence-boss-wont-release | #10 | 3/3 |  |
| dependence-boss-wont-release | 地圖 A～E | 4／5／5 | 第 1 次 C 判否：正文說「你沒提外部機會」，圖寫成「你：只能留原職」 |

合計：條件 commitment 7／5／5（共 17/27），dependence 8／8／8（共 24/30）；地圖 A～E 29/30。

map-check 第 8 項：commitment 三張都是 6 列，有兩張的最後一列 23、24 字。三次都是完整策略的完整面板，不受精簡圖 5 列、20 字的限制。

## 套用預先登記的判定

- commitment-verbal-support：A～E 3 次都 5/5，#1 3/3，E 沒有判否。符合「不加圖型」，**不加承諾帳**。
- dependence-boss-wont-release：只記錄。#1、E 都是 3/3，地圖沒有要寫進下一輪的問題。
- 這兩則正是當初提議新增「承諾帳」「籌碼帳」的處境，現行 v2.1 用既有的傳遞路線與利益交集就畫得出來，評審也判圖能幫使用者選第一步。

## 下一輪要改的（都在正文，這輪不修）

1. **第一句同時講卡點和第一步**：兩則 6 次全判否（#5）。同一個問題在 v2 的 quadrant、venn，以及 v2.1 的 relay #2 都出現過（T9 第 2 項，當時決定不做）。加上這兩則，10 則情境裡已有 5 則量到，值得重新考慮。
2. **順手加的時長**：dependence #8 有 2 次判否（「這兩天」「先約 15 分鐘」）。v2.1 已有「數字、時長、日期必須出自原文」，對這種隨口的時長沒擋住。
3. **把一個人的話擴大成整個部門，或推定原因**：commitment #4 有 2 次判否。
4. **主稿放進沒選的付出**：commitment-3、dependence-2 各一次。這兩種付出（由使用者向資訊部提案、延後到職）沒有逐字出現在 SKILL.md 那張清單上，最接近的是「主動提交新文件」「新期限」。
5. **commitment #3 可能偏嚴**：條件要求三項未知都標出，作答多半只問最關鍵的一項。要改條件還是改 skill，由使用者決定。
