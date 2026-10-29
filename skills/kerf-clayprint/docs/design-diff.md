# Phase 3：PowerPoint 與設計稿的差異

對照 B′ 深藍版的 [簡報樣張](https://github.com/kerfnotes/skills/blob/4602afa8a7a5f2003cbd966c40ab7023b4b7d9ec/skills/kerf-clayprint/design/claude-design/Blueprint%20Deck.dc.html)、[圖表樣張](https://github.com/kerfnotes/skills/blob/4602afa8a7a5f2003cbd966c40ab7023b4b7d9ec/skills/kerf-clayprint/design/claude-design/Blueprint%20Charts.dc.html)（已移出目前版本，連到 Git 歷史）與 [規格 v1.1](../design/spec.md)。色彩、字級與線寬以[目前生效的設計層](../design/README.md)為準。以下實機驗收紀錄對應原本的 B′ 深藍版本，clay 輸出仍需另行驗收。既有開檔紀錄與當次輸出的驗收分開記錄；正式交付需逐頁預覽，並實際操作「編輯資料」。

## 版型與字型

| 項目 | PowerPoint 的做法與原因 |
| --- | --- |
| 證據頁兩期比較 | `examples/story.json` 第 5 頁採斜率圖，取代簡報樣張的分組長條。目前也支援分組長條；此頁兩期仍用 Ordered 舊淺、新深的標記，資料與結論不變。 |
| 字型 | 設計稿優先使用 Helvetica Neue／蘋方；PPTX 的文字、原生圖表、嵌入 SVG 及 PNG 後備統一 Microsoft JhengHei（微軟正黑體），主題的 Hant 與 major／minor 東亞字型也一致，避免中文回退為新細明體。獨立 SVG／PNG 的預設字型不變。字型檔不嵌入 PPTX，接收端仍需有正黑體。 |
| 大數字字重 | 正黑體沒有設計稿使用的 300 字重；數字格及結論大數字採 regular，其餘強調文字採 bold。 |
| 排版餘量 | 正黑體的字高與字寬不同，標題行數採可用寬度的 95% 估算，來源格的水平位移採估算字寬的 1.1 倍；來源列與內文可能較設計稿早換行。大數字超過欄寬、步驟／比較／收尾列高不足時警告，固定字級不縮小，仍需看輸出畫面判斷。 |

## 圖表與可編輯範圍

rank、line、slope、share、scatter、grouped、sharetrend、ordered 使用原生圖表及內嵌活頁簿；table 使用原生 PowerPoint 表格，可直接改儲存格，沒有圖表活頁簿。其餘圖種維持 SVG 加 PNG 後備，圖中資料須改 spec 後重新輸出。

| 項目 | PowerPoint 的做法、原因與限制 |
| --- | --- |
| 折線線寬 | 原生 line 的所有系列統一使用 `T.stroke.otherLine`，即 1.5 px（0.75 pt）。pptxgenjs 4.0.1 無法逐系列設定線寬，故未保留 SVG 重點線 3 px／其他線 1.5 px 的區別；系列顏色仍依 model。 |
| 折線直接標值 | 不放圖例；每個系列只在輸出時最後一個有值的點標「系列名稱＋值」，focus 系列另標最高點。XML 標籤連動系列名稱與數值，但索引固定：新增資料欄後不會自動移到新尾端，最高點換位置也不會重選。這些變動需重新輸出。 |
| 斜率圖 | 每列為兩期折線，線為灰色，舊、新標記分別用 Ordered 第一階與最後一階。左端標「名稱＋值」，右端標「值」；隱藏數值軸與格線，保留兩期名稱。v1 省略設計稿的增減文字，避免改了內嵌資料後，旁邊靜態增減文字仍顯示舊值。 |
| 散佈名稱 | 逐點 `c:dLbl` 的名稱是靜態 `c:tx`，位置隨資料點移動，但名稱不連動活頁簿。修改點名須重新輸出或在 PowerPoint 手動改標籤。 |
| 散佈參考線 | 原生 scatter 的 v1 省略 `refs` 參考線與文字；有指定 `refs` 時發出警告，提示改用 `native: false` 的 SVG。圖表內部繪圖區由 PowerPoint 排版，外加圖形線段難以保證在改軸或改尺寸後仍對準。 |
| 數值軸上界 | 原生 rank、line、slope 不固定 Max，交由 PowerPoint 自動決定，讓編輯後增加的數值仍可顯示；刻度間距與下界仍取 model。share 的比例範圍固定為 0～100%。自動上界可能與 SVG 的 model 上界不同。 |
| 散佈留白與上界例外 | scatter 的 x、y 軸分別判斷：只有資料點貼到 model 邊界時，該邊向外加一個 step；沒有貼邊就不另加留白。貼上界時必須明定 Max 為原上界加一個 step，確保標記不貼框，這是自動 Max 的例外；其他情況使用自動 Max。編輯後若數值超過明定的 Max，需手動調整軸界或重新輸出。 |
| 橫條數值軸位置 | rank、share 類別反轉後，設定 `catAxisCrossesAt: 'max'`，使數值軸的 `c:crosses` 為 `max`，並用 `valAxisLabelPos: 'nextTo'` 讓刻度標籤跟隨軸線，修正軸與標籤分離的位置。 |
| 「其他」填色 | 原生 share 使用 `T.fill.other.native.color` 實色；SVG 仍用斜線。這是規格第 5、9 節明定的輸出差異。 |
| 百分比資料 | 原生 share 的活頁簿保留各類別原始值，右側另加標示「比例，自動計算」的公式欄，圖表引用比例欄，讓段內標籤顯示百分比且保留原始精度。編輯資料時應改左側原始值；公式欄由各列總和重算，不應直接覆寫。新增列或類別仍需重新輸出，才能更新公式範圍與類別配色。 |
| 預估填色 | 規格指定原生預估值用 `T.fill.estimate.native.color` 實色並加「預估」標籤，SVG 用斜線。目前具有 `estimate` 的 bridge 維持 SVG 路徑，因此仍保留預估斜線；本階段沒有新增原生預估圖。 |
| 原生表格 | 文字、對齊、顏色、強調列淡底與粗體、合計上線由 model 逐格對映；使用 `tableBody`／`tableHeader` 字級。垂直對齊改用 pptxgenjs 的 `middle`，輸出合法的 `anchor="ctr"`。PowerPoint 表格與設計稿 CSS 的欄寬、內距及換行可能不同。 |
| 極小值與強制 SVG | 非零值若在顯示精度下會成為 0，原生圖改走 SVG 並警告，以保留 `<`／`>−` 標籤；也可指定 `native: false`。這兩種情況沒有可「編輯資料」的圖表活頁簿。 |
| 標籤位置 | 原生圖表的標籤位置交由 PowerPoint 排版，無法逐像素重現 SVG 的固定偏移與避碰。刻度、數字精度、顏色取 model；軸界採上述自動上界與散佈留白規則。密集標籤仍可能需要手動調整。 |

原生圖的數值標籤使用 `showSerName`／`showVal`，並在逐點 `c:dLbl` 明定 `numFmt`，避免 PowerPoint 忽略系列層級格式；數字仍隨資料更新，不寫成靜態文字。scatter 名稱是上述例外。缺值從圖表 `numCache` 與活頁簿空儲存格移除，折線使用 `displayBlanksAs: gap`；0 則保留為觀察值。改內嵌資料只能更新 PowerPoint 的圖表，無法重新執行 Clayprint 的排序、Focus 選擇、極小值判定、缺值來源列或頁面結論；需要這些規則時應改原始 spec 後重產。

## 交付前的編輯驗收

在 PowerPoint 點「編輯資料」，修改一個現有數值並關閉資料視窗，確認圖形與數值標籤同步更新。交付註記「實際在 PowerPoint 改一個原生圖數值：完成／未驗」，並列出原生圖、原生表格與 SVG 的頁碼。

share／sharetrend 改左側原始值，確認右側比例公式與段內百分比更新；rank、line、slope 提高一筆數值，確認自動上界容納新值。scatter 若有明定 Max，超過上界時依上述例外手動調軸或重產。線尾固定索引、scatter 靜態名稱與新增資料欄限制，依表內說明驗收。比例公式是否立即更新，需在 PowerPoint 實際確認。

預設 clay 的正增減符號使用半形 "+"，與數字放在同一文字串中；相較全形「＋」，減少字形左右留白，PowerPoint 與 SVG 共用同一個 token。色彩與負號不變，實際字型下的間距仍需預覽。
