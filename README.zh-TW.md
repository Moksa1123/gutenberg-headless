# gutenberg-headless

**幾秒鐘寫出 WordPress 區塊編輯器頁面。不開編輯器，不用猜。**

一個給 Claude Code 用的
[Agent Skill](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)，
用三種方式產生 Gutenberg 頁面：

### 三種建法

| 方式 | 輸入 | 輸出 | 證明 |
|------|------|------|------|
| **口語描述** | 「深色 hero＋卡片＋FAQ＋結帳」 | post_content，直接發布 | 一頁式行銷頁上線並完成真實訂單 |
| **HTML 轉換** | 任何手寫 HTML/CSS/JS/SVG 頁面 | 同一頁的區塊版 | 重建到視覺一致、編輯器位元組正準 |
| **查詢 Schema** | 「core/group 能做什麼？」 | 屬性、supports、presets、實測判定 | 免費、即時、來自量測資料 |

描述就好。Agent 負責查表、驗證兩半、寫入，然後**在公開網址與編輯器裡雙重證明**。

---

把一個活站的完整區塊編輯器授權面做成可查詢的資料庫 — 每個主張都經過渲染、
重存、量測驗證，因為 WordPress 存壞掉的標記時一聲不吭。

```
伺服器  302 種區塊 · 3,188 個屬性 · 4,141 個 support 旗標 · 105 個 preset slug
        37 個樣式引擎屬性 · 86 個 patterns · viewport 斷點
編輯器  280 種區塊 · 173 個 variations · 168 個 transforms · 192 個「已棄用」形式
        每個區塊 save() 實際寫出的類別順序、CSS 順序與標籤形狀
情境    302 個全部歸位：各自需要什麼才會渲染
```

兩個註冊表不是同一組，而 variations、transforms、棄用版本和正準形全部住在
第二個裡面。伺服器回報 3 個 variations，編輯器有 173 個。

[English](README.md) · 繁體中文

---

## 為什麼需要這個

### 無聲失敗是這個格式的天性

一個 Gutenberg 區塊是**兩半互不檢查的東西**：comment JSON 是給*編輯器*讀的，
儲存的 HTML 是給*訪客*看的：

```html
<!-- wp:paragraph {"backgroundColor":"accent"} -->
<p>hello</p>
<!-- /wp:paragraph -->
```

- comment 說有背景、HTML 少了 class → 訪客看不到背景，編輯器看得到，**沒有錯誤**
- preset slug 站上不存在 → class 進了 HTML，但沒有任何 CSS 定義它
- 站上沒註冊的區塊 → 訪客看到原始 HTML，編輯者看到復原對話框
- sourced 屬性（`content`、`url`…）寫進 comment → 完全沒作用，無聲
- 儲存的 HTML 對不上 `save()` → 區塊靠 deprecation 保持「有效」，
  但下一次手動儲存會**改寫你的標記，並吃掉它不認得的部分**

九成正確的頁面看起來跟全對的頁面一模一樣 — 直到訪客看不到背景，
或編輯者存檔時默默刪掉你的東西。

### 解法

權威的授權面 — 每個區塊、屬性、support、preset、樣式屬性 — 全部從活站抽取
並以渲染驗證。加上任何 schema 都給不了的東西：一個驗證*兩半是否一致*的
validator，以及把編輯器本人當最終仲裁者的驗證迴圈。

## 運作方式

![architecture](assets/diagrams/architecture.svg)

三個階段。**抽取**：每個站跑一次（WP-CLI），dump 區塊註冊表、合併後的
theme.json、以及樣式引擎自己的屬性→CSS→class 對照表。**驗證**：302 個區塊
全部推過 `do_blocks()`、解析器對 `serialize_blocks()` 做位元組往返，判定寫回
資料。**查詢**：agent 建頁時只做這件事 — 425 KB 的 schema 用查的，永遠不整份載入。

## 安裝

用 npm — 不用 clone、安裝階段不需要 Python（Python 只在之後跑查詢／驗證工具時才用到）：

```bash
npx gutenberg-headless claude-code --global    # 或 cursor、codex-cli、gemini-cli...
npx gutenberg-headless --list
```

或從 clone 安裝（同一套平台設定，Python 安裝器）：

