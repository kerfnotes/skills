# Power Map 地圖驗收檢查

`map-check.js` 在預覽頁面裡跑，檢查一張地圖 HTML 有沒有踩到七條格式規則，另外列出列數與每列字數。它放在 repo 根目錄的 `evals/`，不在 skill 資料夾裡，安裝 skill 時不會被帶走。

## 檢查什麼

1. 視窗寬度下沒有水平溢出：整頁不比視窗寬，任何元素也不超出視窗左右緣。
2. 文字沒被截斷：`overflow` 裁切且內容比框大的元素；SVG 裡超出畫布的 `<text>`。
3. 標了 `data-focal` 的強調元素最多 2 個。
4. 每個 `<svg>` 有 `role="img"`，`aria-labelledby` 指向它自己裡面有字的 `<title>` 和 `<desc>`，而且 `<title>` 是第一個子元素。
5. 沒有外部資源：`src`、`srcset`、`href`、`data`、`poster` 不指向 `http(s)://` 或 `//`；`<style>` 和 `style` 屬性裡沒有網址或 `@import`。`<a>` 連結不算。
6. `html`、`body` 和 body 底下的最外層容器沒有設背景色或背景圖。
7. 每個證據標籤 `.tag` 都有文字。
8. 列數與每列字數，只報不判（印成 `INFO 8`，不算進總結）：HTML 的 `.qa-r`、`.hop`、`.ring` 裡的人各算一列，字數不含空白、標點、證據標籤和圈名；超過 20 字的列另外點名。SVG 不分列，只報方框、點的個數和文字總數。精簡圖拿來對 [board.md](../../skills/kerf-power-map/references/board.md) §1「最多 5 列，每列 20 字內」；完整面板不受這條限制。

## 在 html_preview 怎麼用

1. 用 ToolSearch 載入 `mcp__t3-code__html_preview`。載入不到就停下回報，不要改用其他瀏覽器。
2. 把地圖 HTML 複製一份，在 `</body>` 前面貼上 `<script>`、`map-check.js` 全文、`</script>`。
3. 呼叫 html_preview，`html` 放上一步的整份文件，`width` 設 375。版型零件和範例另外用 728 再跑一次。
4. 看回傳的 `consoleMessages`：第 1～7 項每項一行 `PASS n …` 或 `FAIL n …：原因`，第 8 項一行 `INFO 8 …`，最後一行是第 1～7 項的總結，例如 `map-check PASS：7/7 通過，視窗寬 375px`。
5. 一定要看截圖。腳本不檢查元素重疊、箭頭標籤壓線、配色對比，也不判斷圖畫得對不對。
6. 交付給使用者的版本不放這段 script。

## 樣本與預期結果

| 樣本 | 預期 | 實測（375 寬） |
|---|---|---|
| `fixtures/violations.html` | 七項全部 FAIL | 7 項全 FAIL，每項都指出違規元素；INFO 8 印出 SVG 文字 16 字 |
| `fixtures/pass.html` | 七項全部 PASS | 7/7 PASS；INFO 8 印出 SVG 文字 15 字 |
| 審查資料夾的 `first-map.html`（含真實名稱，不放進 repo） | 找出格式違規 | 7/7 PASS：這張圖的問題是信件時間軸、跟正文重複這類內容問題，格式檢查抓不到，要靠情境評測 |

改了 `map-check.js` 之後，三份樣本都要重跑，結果要跟上表一致。2026-10-22 加第 8 項時重跑了前兩份和 `references/examples/` 的 6 個範例（375、728 寬都是 7/7）；第三份不在 repo，沒有重跑。

## 已知限制

- html_preview 會注入 `<style id="t3-theme">`，並在裡面替 `html` 設背景。第 5、6 項靠這個 id 排除它；換預覽工具時要改 `THEME_ID`。
- 第 6 項讀作者寫的樣式規則和 `style` 屬性，不看計算後的顏色。用腳本動態加上的背景抓不到。
- 第 1 項會把超出視窗的 SVG 文字也算進去，所以同一個問題可能同時出現在第 1、2 項。
