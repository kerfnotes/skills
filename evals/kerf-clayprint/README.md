# Clayprint：從文字稿驗收簡報

這裡放驗收用的原稿與清單。它們在 repo 根目錄的 `evals/`，不在 skill 資料夾裡，安裝 skill 時不會被帶走，製作者讀不到清單。製作者需要的 check 指令說明在 skill 內的 [evals/README.md](../../skills/kerf-clayprint/evals/README.md)。

| 原稿 | 清單 | 測什麼 |
|---|---|---|
| [with-numbers.md](with-numbers.md) | [with-numbers.checklist.md](with-numbers.checklist.md) | 有數字：圖表選擇、資料底線、算式、原生圖表 |
| [without-numbers.md](without-numbers.md) | [without-numbers.checklist.md](without-numbers.checklist.md) | 無數字：不造量化圖、推薦與待決分開 |

## 怎麼跑

1. 每次開一個全新的製作者 agent，只給它 skill 路徑、一份原稿副本（複製到它的輸出資料夾，不要給這個資料夾的路徑）與輸出資料夾。不提供預寫好的故事線或簡報答案。
2. 製作者交付後，另開一個全新的驗收者 agent，給它清單、原稿與交付物，逐項判「通過／不通過／無法驗證」。製作者不讀清單，驗收者不由製作者兼任。
3. 從 skill 資料夾執行 `node evals/check.mjs <story.json> ../../evals/kerf-clayprint/with-numbers.md`（或 without-numbers.md）重跑自動驗收。
4. 查製作者的對話紀錄，確認它沒有讀這個資料夾。