```bash
git clone https://github.com/Moksa1123/gutenberg-headless
cd gutenberg-headless
python tools/install-skill.py claude-code --global
```

8 個平台：Claude Code、Claude.ai、Cursor、Codex CLI、Gemini CLI、Devin
（前 Windsurf）、GitHub Copilot、Continue — 沿用姊妹技能 elementor-headless
驗證過的平台慣例（每個設定檔帶 `verifiedAsOf` 日期；是查核過的，不是假設的）。
升級時會清掉上一版留下的檔案。`SKILL.md` 是入口。步驟 1–3 純本地；步驟 4–7 需要 WordPress 主機上的
WP-CLI（通常走 SSH），編輯器仲裁與設計審計另需任一瀏覽器自動化管道。

## 使用

裝好 skill，然後直接對 agent 描述頁面。skill 教它這個迴圈：

```
1. 查授權面      gb.py              這個站有哪些區塊、屬性、家族、實測判定
2. 寫標記        (agent)            兩半都寫，依據 schema
3. 寫入前驗證    validate-post.py   WordPress 不會報的 11 類錯誤
4. WP-CLI 寫入   apply-post.php     繞過 kses＋slashing＋style.css 剝除；
                                    寫入後逐位元組回讀比對；清快取
5. 驗證公開頁    verify-live.py     穿過頁面快取的公開網址
6. 問編輯器本人  (瀏覽器 console)    每個區塊 isValid，且
                                    serialize(getBlocks()) === 儲存內容
7. 設計審計      audit-contrast.js  WCAG 對比零失敗＋theme.json 斷點的 RWD 檢查
```

常用查詢 — 每個都在幾百 token 內給出完整答案：

```bash
python tools/gb.py stats                        # 這是哪個站、裡面有什麼
python tools/gb.py block core/group             # 家族、屬性、supports、判定
python tools/gb.py presets color                # 每個 slug＋CSS 變數＋值
python tools/gb.py var "var:preset|color|x"     # 展開 ref、確認存在
python tools/gb.py skeleton                     # 最小合法頁面
python tools/gb.py grammar                      # 序列化速查表
```

## 不是每個站都有每個區塊

**區塊授權面是「站點」的屬性，不是 WordPress 的。** 抽取站註冊了 302 種：
116 個 `core/*`、165 個 `woocommerce/*`、13 個來自主題。裸裝 WordPress 只有
約 116 個。而 `is_dynamic` 會誤導 — 302 個中有 272 個帶 render callback，
連 `core/heading` 都是。真正重要的分類是內容住在哪裡：

| 家族 | 數量 | 你要寫的 |
|---|---|---|
| 內容在 HTML（有 sourced 屬性） | 28 | comment＋完整儲存 HTML |
| 靜態容器 | 14 | comment＋容器 HTML |
| 純動態 | 260 | 一個 void comment — 屬性就是一切 |

以及掛在每個區塊上的關鍵數字：**205／302 在空白頁面上渲染不出任何東西** —
它們需要商品、文章、購物車、查詢迴圈。`gb.py block <名稱>` 會在你發布一個
隱形頁面之前告訴你。

## Token 成本與時間

**比讀 WordPress 原始碼省 85.1% token、比載入整份 schema 省 93.4%、
模型 ingest 約 5 倍快。** 工具延遲是實測的（每次查詢中位數 241 ms）；ingest
時間由 token 數在揭露的 1,000 tok/s 參考速率下推得 — 改速率，比值不變。
自己重跑；腳本會寫出 `data/token-benchmark.csv`：

```bash
pip install tiktoken
python tools/benchmark-tokens.py --wp-src /path/to/wordpress
```

| 任務 | 讀原始碼 | 載入 schema | **查詢** |
|---|---|---|---|
| 建一個 group 區段（layout、背景、間距 preset） | 19,036 | 102,812 | **627** |
| 標題的顏色＋字型，含合法 preset slug | 13,855 | 102,812 | **1,132** |
| 這個站能用的每一個 preset slug | 4,215 | 102,812 | **3,935** |
| woocommerce/product-price 在這裡會渲染嗎、要放在什麼裡？ | 433 | 102,812 | **383** |
| 哪個 style 鍵驅動 box-shadow、合法的 shadow preset | 8,109 | 102,812 | **743** |
| **合計** | **45,648** | **102,812** | **6,820** |

