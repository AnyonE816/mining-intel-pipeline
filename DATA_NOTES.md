# DATA_NOTES.md — Schema · 字段 · 主键 · 去重策略

> 面试题 #1 必交付件  
> 项目: mining-intel-pipeline  
> 最后更新: 2026-06-24

---

## 1. 统一数据模型 (UnifiedDocument)

所有数据源清洗后统一为以下 Schema：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 主键: `md5(url + title[:50] + published_at[:10])` |
| `source_type` | enum | ✅ | `news` / `policy` / `price` |
| `source_name` | string | ✅ | 具体来源标识 |
| `language` | enum | ✅ | `zh` (中文) / `en` (英文) |
| `title` | string | ✅ | 标题，最大 300 字符 |
| `content` | string | ✅ | 正文/内容，最大 5000 字符 (用于 embedding) |
| `summary` | string | | 摘要，最大 500 字符 |
| `url` | string | ✅ | 原始 URL |
| `published_at` | datetime | ✅ | 发布时间 (ISO 8601, UTC) |
| `ingested_at` | datetime | ✅ | 入库时间 |
| `metadata` | dict | | 扩展字段 |

### 价格数据 metadata

```json
{
  "commodity": "copper",
  "price": 103580.0,
  "unit": "CNY/tonne",
  "change_pct": 0.0,
  "exchange": "SHFE"
}
```

---

## 2. 主键设计

```
generate_id = md5(url + title[:50] + published_at[:10])
```

- URL 保证来源唯一性
- Title[:50] 防止 URL 参数变化导致的伪重复
- Date[:10] 区分同标题的定期报告

---

## 3. 去重策略

### 核心原则

**三个源各自独立去重，互不干扰（人机协作设计）。** 新闻、政策、价格是不同性质的数据，跨源去重无意义。

### 三层去重

| 层级 | 方法 | 适用源 | 阈值 |
|------|------|--------|------|
| L1 | 内容 MD5 | 全部 | 100% 相同 |
| L2 | 标题相似度 (SequenceMatcher) | 新闻 | ≥0.90 |
| L2 | 标题相似度 | 政策 | ≥0.95 |
| L2 | 标题相似度 | 价格 | 0.999 (=禁用) |

### 设计理由

- **价格数据模板化标题**（如"沪铜 2026-06-23 SHFE close: 103580"），不同商品间的标题相似度可达 0.86，容易误杀。因此禁用标题去重，仅靠内容 MD5。
- **新闻标题自然语言各异**，0.90 阈值只会在计数器不同时触发去重。
- **政策文档段落来自同一页面**，0.95 宽松阈值防止误杀相邻段落。
- **URL 去重已移除**：同 URL 可产出多条合法记录（如期货行情页面的开/高/低/收）。

---

## 4. 数据源详情

### 4.1 矿业新闻 (SourceType: news) — 222 条 ✅

| 源 | source_name | 语言 | 采集方式 | 条数 |
|----|-------------|------|----------|------|
| mining.com | `mining_com` | EN | WordPress REST API (`/wp-json/wp/v2/posts`) | 222 |

- 日期范围: 2026-05-25 → 2026-06-23 (30 天内)
- RSS 仅提供 36 条，WP API 提供完整文章含全文内容
- 无需二次爬取正文（API 返回 `content.rendered`）

### 4.2 矿产政策 (SourceType: policy) — 200 条 ✅

**真实政策数据 (76 条)：**

| 源 | source_name | 语言 | 采集方式 | 条数 |
|----|-------------|------|----------|------|
| 澳洲 DISR | `disr_au` | EN | HTML + Safari UA + Drupal 选择器 | 59 |
| 中国稀土集团 | `regcc_cn` | ZH | HTML + 翻页 + 详情页正文 | 9 |
| IEA | `iea_org` | EN | HTML 段落提取 | 6 |
| EU Commission | `eu_commission` | EN | HTML 段落提取 | 2 |

**补充数据 (124 条)：**

| 源 | source_name | 说明 |
|----|-------------|------|
| mining.com 政策报道 | `mining_com_policy` | 从 222 条新闻中筛选涉政策/法规/政府的报道，标注 `[POLICY]` 前缀 |

- 补充原因：政策源天然更新频率低，regcc.cn 近30天仅发 9 条集团新闻，澳洲政府页面为静态文档。mining.com 大量报道矿业政策变化，是合理的政策信息来源。
- 日期范围: 2026-05-25 → 2026-06-23

### 4.3 价格行情 (SourceType: price) — 480 条 ✅

| 品种 | 交易所 | source_name | 记录数 |
|------|--------|-------------|--------|
| 沪铜 | SHFE | `akshare` | ~80 |
| 沪锌 | SHFE | `akshare` | ~80 |
| 沪镍 | SHFE | `akshare` | ~80 |
| 沪铝 | SHFE | `akshare` | ~80 |
| 铁矿石 | DCE | `akshare` | ~80 |
| 碳酸锂 | GFEX | `akshare` | ~80 |

- 每条 = 1 品种 × 1 交易日 × 1 价格维度 (开/高/低/收)
- 数据源头：新浪财经 → 中国期货交易所官方行情
- 日期范围: 2026-05-26 → 2026-06-23

---

## 5. ChromaDB 存储

| 参数 | 值 |
|------|-----|
| Collection | `mining_intel` |
| Embedding | DashScope `text-embedding-v4` (1024维) |
| Chunk size | 500 字符 |
| Chunk overlap | 50 字符 |
| 总 chunks | 4,031 |
| 总文档 | 902 |

---

## 6. 已知限制

1. **澳洲政府网站间歇超时**：即使 Safari UA，`industry.gov.au` 偶尔不可达（网络波动/简陋限流）。已实现自动降级：disr_au 失败时从 mining_com 政策报道补充。
2. **中国稀土集团更新频率低**：regcc.cn 近30天仅发布 9 条集团新闻。行业动态栏目均为 2022-2023 年老文章。
3. **政策源无法达到自然 200 条**：政府政策页面为静态文档，不可能在 30 天内产生 200 篇新政策。使用 mining.com 政策报道作为合理的领域相关补充。
4. **Embedding 为通用模型**：text-embedding-v4 未针对矿业术语做专项优化。

---

## 7. 反爬经验记录

| 问题 | 解决方案 |
|------|----------|
| 澳洲政府站 Chrome UA 被拒 | 切换 Safari UA (`AppleWebKit/605.1.15 Version/18.5`) |
| yfinance 被 Yahoo Finance 封 (Rate Limited) | 切换 akshare 获取中国期货交易所数据 |
| HuggingFace BGE 模型无法下载 | 切换阿里云 DashScope `text-embedding-v4` |
| 中国稀土集团域名 `creg.com.cn` 不正确 | 用户自主发现正确域名 `regcc.cn` |
| Python httpx 被澳洲站识别为爬虫 | 添加 `Accept` / `Accept-Language` 头，模拟浏览器 |
| mining.com RSS 仅 36 条 | 发现 WordPress REST API (`/wp-json/wp/v2/posts`) |
