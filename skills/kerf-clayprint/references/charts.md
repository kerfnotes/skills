# 圖表選單：先決定要回答的問題

目前有 23 種圖表與 1 種表格。把下列 spec 放進證據頁的 `visual`；版面結構見 [layouts.md](layouts.md)。這些是輸入欄位，`core.prepare()` 產生的 `axis`、`missing`、`warnings`、`text` 等結果不用自己填。範例數字都是虛構示意；製作簡報時以文字稿為準。

## 共通欄位與輸出

- `kind`：下列圖種名稱；各圖的資料欄位必填，其他欄位除特別註明外可省略。
- `digits`：顯示小數位數，預設 `0`；原始資料仍保留精度。
- `better`：`higher` 或 `lower`，預設 `higher`；控制支援增減的圖表之增減標籤色，不改動正負號。
- `unit`、`period`、`source`：獨立 SVG 的來源列。放進簡報後，每頁來源列改讀頁面的 `sources`，請另填 `sources.source`、`sources.unit`、`sources.period`。
- 數值用 JSON 數字，缺值用 `null`，0 照常保留。缺值會自動列入證據頁來源列；表格會在原格寫「未提供」，其他圖種依圖種留白、斷線或略去。若缺值本身是論證重點，改用能在原格標示的數字、比較或表格版型。文字稿沒有可畫數字時，選非圖表版型。
- 原生：`rank`、`line`、`slope`、`share`、`scatter`、`grouped`、`sharetrend`、`ordered` 是 PowerPoint 圖表，`table` 是 PowerPoint 表格。其餘為 SVG，簡報內附 PNG 後備。原生圖可加 `native: false` 改用 SVG；極小非零值若會顯示成 0，也會自動改 SVG 並警告。
- 一張圖只有一個數值軸；`combo` 是上下對齊的兩張圖，各有自己的數值軸與單位，沒有雙軸圖。
- 同類別整份簡報維持同色。`share`、`sharetrend`、`waffle`、`mekko` 超過可用類別色數的類別會合併為「其他」；無 `focus` 的多系列 `line` 超出可用色數者改用灰色，但不合併資料。可用色數取 `categoryRules.maxCategorical` 與 `categorical` 長度的較小值；預設為四色。看警告與圖面再決定是否調整。

獨立圖表預覽指令（從 skill 根目錄執行）：

```sh
mkdir -p out
node scripts/svg.js examples/rank.json out/rank.svg
node scripts/png.js out/rank.svg out/rank.png
```

要預覽自己的圖，另存該頁 `visual` 為圖表 JSON，再把指令的輸入換成該檔。SVG 不包含整張投影片的排版，也不能代表 PowerPoint 原生圖已驗收。原生圖的編輯限制見 [設計差異](../docs/design-diff.md)。

## 哪個最多、差距多大？

### 排名長條 `rank`

用於同一指標的類別高低比較；預設由大到小排序，適合找出首要對象。

- 欄位：`rows: [{label, value}]`；選用 `focus`（一個類別名稱或名稱陣列，如 `["甲", "乙"]`）、`sort: false`（保留輸入順序）。主張點名多個渠道時一起強調。`value` 可為數字或 `null`；缺值的整列不畫，列名只列入來源缺值說明，SVG 與原生圖相同。
- 輸出：原生圖表。
- 常見錯誤：拿不同單位的數字排名；`focus` 拼字與 `label` 不一致；把缺值補成 0。負值可畫，長條仍以 0 為基準。
- 最小範例：`{"kind":"rank","rows":[{"label":"甲","value":12},{"label":"乙","value":8}],"focus":"甲"}`。完整檔：[examples/rank.json](../examples/rank.json)。

### 啞鈴 `dumbbell`

用於逐項比較前後差距，尤其是等待時間、成本等越低越好的指標。

- 欄位：`periods: [舊期名稱, 新期名稱]`（恰好兩個）、`rows: [{label, values: [舊值, 新值]}]`；選用 `xLabel`（省略時用 `unit`）、`better`、`digits`。值可為 `null`；缺一端時保留列名與有效端點，不畫連線或差額，兩端皆缺值則略去整列。
- 輸出：SVG。
- 常見錯誤：把新舊順序倒過來；下降代表改善卻沿用 `better: "higher"`；把百分比的百分點差誤寫成成長率。此圖的差額是新值減舊值，沒有 `mode` 欄位。
- 最小範例：`{"kind":"dumbbell","periods":["調整前","調整後"],"better":"lower","rows":[{"label":"甲","values":[12,8]}]}`。完整檔：[examples/dumbbell.json](../examples/dumbbell.json)。