有兩列幾乎沒省 — 而且留在表裡。preset 任務讀的是兩個精簡的 theme.json
（省 6.6%）、product-price 的 block.json 很小（11.5%）— 但這兩個基準都答不了
會無聲失敗的那一半：外掛 filter 注入的合併 preset、以及不存在於任何檔案裡的
空白頁渲染判定。省得多的地方在原始碼攤得開的地方（supports 語意：96.7%）—
而正確性無處不在。Token 用 tiktoken `cl100k_base` 計算 — 那是 OpenAI 的
tokenizer 不是 Claude 的，絕對值會差約 ±10%；同一個 tokenizer 下的比值穩定，
而比值才是主張。

## 自訂 CSS 與 JS — WordPress 到底給了什麼

**per-block 自訂 CSS 是原生的**（WP 7.0+，`style.css` 屬性，支援 `&` 巢狀，
編譯進 `:root :where(...)`）。**per-block 自訂 JS 核心完全沒有。** 頁面級的
CSS 與 JS 走一個 `core/html` 設計層＋一個行為層 — 這是本 repo 範例頁使用、
且編輯器逐位元組接受的模式。完整實測（含特異性天花板、以及 WP-CLI 寫入時會
吃掉 `style.css` 的剝除過濾器）在
[custom-css-js.md](references/custom-css-js.md)。

## 從 Elementor 搬過來

