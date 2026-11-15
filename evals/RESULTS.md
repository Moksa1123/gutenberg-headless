# evals 結果

最新的在最上面。題目與評分標準見 `cases.json`，評分程式 `grade.py`（照抄 elementor-headless／line-api）。資料版本：booking.moksaweb.com、WP 7.1、Blocksy 2.1.53（2026-08-28 抽取）；往返資料 2026-11-15 重測。

## 2026-11-15 第 1 輪（現行題組）

- 出 17 題，兩邊各跑一次。沒 skill 也答對 5 題（`tabs-active-index`、`mobile-state-breakpoint`、`product-price-context`、`binding-sources`、`block-visibility-mobile`），已在 `cases.json` 標 `retired`；下表只列現行 12 題。`mobile-state-breakpoint` 是沒 skill 的作答者把 689.98px 當成「也可能是」列出來，被評分規則算對，照規則一樣淘汰。
- 回答原始 17 題時：有 skill 17/17，沒 skill 5/17。
- 有 skill 的作答者回報：找子區塊沒有直接的查法、`gb.py context` 和 205／69／28 的分法不同、往返資料標的版本和抽取時不同、往返題在路由表沒有對應列。SKILL.md 已補路由列與說明。

| 項目 | 有 skill | 沒有 skill |
|---|---|---|
| 計分題答對率（12 題） | **12/12（100.0%）** | 0/12（0.0%） |
| 全部題目（12 題） | 12/12 | 0/12 |
| 模型 | claude-opus-5-5 | claude-opus-5-5 |
| 作答方式 | subagent 讀 SKILL.md、用 gb.py 查 | subagent 不用任何工具，憑記憶作答 |
| 答案檔 | `evals/runs/2026-11-15-with-skill.json` | `evals/runs/2026-11-15-without-skill.json` |

| 題目 | 可信度 | 有 skill | 沒有 skill | 備註 |
|---|---|---|---|---|
| `tabs-structure-71` | measured | ✅ | ❌ |  |
| `bare-page-empty-count` | measured | ✅ | ❌ |  |
| `dynamic-count` | measured | ✅ | ❌ |  |
| `blocksy-blocks` | measured | ✅ | ❌ |  |
| `button-link-attr-order` | measured | ✅ | ❌ |  |
| `image-button-deprecations` | measured | ✅ | ❌ |  |
| `palette-color-3` | measured | ✅ | ❌ |  |
| `preset-counts` | measured | ✅ | ❌ |  |
| `editor-vs-registry` | measured | ✅ | ❌ |  |
| `roundtrip-live` | measured | ✅ | ❌ |  |
| `playlist-breakpoint` | measured | ✅ | ❌ |  |
| `product-context-count` | measured | ✅ | ❌ |  |

