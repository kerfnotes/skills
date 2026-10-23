# 版型：先寫判斷，再選畫面

每個版型自帶一個主張。先寫每頁 `claim`，再選能支撐它的版型；稿子撐不起主張時換版型。版型是工具箱，不必湊齊，也不必固定頁數。決策型範例見 [story.json](../examples/story.json)，說明型範例見 [story-explain.json](../examples/story-explain.json)。

決策骨架：封面 → 主管摘要 → 現況／需求 → 證據 → 診斷或方案 → 決議事項。無數字的決策稿，在封面後以帶 `focus` 的 `statement` 提出核心判斷。每張證據頁的 `claim` 都要被摘要或決議採用；無法指出支撐哪個判斷或行動的孤立頁刪去。

## 整份簡報與共通欄位

根物件有 `title`、選用的 `date`、`author`、`mode` 和依播放順序排列的 `pages`。`mode` 省略或填 `present` 是現場簡報；填 `read` 是[閱讀型簡報](#閱讀型簡報)。沒有日期就省略 `date`，封面不顯示日期。每頁填 `type`、一句 `claim` 與 `sources.source`；有內容才填該版型的選用欄位。

| 欄位 | 用法 |
| --- | --- |
| `kicker` | 頁首主題；封面作單位名稱。章節尺標按非封面頁的 `kicker` 首次出現順序去重，只在 `section` 頁顯示。 |
| `claim` | 可由內容支持的結論。長標題可用 `\n` 指定斷點；封面、章節與內容頁標題估算超過兩行會警告。不要只寫「背景」或「分析結果」。 |
| `lede` | 封面、章節以外的內容頁選填，一行小字放在標題下、內容上，交代「指標・範圍・期間・單位」。省略時不佔高度。 |
| `note` | 畫面上的補充，適用於 `cover`、`section`、`statement`、`evidence`。 |
| `visual` | 依版型放圖表或結構化內容；欄位見下表。 |
| `sources` | 每頁可見來源列：`source` 必填；已知時填 `unit`、`period`；`more` 是會上投影片的口徑、算法或缺口字串陣列。 |
| `notes` | 講者備註，可為字串或字串陣列，不在畫面顯示。 |

`note` 是畫面補充，`notes` 是講稿。選填格若稿子沒有提及，省略整格；不要填空白卡片或佔位字。論證需要或讀者會預期看到的數字，若原稿未提供，數字格或比較格用 `null` 保留位置，畫面標「未提供」並列入來源列；`0` 是有效觀察值。證據頁的 `table` 圖種也在缺值格原位標「未提供」。其他圖表的 `null` 可能留白、斷線或略去圖元，依[圖表選單](charts.md)處理並列入來源列；若缺值位置本身是論證重點，改用能在原位標示的數字、比較或表格版型。來源列建議兩行內，超出會警告而不縮字。圖表 `visual.source` 不能代替頁面的 `sources.source`。

`focus` 的值依用途而異：`statement` 用頁面層字串，逐字對應 `claim`；`list`／`process`／`flow`／`columns` 用 `visual.focus` 零起算索引。圖表通常用資料名稱，`rank`／`funnel` 也接受名稱陣列；`histogram` 用組界 `from` 數值。各圖以[圖表欄位](charts.md)為準。

## 版型與各自的主張

下表容量是畫面建議；超出會警告，應看圖後刪內容或拆頁。所有版型都接受 `notes`，所有內容頁都可填 `lede`。

| 版型 | 自帶的主張 | `visual` 與容量 |
| --- | --- | --- |
| 封面 `cover` | 這份簡報要談的問題與方向。 | 無；用 `kicker`、`claim`、`note`，日期讀根層 `date`。主標可用 `\n` 分行。 |
| 主管摘要 `summary` | 建議這樣做，關鍵數字支持它。 | `{lead, body?, items}`；左欄一行建議和至多三行理由，右欄建議 2～3 個數字格。 |
| 章節 `section` | 接下來處理這個問題。 | 無；用 `kicker`、`claim`、`note`。 |
| 一句話 `statement` | 先記住這個判斷。 | 無；選用頁面 `focus` 指定 `claim` 中的原文，找不到會警告。 |
| 證據 `evidence` | 這張圖或表支持標題判斷。 | 一張[圖表](charts.md)；選用頁面 `metric: {label?, value, unit?, digits?}` 和 `note` 作右側結論欄。 |
| 數字 `numbers` | 這幾個指標一起說明狀態。 | `items: [{label, value, unit?, ...}]`；建議 2～4 格，過長數字與高度會警告。 |
| 診斷清單 `list` | 這幾件事需要處理；原稿有優先序時標出重點。 | `items` 3～5 項；選用 `tag`／`focus`，列間細線。 |
| 無日期流程 `process` | 事情照這個順序走，現在在這一步。 | `steps` 3～6 步；`focus` 標目前步驟，超出欄寬會警告。 |
| 核心數字 `kpi` | 這一個數字最重要。 | `main` 含 1～3 個 `benchmarks`，`secondary` 0～4 個。 |
| 因果 `flow` | A 加 B 造成 C，所以做 D。 | `nodes` 2～5 個，`connectors` 連接相鄰方框；預設強調最後一框。 |
| 並列重點 `columns` | 這幾件事並列，不分先後。 | `items` 2～4 欄，選用 `focus` 強調一欄。 |
| 方案比較 `compare` | 在同一組條件下，這個方案較適合。 | `rows` 列名及 `options` 2～4 個方案；每個 `values` 與列名逐格對應。超出 2～4 個才警告。 |
| 月份時程 `steps` | 已知的工作照這段月份安排。 | `start`、`end`、`phases`；日期必須是 `YYYY-MM`，列高不足會警告。 |
| 決議事項 `close` | 下一步由誰做什麼、何時完成。 | `rows: [{task, owner?, due?}]`；列高不足會警告。 |

### 摘要、數字與核心數字

`summary.visual` 為 `{lead, body?, items}`；`lead` 必填，補充標題之外的建議或條件；`body` 選填，`items` 使用 `numbers` 的數字格結構並可加一行 `note`。右欄每個數字格都支持 `lead`，共用口徑；不同期間、分母或實績／預估基準在該格 `note` 註明。若沒有支撐建議的數字，以帶 `focus` 的 `statement` 開場。

預設設計層的 `body` 每行約 25 個中文字、最多三行約 75 字；標點與手動換行也佔容量，末行孤字需調整斷點。

`numbers.visual.items` 的每項是 `{label, value, unit?, prev?, mode?, digits?, better?, deltaSuffix?, note?}`；`note` 是數字下方的一行說明，交代口徑或比較基準。`value` 可為數字、顯示字串或 `null`；數字依 `digits` 格式化，未指定時照數值本身的小數位顯示（24.7 顯示 24.7），增減值照前後值的小數位。四格時使用設計層較小的固定數字字級，過長仍警告而不自動縮字。數字搭 `prev` 時可算增減，須明寫 `better: "higher"` 或 `"lower"`；`mode` 預設 `abs`（差額），另有 `pct`（相對百分比）、`pp`（百分點）。前期為 0 時改用差額；字串值不計算增減。

`kpi.visual` 為 `{main: {label, value, unit?, digits?, benchmarks: [{label, value, unit?, digits?}]}, secondary?: [{label, value, unit?, digits?}]}`。主數字在左，1～3 個對照逐列置於下方，右側直排 0～4 個次要指標。每個 `value` 可為數字或顯示字串，數字依該項的 `digits` 格式化；論證必要但缺值時可用 `null`，畫面標「未提供」並列入來源列。

### 診斷、無日期流程、因果與並列

`list.visual` 為 `{items: [{tag?, heading, body?, note?}], focus?}`。`items` 建議 3～5 項：左欄短標 `tag`、中欄粗體 `heading` 與一行 `body`、右欄一行小字 `note`；列間細線。`focus` 是從 0 起算的項目索引，只讓該列 `tag` 與 `heading` 用重點色。選填文字沒有內容就省略該格。

原稿給了順序或優先序時才用 `tag`／`focus`；未決事項用沒有 `tag`／`focus` 的 `list`，或用各欄同重的 `columns`。將推論的優先序與理由寫在 `notes`，畫面保留原稿已確認的內容。

`process.visual` 為 `{steps: [{label?, heading, body?}], focus?, note?}`。`steps` 建議 3～6 步，從左到右以細線串起圓點；上方小字 `label` 省略時顯示「步驟 1」等，下方放粗體 `heading` 和 `body`。`focus` 是從 0 起算的目前步驟索引，該步圓點與文字用重點色。已有月份的時程使用 `steps` 版型。原稿中的例外／分支可放 `visual.note`，顯示在整段流程下方的一行補充；推論的分支放 `notes`。

預設設計層下，三步的 `heading` 每行約 14 字、`body` 約 16 字；六步分別約 6 字、7 字。先以短標題加一至兩行說明編排，再看警告與預覽。`process`、`columns` 從標題／`lede` 下的內容起點向下排，`statement` 的大字判斷在頁面垂直置中，過高時從標題位置開始。

`flow.visual` 為 `{nodes: [{label?, heading, body?}], connectors?, focus?, note?}`。`nodes` 建議 2～5 個方框，由左到右閱讀；`connectors` 是長度比方框少一的符號陣列，每段預設「→」，可用「＋」或「＝」。`focus` 是從 0 起算的方框索引，預設最後一個，該框填滿重點色並使用設計層對應文字色。`note` 是方框下一行補充；節點選填格省略時不留佔位。

`columns.visual` 為 `{items: [{kicker?, value?, unit?, digits?, heading, body?}], focus?}`。`items` 建議 2～4 欄：每欄上緣細線、小字 `kicker`、可選大數字 `value`、粗體 `heading` 與 `body`。`value` 是數字時依 `digits` 格式化；`focus` 是從 0 起算的欄索引，省略時各欄同重。

### 方案、月份與行動

`compare.visual.rows` 是比較項目字串陣列；`options` 每項為 `{name, subtitle?, values, recommended?}`。`values` 長度等於 `rows`，文字或數字逐格對應，缺少論證必要的比較值用 `null`，該格顯示「未提供」並進來源列。`recommended: true` 的欄頭填重點色；省略時方案同重。4 個方案仍需檢查文字是否放得下。

`steps.visual` 為 `{start: "YYYY-MM", end: "YYYY-MM", phases: [{name, note?, from: "YYYY-MM", to: "YYYY-MM"}]}`。起訖月都計入長條；每階段須在整體時程內。沒有來源日期就改用 `process`。

`close.visual` 為 `{rows: [{task, owner?, due?}]}`。`due` 是顯示文字，可放來源提供的日期或相對時點，不轉成日期軸。單格未知時留空或省略該列的欄位，其他列的已知值照常保留；整欄都未知時才省略整欄。若責任歸屬是決策必需的缺口，在 `sources.more` 寫明。未決事項改用沒有 `tag`／`focus` 的 `list` 或 `columns`。

欄頭固定為「下一步／負責人／期限」（整欄省略時隱藏該欄頭）；`kicker` 寫議題，例如「試行安排」。預設每行約可放 `task` 28 字、`owner` 12 字、`due` 7 字，稀疏列最多約三行；列數增加時容量變少。負責人與期限宜短寫，單格末行孤字會警告。

表格、比較頁及收尾頁會依可用高度調整資料列，字級不變。若文字仍放不下，刪內容或拆頁。建檔成功只證明檔案能產生；字級、重疊、圖文關係與故事是否成立，仍須逐頁預覽驗收。

## 閱讀型簡報

會前先寄、讀者自己看、沒有人講解時，根層填 `"mode": "read"`。閱讀型簡報每頁放的訊息比現場簡報多：整份改用 [design/read.json](../design/read.json) 的字級、上下邊界、證據圖寬與容量。`node evals/check.mjs` 與 `node scripts/pptx.js` 讀到 `mode` 會自動切換，指令不變。

| 層級 | 字級 | 用在 |
| --- | --- | --- |
| 頁標題 | 22 pt，最多兩行 | 每頁 `claim` |
| 正文 | 11 pt | 摘要理由、清單與並列的 `body`、證據頁 `note`、收尾表、panels 的文字格 |
| 小字正文與標籤 | 10 pt | 頁首、`lede`、`takeaway`（粗體）、`points`、panels 格標題與 `note` |
| 圖表文字 | 9 pt | 軸標、資料標籤、表格 |
| 註腳與來源 | 8 pt | `footnotes`、來源列、頁碼；也是最小字級 |

上邊界 8 mm、下邊界 7 mm，左右邊界不變。來源列與頁碼在同一行。證據頁圖表縮窄為 1000 px，右欄加寬，正文每行約 26 個中文字。13.33 吋投影片印在 A4 橫式約縮為 0.88 倍，8 pt 印出約 7 pt；讀者會印出細看時，先預覽 PDF 確認可讀。字級是整份一致的設計，不是逐頁縮字；放不下仍刪內容或拆頁。

每個內容頁建議放 600 到 900 個字元的可見文字（`claim`、`kicker`、`lede`、`note`、`takeaway`、`points`、`footnotes`、`visual` 內的標籤與數值、來源列，不算換行）。這是寫作目標，驗收器不檢查；少於 600 字元時多半是該併頁，或證據頁右欄還能補理由。

### 容量

超出下表只警告，不擋建檔；高度估算超出內容區時另有警告，那是硬門檻。

| 版型 | 現場簡報 | 閱讀型 |
| --- | --- | --- |
| `summary` | 2～3 格，理由至多 3 行 | 2～6 格，理由至多 10 行 |
| `numbers` | 2～4 格，`note` 1 行 | 2～8 格，4 格以上排兩列，`note` 至多 3 行 |
| `list` | 3～5 項，`body` 1 行 | 3～8 項，`body` 至多 3 行 |
| `process` | 3～6 步 | 3～8 步 |
| `columns` | 2～4 欄 | 2～5 欄，每欄 `body` 至多 6 行，可加一列 `takeaway` |
| `compare` | 2～4 個方案 | 2～5 個方案，至多 8 列 |
| `evidence` 的 `table` | 依可用高度 | 至多 14 列 |
| `evidence` 的 `points` | 不支援 | 2～4 點，每點至多 2 行 |
| `close` | 依可用高度 | 至多 14 列 |
| `panels` | 不支援 | 恰好 2 格，每格 `note` 至多 3 行 |
| `footnotes` | 不支援 | 不限則數，8 pt 依頁寬換行，佔用內容區下方高度 |

`summary` 6 格與 `close` 14 列是標題一行、沒有 `lede` 時的上限：摘要每格只放數字與標籤；每格加 `note` 時約放 4 格。兩行標題或加 `lede` 會少一點高度，依警告刪格或拆頁。

### 新欄位

沒有講者，要說的話就要寫在頁面上。以下欄位只有閱讀型支援，現場簡報用到時驗收失敗：

- `evidence` 右欄：`takeaway` 一句結論（10 pt 粗體），`points` 2～4 點理由（10 pt，每點至多 2 行），其後接既有的 `note`（11 pt，寫怎麼讀與資料限制）。三者都沒有時建檔會警告右欄空白。重點數字 `metric` 仍在右欄最上方，但會占掉 `points` 與 `note` 的高度。
- `columns` 的 `takeaway`：頁面層一句，以一列 10 pt 粗體排在各欄下方。
- 任一頁的 `footnotes`：字串陣列，自動編號為「(1)」「(2)」，以 8 pt 排在來源列上方。正文自己寫半形「(1)」標記，不用上標。驗收器掃數字時會剔除不超過註腳數的「(N)」，其餘數字（含 `takeaway`、`points`、`footnotes` 裡的數字）都要有原稿依據。
- `panels` 版型：見下節。

```json
{
  "type": "evidence",
  "claim": "甲區 12 件，多於乙區的 8 件",
  "takeaway": "甲區是目前最主要的案件來源(1)。",
  "points": ["甲區 12 件，乙區 8 件。", "乙區仍在成長，差距可能縮小。"],
  "note": "只計已結案件；未結案件不列入。",
  "footnotes": ["案件以受理地區歸類。"],
  "visual": { "kind": "rank", "rows": [{ "label": "甲區", "value": 12 }, { "label": "乙區", "value": 8 }] },
  "sources": { "source": "虛構測試文字稿" }
}
```

```json
{
  "type": "columns",
  "claim": "三項工作並行，五月底前完成",
  "visual": { "items": [{ "heading": "核定費率", "body": "營運科負責。" }, { "heading": "增補條款", "body": "法務室負責。" }, { "heading": "擴容評估", "body": "規劃科負責。" }] },
  "takeaway": "三項都要在下次會議前完成，才能如期全區上線。",
  "sources": { "source": "虛構測試文字稿" }
}
```

### panels

`panels` 一頁並排兩格，各放一張圖、一張表、一份清單或一段文字。`visual` 為 `{items: [{title, visual, note?}, {title, visual, note?}], split?}`：`items` 恰好兩格；格標題 10 pt；格內 `visual` 是圖表或表格的 `{kind, …}`（同[圖表欄位](charts.md)，表格用 `table` 圖種）、清單 `{items: [{heading, body?}]}` 或一段文字字串（正文 11 pt）；`note` 10 pt、至多 3 行，超出警告。預設兩格等寬，`split: [3, 2]` 依比例分寬。格內數字與註一樣要能在原稿找到。

```json
{
  "type": "panels",
  "claim": "河東與河西的騎乘量都成長，河東增量最大",
  "visual": {
    "split": [3, 2],
    "items": [
      { "title": "各區 2025 年騎乘量", "visual": { "kind": "rank", "unit": "萬次", "rows": [{ "label": "河東區", "value": 398 }, { "label": "河西區", "value": 301 }] }, "note": "河東區 398 萬次最高。" },
      { "title": "主要風險", "visual": { "items": [{ "heading": "司機招募不易", "body": "尖峰補車延遲。" }] } }
    ]
  },
  "sources": { "source": "河港市交通局營運報表" }
}
```

### 填滿與頁數

- 數字格、流程、並列、時程、一句話頁、清單、方案比較、收尾待辦、主管摘要，以及兩格都是文字或清單的 `panels`，內容填滿低於內容區 70% 時驗收器會警告（清單、比較、收尾與摘要的列會拉伸填滿，填滿率以內容不拉伸時的自然高度估算）：加 `takeaway` 或 `points`，或併入相鄰頁；不湊字、不放大字級。
- `lede` 交代指標、範圍、期間與單位；清單與流程的 `body` 寫原因或做法，不只寫名詞。
- 現場簡報用來鋪陳的 `statement`、`section` 頁，改把判斷併入相鄰內容頁的 `claim`、`takeaway` 或 `note`，頁數通常比現場版少。
- `notes` 不會被讀者看到，只放計算行與資料限制，不必寫講稿。

範例見 [story-read.json](../examples/story-read.json)：封面加五個內容頁，用到 summary、evidence 的 `takeaway`／`points`、`panels`、compare 與 columns 的 `takeaway`；四頁有 `footnotes`，三頁用兩行標題；和現場版 [story.json](../examples/story.json) 用同一份原稿。

## 預覽與交付

有 PowerPoint 的 Mac 使用 PowerPoint；沒有 PowerPoint 但有 LibreOffice（`soffice`）時使用 LibreOffice。執行 `node scripts/preview.js out/deck.pptx out/preview`，需要 `pdftoppm`、`ffmpeg`，輸出 `page-N.png`、`sheet.png`（整份概覽）與 `deck.pdf`。LibreOffice 可能替換字型，正式字型仍需在 PowerPoint 複查。兩者都沒有時交代安裝需求；[SVG／PNG 圖表預覽](charts.md#共通欄位與輸出)可驗圖表，整頁版面仍標未驗。

現場簡報每張內容頁的 `notes` 寫 1～3 句要說的話與資料限制，計算行另列；閱讀型簡報把這些話寫進頁面。預覽逐頁核對主張、強調項目、口徑、空間分配與閱讀順序，找出末行單一中文字、過短末行或不均勻斷行。0 項容量警告只表示估算未偵測到溢出，換行品質需看圖。交付記錄最弱頁修改前後及理由；列出實際輸出的原生圖與 SVG，將「實際在 PowerPoint 改一個原生圖數值」標為完成或未驗。