`tools/el2blocks.py` 把 `_elementor_data` 轉成區塊，而且不用猜：它讀姊妹技能
[elementor-headless](https://github.com/Moksa1123/elementor-headless) 實測出的
control→CSS 對照表（25,357 列），跟本技能的樣式引擎對照表比對。在測試站真實的
Elementor 首頁（63 KB 的樹、12 種 widget）上：**158 個區塊、validator 0 錯誤、
編輯器 0 個 invalid**，每個有損的決定都由 `--report` 列出（背景疊層丟棄、
icon-box 圖示丟棄、兩個 widget 保留成帶原始設定的可見佔位）。做法與誠實限制：
[elementor-migration.md](references/elementor-migration.md)。

## 準不準？讓它自己證明。

**1. 解析器對得上 WordPress 嗎？** `blockmark.py` 對活站上**每一篇**含區塊的
文章做位元組往返（19 篇、111 KB）。它寫的是正準形，也就是兩個序列化器都會寫的
形式。兩類分歧，都量測過、都不藏：伺服器自己的 `{}`→`[]` 正規化，以及註解 JSON
裡的字面 `&` `<` `>` `--`（每個序列化器都會跳脫）。這個 repo 自己有三個範例
帶著字面 `&` 和 `>`，直到這條檢查存在為止 —— 寫進文件卻沒有任何地方強制的規則，
等於沒有規則，所以它現在是 `W-ESCAPE`。

**2. 每個區塊渲染出 schema 說的東西嗎 — 渲染不出來的話缺什麼？** 302 個全部
推過 `do_blocks()`，零錯誤：69 個能渲染、205 個渲染空、28 個是內容區塊。
「渲染不出東西」是判定不是診斷，所以同一批再跑一次，這次放進真實頁面能提供的
情境裡，記錄第一個產生輸出的：

```
 101  需要父區塊              17  有文章就渲染
  69  空白頁就渲染            15  有商品就渲染
  23  內容在 HTML，void 本來就空   2  分類彙整 · 2 登入後
   9  static wrapper          64  需要這個掃描沒建的情境，或站上根本沒有那個資料
```

`gb.py context` 印出這張表。第一次跑的結果是垃圾 —— 情境在區塊之間洩漏，
`core/post-content` 在「空白頁」下吐出 3,849 bytes。修正後的空白頁那一輪是 69，
與獨立的 sweep 完全一致。

**3. 樣式面是引擎的，還是人的記憶？** `data/style-surface.json` 直接 dump
站上的 `WP_Style_Engine::BLOCK_STYLE_DEFINITIONS_METADATA`。save-time 與
render-time 的分界**逐屬性量測**（編輯器 `getSaveContent` 輸出什麼 vs 伺服器
render 時注入什麼）。

**4. 編輯器本人接受這些標記嗎 — 位元組級？** 每個出貨範例的標準，四個在正準化
規則被發現之後**全部重驗**：wp-admin 打開、全部 `isValid`、序列化結果與儲存
位元組相同。21、169、48、20 個區塊，零無效、零漂移，再加上 180 個區塊的轉換頁。

這個檢查有個值得知道的盲點：拿 `getCurrentPost().content` 比對，比的是編輯器輸出與
**REST API 送來的內容**，而那條路徑會把 `&` `<` `>` `--` 跳脫掉 —— 所以資料庫裡
是字面 `&` 的頁面會回報「一致」。要比**儲存位元組的雜湊**，而且比雜湊不要比長度：
PHP 數 UTF-8 位元組、JavaScript 數 UTF-16 code unit，同一個 169 區塊頁面一個說
47,282、一個說 45,031。

正準形本身也不再是口耳相傳：用合成屬性對每個區塊探測 `getSaveContent` 九次，
只有**從不翻轉**的順序才算規則 —— `gb.py save <block>` 印出來、轉換器直接讀它
而不是讀手寫表格、標記不符時 `validate-post.py` 報 `W-ORDER`。全部規則在
[canonicalization.md](references/canonicalization.md)。

**5. 公開頁面全部都有嗎？** `verify-live.py` 穿過頁面快取抓公開網址，斷言
每個文字片段、class、行內規則、preset 變數定義 — 行銷頁 356 項全綠。

**6. 設計經得起量測嗎？** `audit-contrast.js` 在頁面內算 WCAG 對比 —
走訪祖先找真實底色、漸層取每一個色標、cover 遮罩混色、星號當圖形。首跑在
一個「看起來還行」的頁面抓到 15 個真問題；標準是零。

**6b. 那些你沒測到的寬度呢？** 七個抽樣寬度全部 PASS。連續掃描 320–1600px
之後，找到 **1040–1152px 有一整段溢出**，那七個點沒有一個落在裡面。
`rwd-scan.js` 回傳每個寬度的 signature，驅動程式掃過範圍、把每個變化
**二分搜尋到像素**。溢出分成頁面內容與網站框架兩邊計算 —— 因為那一段最嚴重的
元素其實是主題自己的頁首，全站每頁都一樣。

那一段是真的轉換缺陷，原因值得記住：flexbox 裡 auto margin **優先權高於
`align-items`**，而且只分配**正的**剩餘空間，所以視窗比內容區窄時它把盒子
釘在單邊，同時壓掉父層本來就在做的置中。

**6c. 這個模型跟 WordPress 對得上嗎？** 其他檢查都在問頁面符不符合模型；
`selftest-patterns.py` 反過來問，拿驗證器規則去跑 WordPress、WooCommerce 和
主題出貨的 86 個 pattern。57 個完全乾淨。它抓到我規則裡的兩個真 bug —— 以及
四件單純是核心自家內容事實的事，包括**寫成已棄用形式**的 pattern，和 30 個
在傳統主題站上根本不存在的 preset slug。

**7. 電商真的能動嗎？** 一頁式從公開頁完成真實下單：加入購物車 → 同頁區塊
結帳 → 台式地址欄位順序 → 離線金流 → **資料庫裡的訂單**。之前那次失敗
（外掛的結帳欄位在非結帳頁不渲染）連同解法寫在
[woo-onepage.md](references/woo-onepage.md)。

## 陷阱

每一條都是做這個 repo 時親自踩到的 — 現在都是 validator 規則、工具行為或文件：

1. sourced 屬性寫進 comment 沒有作用 — 內容住在 HTML 那一半
2. `is_dynamic` 不是你以為的意思；272／302 帶 callback
3. WP-CLI 寫入被弄壞兩次：kses（無使用者→過濾器全開）與 unslash 吃掉跳脫
4. per-block custom CSS 有**第三個**剝除器：`content_save_pre` 對沒有
   `edit_css` 的使用者刪掉 `style.css` — WP-CLI 也算
5. 過時寫法保持「有效」但下次儲存會被改寫 — 寫現行正準形
6. save-time vs render-time：`has-*` 自己寫；`wp-container-*`／`wp-elements-*`
   ／`wp-states-*` 永遠不寫 — 伺服器會注入
7. per-block custom CSS 被 `:where()` 鎖在特異性 (0,1,0) — **設計上如此**；
   打不過外掛的 `!important`，頁面級 `<style>` 層是逃生口
8. 流體字級在 render 時把你的 `font-size` 改寫成 `clamp()` — 儲存位元組與
   交付位元組合法地不同
9. 含結帳區塊的頁面上 `is_checkout()` 是 false — 條件註冊的結帳欄位不渲染，
   但伺服器端驗證照樣擋單
10. 伺服器 registry 看不到 JS 注入的屬性、client 註冊的 variations、
    以及 `save()` 本身 — 編輯器 console 是唯一的仲裁者
11. PHP 在任何伺服器端重存把 `{}` 正規化成 `[]`；編輯器不會
12. 註解 JSON 裡的字面 `&` `<` `>` `--` 會解析、會渲染、會通過驗證 —— 然後被
    任何一邊的第一次儲存改寫（`W-ESCAPE`）
13. `className` 落在 `core/button` 的**外層**，永遠不在 `<a>` 上。寫到連結上
    的類別是 `save()` 不會產生的標記：存得下、畫得出、編輯器判定無效
14. 同一個站上有四個寬度都叫「mobile」—— `style["@mobile"]` 689.98px、
    `core/columns` 781px、`core/media-text` 600px（後兩者寫死在自己的 CSS 裡，
    而且共用同一個屬性名 `isStackedOnMobile`）、Elementor 767px。而且
    `@tablet` 是**區間**不是 max-width
15. auto margin 優先權高於 `align-items`，卻在剩餘空間為負時放棄 —— 它會把
    你要它置中的東西弄成不置中
16. 文章編輯器讀不到的 22 個區塊，多數是**網站編輯器**的區塊；註冊表、pattern
    甚至範本清單都會隨主題改變（實測：換一個主題，區塊 302→299、pattern 86→162）

## 誠實的限制

- **`data/` 描述的是抽取站**（WP 7.1、Blocksy、WooCommerce）。它是能跑的
  範例；用在自己站之前先重抽。
- **編輯器的 `save()` 與 deprecations 只存在 JS。** validator 執行它們的
  規則；編輯器 console 迴圈是最終仲裁 — skill 把它排進流程，而不是假裝不需要。
- **WordPress 核心沒有 per-block 自訂 JS。** 互動來自核心互動區塊
  （tabs、accordion、details、lightbox、fitText），或一個刻意設計的
  `html` 區塊行為層 — 這是本 repo 使用並文件化的模式，不是 WordPress 功能。
- **綁定版本**：所有數字量測於 WordPress 7.1。新版本可能推翻任何一條 —
  所以抽取器與掃描器都隨包出貨，對*你的*站重跑。
- **這個面是「主題」的屬性，不只是「站」的。** 在測試站真的啟用一個區塊主題
  之後：註冊表 302→299（13 個主題區塊消失、10 個 WooCommerce 區塊出現）、
  pattern 86→162、範本 8→16。`extract-block-schema.php <theme>` 可以在不切換
  主題的情況下描述另一個已安裝的主題，但它只對 theme.json 宣告的內容和該主題
  自己的檔案忠實 —— 沒有任何東西會重跑 boot，所以 `theme_supports` 以及由它
  註冊的一切仍是啟用中主題的。輸出裡會寫明哪些可信、哪些不可信。
- **還有 64 個區塊沒有解釋。** 這個數字混了兩種東西：情境掃描沒建的情境
  （有商品的購物車、結帳工作階段），以及站上根本沒有那個資料 —— `core/site-tagline`
  在這裡是空的，因為網站標語本身就是空字串。我沒有把它湊成比較好看的數字。

## 重新抽取你的站

```bash
wp eval-file tools/extract-block-schema.php > dump.json
wp eval-file tools/sweep-render.php > render-sweep.json
python tools/build-indexes.py dump.json --out data/ --render-sweep render-sweep.json
python tools/gb.py stats      # 確認它現在描述的是「你的」站
```

## 授權

MIT。由 **moksa** 打造與維護 · [moksaweb.com](https://moksaweb.com)

姊妹技能：[elementor-headless](https://github.com/Moksa1123/elementor-headless) ·
[rankmath-seo-wp](https://github.com/Moksa1123/rankmath-seo-wp)