### 分組長條 `grouped`

用於比較各項目在不同期間或情境的大小；每組並排，適合看同一項目的差距。

- 欄位：`x: [項目, ...]`、`series: [{name, values: [...]}]`（2～4 個系列，每組數值長度等於 `x`）；選用 `seriesRole: "ordered" | "categorical"`，預設 `ordered`。有先後的期間用 ordered 深淺，互斥情境用 categorical 類別色。缺值用 `null`，0 是實測值。
- 輸出：原生群組長條；可設 `native: false` 用 SVG。
- 常見錯誤：將不同單位放在同一數值軸；把情境當成先後期間；把缺值補 0。系列超過四個時應分頁或換圖。
- 最小範例：`{"kind":"grouped","x":["甲","乙"],"series":[{"name":"前期","values":[8,10]},{"name":"本期","values":[12,9]}]}`。完整檔：[examples/grouped.json](../examples/grouped.json)。

### 實際對目標 `bullet`

用於逐項查看實際值離目標多遠；區間底可交代差、可、好三段標準。

- 欄位：`rows: [{label, value, target, ranges?: [差上限, 可上限, 好上限]}]`；選用 `better`（`higher` 或 `lower`）。每列畫實際長條、目標刻度和差距；`ranges` 是遞增的數值界線，以灰階呈現。
- 輸出：SVG。
- 常見錯誤：把目標當成實績；不同列使用不同單位；`better: "lower"` 的指標仍以高於目標稱為改善。缺值應用 `null` 並核對來源列，0 不代表缺資料。
- 最小範例：`{"kind":"bullet","rows":[{"label":"甲","value":92,"target":100,"ranges":[60,85,120]}]}`。完整檔：[examples/bullet.json](../examples/bullet.json)。

## 隨時間怎麼變、各組是否走同一方向？

### 折線 `line`

用於連續、等距時間點的趨勢；先說明轉折或持續變化，再選一條重點線。

- 欄位：`x: [標籤, ...]`（至少兩點）、`series: [{name, values: [...]}]`；選用 `focus`（系列名稱）。每條 `values` 長度須等於 `x`，缺值用 `null`；保留該類別位置、缺點處斷線，不補成 0 或跨點連線，SVG 與原生圖相同。整條皆缺值時不畫線或線尾標籤；來源列以「系列名／類別」列明缺口。
- 輸出：原生圖表。
- 常見錯誤：把不等距日期當等距點；缺值連成完整趨勢；新增資料欄後以為末點標籤會自動移位。資料增刪或重點位置改變時，重產簡報。
- 最小範例：`{"kind":"line","x":["上期","本期"],"series":[{"name":"甲","values":[8,12]}]}`。完整檔：[examples/line.json](../examples/line.json)。

### 小倍數折線 `multiples`

用於多個對象各自的走勢比較；所有小圖共用縱軸，避免各自放大造成錯覺。

- 欄位：`x`、`series` 與 `line` 相同；各格都使用重點色，`focus` 不生效。`null` 保留類別位置並斷線；整條皆缺值仍保留該小圖的格位、系列名與座標格線，不畫資料線或末值。
- 輸出：SVG。
- 常見錯誤：各系列時間點不同；格數過多。超過六格會警告，應看圖決定分頁或精簡。
- 最小範例：`{"kind":"multiples","x":["上期","本期"],"series":[{"name":"甲","values":[8,12]},{"name":"乙","values":[10,9]}]}`。完整檔：[examples/multiples.json](../examples/multiples.json)。

### 金額加比率 `combo`

用於同時追蹤規模與比率，例如營收與年增率；上下兩張圖共用橫軸，上方長條、下方折線或點，各自只有一個數值軸。

- 欄位：`x: [期間, ...]`、`amounts: [金額, ...]`、`rates: [比率, ...]`，兩組長度都等於 `x`；選用 `amountUnit`、`rateUnit`，並於來源列交代兩種單位。缺值用 `null`，不以 0 代替。
- 輸出：SVG；上下兩張圖在原生 PowerPoint 中不易保持對齊，因此沒有原生版。
- 常見錯誤：把兩種尺度硬疊在一張雙軸圖；比率的 0.08 與 8% 混用；把金額缺值當成零。比率輸入與 `rateUnit` 必須一致。
- 最小範例：`{"kind":"combo","x":["上期","本期"],"amounts":[20,24],"rates":[4,8],"amountUnit":"百萬元","rateUnit":"%"}`。完整檔：[examples/combo.json](../examples/combo.json)。

