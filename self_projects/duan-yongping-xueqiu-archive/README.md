# 段永平（大道无形我有型）雪球存档 · Duan Yongping Xueqiu Archive

个人项目 / personal project · 2026

雪球主页：<https://xueqiu.com/u/1247347556>

---

## 📅 数据覆盖范围 / Data coverage

| | |
|---|---|
| **最早一条 / from** | **2011-03-24 06:51** |
| **最新一条 / through** | **2026-06-28 00:06** |
| **抓取日期 / last scraped** | **2026-06-28** |
| **总条数 / posts** | **10,712** |
| **最新条 id（更新锚点）** | `397169057` |

> 也就是说：本存档里**只有到 2026-06-28 00:06 为止**的发言。  
> 这之后他发的任何新内容**都不在里面**，需要重新抓取才会有。

## 🔄 何时 / 如何更新 / When to update

下次想更新时，只需补抓"最新一条之后"的增量：

1. 重新抓取 timeline（page 1 往后）。
2. **一直抓到遇见 id = `397169057` 为止**——它之前的都已存档。
3. 把新抓到的（id 比它新的）合并进 `大道无形我有型_posts.json`，重跑脚本即可。

更新后记得改本文件和 `coverage.json` 里的 **through / last_scraped / newest_post_id**。

精确机器可读的覆盖信息见 [`coverage.json`](coverage.json)。

---

## 📂 目录 / Contents

```
大道无形我有型_posts.json   结构化全量数据（10,712 条）
大道无形我有型_posts.csv    同上，CSV（Google Sheets / Excel 用，UTF-8 BOM）
大道无形我有型_posts.txt    可读版（按时间倒序）
coverage.json              覆盖范围 + 更新锚点
analysis/
  段永平_思维原则.md         8 条核心原则提炼（附高赞原话）
  README.md                分析包说明
  companies/               逐公司发言（按时间）：苹果/茅台/腾讯/拼多多/泡泡玛特/特斯拉/网易/巴菲特
  themes/                  逐主题原文：本分/能力圈/商业模式/企业文化/平常心/估值/分红回购/长期
raw/checkpoint_raw.json    抓取原始备份
scripts/
  json_to_csv.py           JSON → CSV
  dyp_format.py            JSON → 可读 txt
  build_analysis.py        生成 analysis/ 切片
  search.py                关键词检索：python3 scripts/search.py "护城河"
  xueqiu_scrape.py         独立抓取脚本（参考）
```

## 字段 / JSON fields
`id, created_at(ms), source, text, is_reply, ctx{author, author_id, text, url}, reply_count, like_count, retweet_count, fav_count, view_count, url`
