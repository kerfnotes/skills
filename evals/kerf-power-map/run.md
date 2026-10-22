# 情境回放評測：怎麼跑

用一組固定情境重跑 kerf-power-map，只看使用者拿到的東西（回覆正文與地圖），不看模型怎麼推理。改版前後各跑一次，比較每條通過條件的差異。

## 情境

| 檔案 | 卡點 | 圖型 | 交付 |
|---|---|---|---|
| [concern-external-draft.md](scenarios/concern-external-draft.md) | 對外說明疑慮，同事草稿只缺一句因果 | 疑慮對照 | 短答 |
| [relay-credit-filtered.md](scenarios/relay-credit-filtered.md) | 功勞被主管轉述時過濾掉 | 傳遞路線 | 不限 |
| [decision-circle-cross-dept.md](scenarios/decision-circle-cross-dept.md) | 跨部門提案不知道誰能批 | 決策圈 | 不限 |
| [branch-user-knows-fact.md](scenarios/branch-user-knows-fact.md) | 關鍵事實只有使用者知道 | 分支 | 判讀輪 |
| [quadrant-store-stances.md](scenarios/quadrant-store-stances.md) | 多位同事立場不一 | 立場四象限 | 不限 |
| [venn-workload-trade.md](scenarios/venn-workload-trade.md) | 代理工作量與交換條件 | 利益交集 | 不限 |
| [followup-how-to-reply.md](scenarios/followup-how-to-reply.md) | 策略給過後再問「那怎麼回」 | 疑慮對照（精簡） | 短答 |
| [no-long-form.md](scenarios/no-long-form.md) | 明說「不要長篇」 | 傳遞路線（精簡） | 短答 |

8 則、6 種圖型，必有兩則圖型重疊：最後兩則測交付分流，處境和前六則都不同，圖型借用疑慮對照與傳遞路線。

每則固定四節：`## 使用者輸入`、`## 預期卡點與圖型`、`## 通過條件`、`## 舊版預期`。條件末尾的〔US n〕是 spec User Stories 編號；〔要點二〕〔要點三〕指 spec Implementation Decisions 的三要點（不替使用者承諾或背書、今天就能提的請求不設門檻）。

## 三個角色

**作答者**（子代理，每次新開）只拿兩樣東西：skill 目錄路徑，和情境的 `## 使用者輸入` 一節。看不到其他三節，否則評測漏題。多輪情境把各輪依序放進對話歷史，只答最後一輪。提示詞：

```
你是使用者的助理，已安裝 kerf-power-map skill，位置：<skill 目錄>。依該目錄的 SKILL.md 與它引用的檔案回答下面的使用者訊息。
- 只讀 skill 目錄內的檔案；不要讀 evals/、git 歷史或其他資料夾。
- 回覆正文存成 <輸出目錄>/<情境>-<第幾次>.md。
- 回覆含地圖時，把完整 HTML 存成 <輸出目錄>/<情境>-<第幾次>.html（不含檢查腳本）。
- 只寫給使用者看的內容，不寫製作過程。

使用者訊息：
<貼上「使用者輸入」一節全文>
```

**地圖檢查**（跑評測的人或主代理）：用 `html_preview` 以 375 寬開地圖 HTML，把 `evals/kerf-power-map/map-check.js` 以 inline script 附在 HTML 末端，存下 console 的 PASS／FAIL 與 INFO 8（列數與每列字數）輸出，以及 375 截圖。腳本細節與 html_preview 用法見同資料夾 `README.md`。沒有 HTML 就記「無地圖」。

**評審**（子代理，沒參與改版也沒參與作答）拿到：使用者輸入、回覆正文、地圖 HTML、375 截圖、腳本輸出、該則通過條件。提示詞：

```
你是評審，沒有參與這個 skill 的改版，也沒有參與作答。依通過條件逐條判「是／否」，不給部分分數，拿不準就判否。
每條一行：#編號｜是／否｜證據（逐字摘錄回覆或 HTML 的一句；判否時寫缺了什麼）。
字數以字元計、不含空白與標點，接近門檻時實際數。
最後判「共通地圖檢查」A～E，格式相同。
```

## 共通地圖檢查（每則都判，不計入各則條件數）

- A. `map-check.js` 在 375 寬全部 PASS。
- B. 375 截圖不捲動就看得到這局卡在哪與第一步，沒有文字或線條重疊。
- C. 正文說未知或推測的事，圖裡沒有寫成定論。
- D. 換案測試：評審指出圖中至少一格（人名以外的數字、原話或事件），換成別的案子就不成立。
- E. 圖沒有把正文或照念稿逐句搬進格子；圖寫的是正文一眼看不出的依賴、取捨、分歧或缺口。

沒有地圖時 A～E 全判否。

## 基準與重跑

- 舊版：commit `3511cc9`（power-map-v2 起點）。另開目錄給作答者，避免讀到新版：`git worktree add <暫存目錄>/pm-baseline 3511cc9`，skill 目錄指 `<暫存目錄>/pm-baseline/skills/kerf-power-map`。
- 新版：改版合入 power-map-v2 後的 HEAD。
- 每則每版至少跑 3 次，記每條條件的通過次數。各則的「舊版預期」是依舊版規則推定的紅燈，實跑結果和它不一致時，以實跑為準並在結果表註明。
- 結果寫成一張表：情境｜條件編號｜舊版通過次數｜新版通過次數｜備註。跑完移除暫存 worktree。