### 斜率圖 `slope`

用於恰好兩期的變化方向與相對位置；中間過程不在這張圖的主張範圍。

- 欄位：`periods: [舊期名稱, 新期名稱]`（恰好兩個）、`rows: [{label, values: [舊值, 新值]}]`；選用 `digits`、`better`。值可為 `null`；缺一端只畫有效端點與數值、不連線，兩期皆缺值則略去整列，SVG 與原生圖相同。列名標在前期端點；前期缺值時，圖內不顯示列名，可由來源缺值說明核對。SVG 差額也僅在兩端皆有值時顯示。
- 輸出：原生圖表；原生版本標兩端值，省略 SVG 版本的差額文字。
- 常見錯誤：用兩端數字推論中間穩定成長；項目太多導致交叉與標籤重疊；把 `periods` 寫成共通欄位 `period`。
- 最小範例：`{"kind":"slope","periods":["上期","本期"],"rows":[{"label":"甲","values":[8,12]},{"label":"乙","values":[10,9]}]}`。完整檔：[examples/slope.json](../examples/slope.json)。

## 整體由什麼組成、增減從哪裡來？

### 百分比堆疊長條 `share`

用於比較各組的組成比例。輸入可用人數、件數或已算出的百分數，每列都會按自己的總和換算比例。

- 欄位：`categories: [類別名稱, ...]`、`rows: [{label, values: [...]}]`；每列長度與 `categories` 相同，數字非負，允許 `null`。任一類別缺值就略去整列，避免把剩餘類別誤算成完整的 100%；SVG 與原生圖相同。
- 輸出：原生圖表；原生「其他」為灰色實底，SVG 為斜線。
- 常見錯誤：用比例長條推論總量；某類缺值時仍把其餘類當成 100%。有缺值的整列會略去並列明來源缺口；全 0 的列留空並警告。類別超過設計層的可用色數會合併，不能靠新增顏色保留所有類別。
- 最小範例：`{"kind":"share","categories":["甲","乙"],"rows":[{"label":"本期","values":[30,70]}]}`。完整檔：[examples/share.json](../examples/share.json)。

### 瀑布 `bridge`

用於從期初到期末的加減拆解，解釋總數為何改變。

- 欄位：`steps: [{label, value, total?, estimate?}]`（至少兩步）；`total: true` 表示總額並重設累計，其餘是帶正負號的增減；`estimate: true` 用斜線標預估。選用 `better`、`digits`。`value: null` 會略去整個步驟及標籤，保留其餘步驟計算，但警告後續累計可能不對。
- 輸出：SVG。
- 常見錯誤：把總額當差額；把支出減少誤寫成負貢獻；期末數字與累計不合卻忽略原因。缺值會跳過該步並警告後續累計可能不對，需在來源列說明。`estimate` 只標示預估，數字仍須有來源。
- 最小範例：`{"kind":"bridge","steps":[{"label":"期初","value":10,"total":true},{"label":"增加","value":3},{"label":"期末","value":13,"total":true}]}`。完整檔：[examples/bridge.json](../examples/bridge.json)。

### 占比隨期間變化 `sharetrend`

用於查看固定類別在各期的組成變化；輸入原始件數，程式逐期換算成 100% 堆疊直條。

- 欄位：`categories: [類別, ...]`、`rows: [{label: 期別, values: [原始值, ...]}]`；每期數值長度等於類別數，非負且可為 `null`。任一類別缺值時略去整期，避免誤算 100%；超過可用類別色數會併成「其他」。
- 輸出：原生圖表；原始值留在活頁簿，比例由活頁簿公式計算。可設 `native: false` 用 SVG。
- 常見錯誤：將已算出的比例當作規模解讀；不同期間類別定義改變；缺值時只加總其餘類別；把原始值改成百分比後仍期待顯示總量。
- 最小範例：`{"kind":"sharetrend","categories":["線上","門市"],"rows":[{"label":"前期","values":[30,70]},{"label":"本期","values":[45,55]}]}`。完整檔：[examples/sharetrend.json](../examples/sharetrend.json)。

### 百格圖 `waffle`

用於單一整體由哪些互斥部分組成，特別適合讓讀者感受大約幾成。

