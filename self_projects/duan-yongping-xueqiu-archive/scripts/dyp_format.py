#!/usr/bin/env python3
"""Format scraped 大道无形我有型 posts into readable + clean JSON deliverables."""
import json, sys, datetime

src = sys.argv[1] if len(sys.argv) > 1 else "/Users/markues/Downloads/dyp_posts_partial.json"
posts = json.load(open(src, encoding="utf-8"))

# de-dup by id, sort newest first
seen, uniq = set(), []
for p in posts:
    if p["id"] in seen:
        continue
    seen.add(p["id"]); uniq.append(p)
uniq.sort(key=lambda p: p.get("created_at") or 0, reverse=True)

def ts(ms):
    if not ms: return ""
    return datetime.datetime.fromtimestamp(ms/1000).strftime("%Y-%m-%d %H:%M")

replies = sum(1 for p in uniq if p.get("is_reply"))
span = f"{ts(uniq[-1]['created_at'])}  →  {ts(uniq[0]['created_at'])}" if uniq else ""

# clean JSON
json.dump(uniq, open("/Users/markues/Downloads/大道无形我有型_posts.json","w",encoding="utf-8"),
          ensure_ascii=False, indent=2)

# readable text
with open("/Users/markues/Downloads/大道无形我有型_posts.txt","w",encoding="utf-8") as f:
    f.write("大道无形我有型 (段永平) — 雪球帖子/回复\n")
    f.write(f"https://xueqiu.com/u/1247347556\n")
    f.write(f"共 {len(uniq)} 条 | 其中回复他人 {replies} 条 | 时间跨度: {span}\n")
    f.write("="*72 + "\n\n")
    for p in uniq:
        f.write(f"【{ts(p['created_at'])}】 赞{p.get('like_count',0)} 评论{p.get('reply_count',0)} 转发{p.get('retweet_count',0)}\n")
        ctx = p.get("ctx")
        if ctx:
            f.write(f"  ↳ 回复 @{ctx.get('author')}：\n")
            orig = (ctx.get('text') or '')[:600]
            for line in orig.splitlines():
                f.write(f"     │ {line}\n")
            if ctx.get('url'):
                f.write(f"     │ https://xueqiu.com{ctx['url']}\n")
        f.write((p.get("text") or "") + "\n")
        if p.get("url"):
            f.write(f"https://xueqiu.com{p['url']}\n")
        f.write("\n" + "-"*72 + "\n\n")

print(f"posts: {len(uniq)}  replies-to-others: {replies}")
print(f"span: {span}")
print("wrote: 大道无形我有型_posts.json / .txt")