- 欄位：`categories: [類別, ...]`、`values: [原始值, ...]`，順序與長度一致；有效值非負。程式用最大餘數法把占比分配成 10×10 共 100 格，類別與百分比直接標示；超過可用類別色數併成「其他」。
- 輸出：SVG。
- 常見錯誤：把可重複選取的答案當互斥組成；把 1 格視為精確的 1% 原始資料；0 或極小占比被整數格隱去後未看直接標示。缺值不要補 0，應先核對來源。
- 最小範例：`{"kind":"waffle","categories":["甲","乙"],"values":[30,70]}`。完整檔：[examples/waffle.json](../examples/waffle.json)。

### Marimekko `mekko`

用於同時比較群體總規模與內部組成；欄寬表示各群總量占全體的比例，欄內色塊表示該群組成。

- 欄位：`categories: [類別, ...]`、`rows: [{label: 群體, values: [原始值, ...]}]`；每列長度與 `categories` 相同，數值非負。直接標各群總量與夠寬色塊的段內百分比；窄段省略段內數字並在附註交代。類別超限時併入「其他」。
- 輸出：SVG。
- 常見錯誤：誤以為各欄等寬；只看色塊高度而忽略總量；把缺值群體算成完整占比。缺值應以 `null` 表示並查來源列。
- 最小範例：`{"kind":"mekko","categories":["甲","乙"],"rows":[{"label":"北區","values":[30,10]},{"label":"南區","values":[10,20]}]}`。完整檔：[examples/mekko.json](../examples/mekko.json)。

### 原因集中度 `pareto`

用於檢查少數原因是否占大多數；長條按件數由大到小，累積占比寫在各長條上方。

- 欄位：`rows: [{label, value}]`；選用 `threshold`（大於 0 且不超過 1，預設 `0.8`）。累積跨過門檻的位置畫垂直參考線；到達門檻的原因用 focus，其餘用 gray。全圖只有件數一個數值軸。
- 輸出：SVG；上方累積標註與門檻線不以原生圖簡化。
- 常見錯誤：將累積百分比當第二數值軸；未依件數排序就套用門檻；把負值當原因件數。缺值用 `null`，不等於 0。
- 最小範例：`{"kind":"pareto","rows":[{"label":"甲","value":40},{"label":"乙","value":25},{"label":"丙","value":15}],"threshold":0.8}`。完整檔：[examples/pareto.json](../examples/pareto.json)。

## 資料分布如何、集中或分散在哪裡？

### 直方圖 `histogram`

用於已分組的數值分布；適合回答大多落在哪個區間。

- 欄位：`bins: [{from, to, value}]`；`from` 為數字，`to` 為數字或 `null`（最後一組無上限），`value` 為數字或 `null`。`value: null` 保留該組位置與組界刻度，不畫長條或值標籤；`to: null` 是無上限，並非缺值。選用 `focus`（目標組的 `from` 數字，預設選最高組）、`suffix`（值標籤尾碼）、`xLabel`、`refs: [{x, label}]`。
- 輸出：SVG。
- 常見錯誤：把原始觀測陣列直接當 `bins`；把區間當字串；組界沒有接上；以不同寬度的組比較頻數。現有畫法每組等寬，應使用等距分組，無上限的末組要在來源列說明。
- 最小範例：`{"kind":"histogram","bins":[{"from":0,"to":5,"value":8},{"from":5,"to":10,"value":12}]}`。完整檔：[examples/histogram.json](../examples/histogram.json)。

### 點狀分布 `strip`

用於比較各組原始觀測與中位數，保留組內差異。

- 欄位：`groups: [{label, values: [...]}]`；選用 `focus`（組名）、`digits`。值可為 `null`；缺值點不畫，中位數只用有效數值計算，整組皆缺值則連組名一起略去。來源列記錄各組缺值筆數。
- 輸出：SVG。
- 常見錯誤：輸入平均值卻聲稱展示個別觀測；用樣本數差異很大的組做未交代的比較。重複值的點會重疊，不能靠可見點數直接數樣本。
- 最小範例：`{"kind":"strip","groups":[{"label":"甲","values":[3,5,8]},{"label":"乙","values":[4,6,9]}]}`。完整檔：[examples/strip.json](../examples/strip.json)。

### 箱型圖 `box`

用於比較各群典型值、離散範圍與離群值；逐筆資料可看形狀，需要精確個別點時用 `strip`。

- 欄位：`groups: [{label, values: [逐筆觀察值, ...]}]`，或 `groups: [{label, summary: [最小值, 第一四分位, 中位數, 第三四分位, 最大值], outliers?: [離群值, ...]}]`。逐筆資料可含 `null`；少於五筆有效觀察會警告。
- 算法：排序後取中位數；第一與第三四分位採 Tukey 半樣本中位數，奇數筆時先排除整體中位數。鬚伸到 `Q1 − 1.5×IQR` 與 `Q3 + 1.5×IQR` 範圍內最遠的實測值，其餘畫離群點。直接輸入五數摘要時，提供的最小與最大值作為鬚，額外離群值由 `outliers` 給出。
- 輸出：SVG。
- 常見錯誤：不同四分位算法混用；把離群值從原始資料刪掉；樣本太少卻宣稱分布穩定。0 是觀察值，缺值要標成 `null`。
- 最小範例：`{"kind":"box","groups":[{"label":"甲","values":[4,6,7,8,9,11,20]}]}`。完整檔：[examples/box.json](../examples/box.json)。

### 等級分布 `ordered`

用於有自然順序的等級或區間，例如滿意度；保留輸入順序，不按件數重排。

- 欄位：`rows: [{label, value}]`；選用 `focus`（等級名稱）。顏色使用 ordered 深淺，`focus` 可標出特定等級；值可為 `null`，0 保留為觀察值。
- 輸出：原生長條；可設 `native: false` 用 SVG。
- 常見錯誤：按件數排序，破壞等級意義；把名目分類誤當有序等級；將缺值補成 0。
- 最小範例：`{"kind":"ordered","rows":[{"label":"低","value":8},{"label":"中","value":12},{"label":"高","value":10}],"focus":"中"}`。完整檔：[examples/ordered.json](../examples/ordered.json)。

### 熱度格 `heat`

用於兩個分類維度的強弱分布，例如時段與區域；找集中處或空白處。

- 欄位：`rowLabels`、`colLabels`、`values`（列數 × 欄數的長方形陣列）；選用 `legendUnit`、`digits`。有效值須非負，缺值用 `null`；該格保留空白，不畫色塊或數字，列名與欄名仍保留，整列皆缺值也不刪列。
- 輸出：SVG。
- 常見錯誤：列欄轉置；填負值；將空值塗成最低階。色階從 0 到最大值等寬分箱，階數取 `heatmap.steps` 與 `ordered` 長度的較小值（預設五階），不能把它解讀為分位數或跨圖固定門檻。
- 最小範例：`{"kind":"heat","rowLabels":["甲","乙"],"colLabels":["早","晚"],"values":[[2,5],[0,null]]}`。完整檔：[examples/heat.json](../examples/heat.json)。

## 哪個假設最影響結果？

### 敏感度龍捲風 `tornado`

用於比較各項假設的低、高情境對同一結果的影響；依影響範圍由大到小排列。

- 欄位：`baseline: 基準結果`、`rows: [{label, low, high}]`；選用 `better: "higher" | "lower"`，預設 `higher`。每列以基準中線為參照，向兩側畫低、高情境結果，顏色依好壞職務。
- 輸出：SVG。
- 常見錯誤：把 `low`、`high` 當成假設本身的數值，而非假設改變後的**結果**；不固定其他假設；低與高使用不同結果單位。缺值用 `null`，不要把未試算情境當作 0。
- 最小範例：`{"kind":"tornado","baseline":100,"rows":[{"label":"需求量","low":80,"high":130},{"label":"售價","low":90,"high":120}],"better":"higher"}`。完整檔：[examples/tornado.json](../examples/tornado.json)。

## 兩個指標有何關係、該先做哪一項？

### 散佈 `scatter`

用於每個對象同時有兩個數值的關係與異常點；相關性本身不表示因果。

- 欄位：`points: [{label, x, y}]`；選用 `focus`（點名）、`xLabel`、`yLabel`、`suffix`（縱軸刻度尾碼）、`refs: [{x?, y?, label}]`。座標可為 `null`，缺任一軸的點及其標籤都略去，SVG 與原生圖相同；每條參考線選一個軸。
- 輸出：原生圖表；`refs` 在原生版省略並警告，需要參考線時設 `native: false`。SVG 顯示 `xLabel` 與縱軸數值，沒有另畫 `yLabel` 標題，可把縱軸意義放入來源單位。
- 常見錯誤：憑印象補座標；把兩個不同族群混在一起推論關係；以為 PowerPoint 的點名會跟著活頁簿改名。點名標籤要重產或手動改。
- 最小範例：`{"kind":"scatter","points":[{"label":"甲","x":3,"y":8},{"label":"乙","x":7,"y":4}],"xLabel":"工時","yLabel":"件數"}`。完整檔：[examples/scatter.json](../examples/scatter.json)。

### 2×2 矩陣 `matrix`

用於已有兩軸評估值與分類門檻的優先順序；質性提案若沒有數值評估，改用 `compare`。

- 欄位：`points: [{label, x, y}]`；選用 `xLabel`、`yLabel`、`domain: [最小值, 最大值]`（同時套用兩軸）、`split: {x, y}`（省略時各取軸範圍中點）、`quadrants: {topLeft, topRight, bottomLeft, bottomRight}`（象限文字）、`priority`（上述四個象限鍵之一）。座標可為 `null`，缺任一軸的點及其標籤都略去，不參與象限判定。
- 輸出：SVG。
- 常見錯誤：為了排出象限而發明分數；以為可以分別指定 `xDomain` 與 `yDomain`；點在分割線上時任意改原始數字。應核對來源門檻並說明歸類，警告不要求硬改資料。
- 最小範例：`{"kind":"matrix","domain":[0,10],"split":{"x":5,"y":5},"priority":"topLeft","points":[{"label":"甲","x":2,"y":8},{"label":"乙","x":8,"y":3}]}`。完整檔：[examples/matrix.json](../examples/matrix.json)。

## 流程在哪一步流失？

### 漏斗 `funnel`

用於同一批對象逐階段留下的數量，呈現主要流失點。只有步驟名稱、沒有數量的流程應改用非圖表版型。

- 欄位：`steps: [{label, value}]`（至少兩步）；選用 `focus`（一個步驟名稱或名稱陣列）、`loss: true`（另列相對上一步的流失數，如「−600」）。數字非負，允許 `null`；缺值步驟保留列名與空位，相鄰缺值時略去轉換率與流失數。相鄰兩步都有值且前一步大於 0 時自動計算轉換率，預設強調最低轉換率的步驟。流失主張使用 `loss: true`，並明確指定對應的到達步驟 `focus`；兩處流失可用 `["送出", "確認"]`。首步不標流失，持平標 0、增加標正值並警告。
- 輸出：SVG。
- 常見錯誤：各步驟不是同一批人或同一口徑；把每階段流失量當成留下的數量；前一步為 0 卻聲稱轉換率有意義。後一步較大會警告，先查分母與定義。
- 最小範例：`{"kind":"funnel","steps":[{"label":"送件","value":100},{"label":"完成","value":70}]}`。完整檔：[examples/funnel.json](../examples/funnel.json)。

## 需要逐格查數字或文字？

### 表格 `table`

用於精確讀值、不同單位並列，或來源只有分類文字而沒有可畫數字的情況。

- 欄位：`columns: [{name, type?, digits?, suffix?, better?}]`、`rows: [[儲存格, ...], ...]`；選用 `total: [儲存格, ...]`、`emphasis`（首欄符合此值的列強調）。每列與 `total` 格數須等於欄數。
- `type`：`text`、`number` 或 `delta`。省略時依內容推斷，明寫較容易核對；`number` 與 `delta` 儲存格須是數字或 `null`，`text` 可放文字或 `null`。任何型別的 `null` 都在原格寫「未提供」，並自動以「列名／欄名」列入來源缺值說明，SVG 與原生表格相同。`delta` 只格式化已提供的差額，`total` 只顯示已提供的合計，都不代算。
- `digits`：欄位或整張表的 `digits` 都沒填時，每格照數值本身的小數位顯示（24.7 印成 24.7），不套上方圖表預設的 `0`；填了才照位數四捨五入。
- 輸出：原生 PowerPoint 表格，直接編輯儲存格，沒有圖表活頁簿。
- 常見錯誤：格數不一致；用加上千分位的字串填數值欄；以為 `total` 自動相加。純文字表格可用於無數字文字稿，但若只是比較方案，`compare` 通常更直接。
- 最小範例：`{"kind":"table","columns":[{"name":"項目","type":"text"},{"name":"件數","type":"number"}],"rows":[["甲",12],["乙",8]]}`。完整檔：[examples/table.json](../examples/table.json)。
