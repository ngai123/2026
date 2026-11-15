#!/usr/bin/env python3
"""Slice 段永平 corpus into per-company and per-theme files for analysis."""
import json, datetime, os, re
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d=json.load(open(os.path.join(BASE,'大道无形我有型_posts.json'),encoding='utf-8'))
d.sort(key=lambda p:p.get('created_at') or 0)  # chronological for case studies
def ts(ms):return datetime.datetime.fromtimestamp(ms/1000).strftime('%Y-%m-%d %H:%M') if ms else ''

def write_slice(path, posts, chronological=True):
    with open(path,'w',encoding='utf-8') as f:
        f.write(f"共 {len(posts)} 条\n"+"="*70+"\n\n")
        for p in posts:
            f.write(f"【{ts(p['created_at'])}】 赞{p.get('like_count',0)} 评论{p.get('reply_count',0)}\n")
            ctx=p.get('ctx')
            if ctx and ctx.get('text'):
                f.write(f"  ↳回复@{ctx.get('author')}: {ctx['text'][:300]}\n")
            f.write((p.get('text') or '')+"\n")
            if p.get('url'): f.write(f"https://xueqiu.com{p['url']}\n")
            f.write("\n")

companies={'苹果':['苹果','AAPL','Apple','iphone','iPhone'],'茅台':['茅台','SH600519'],
 '腾讯':['腾讯','TCEHY','00700'],'拼多多':['拼多多','PDD'],'网易':['网易','NTES'],
 '巴菲特伯克希尔':['巴菲特','伯克希尔','BRK'],'泡泡玛特':['泡泡玛特','09992'],'特斯拉':['特斯拉','TSLA']}
for name,kw in companies.items():
    sel=[p for p in d if any(k in (p.get('text','')+' '+(p.get('ctx',{}) or {}).get('text','')) for k in kw)]
    write_slice(os.path.join(BASE,'analysis/companies',f'{name}.txt'), sel)

themes={'本分':['本分'],'能力圈':['能力圈','不懂不做','看懂'],'商业模式':['商业模式','护城河','差异化'],
 '企业文化':['企业文化','使命','价值观'],'平常心_stopdoing':['平常心','stop doing','做对的事','改正'],
 '估值买卖':['内在价值','安全边际','便宜','贵','现金流','折现'],'分红回购':['分红','回购'],
 '长期投资':['长期','十年','拿住','复利']}
for name,kw in themes.items():
    sel=[p for p in d if any(k in (p.get('text','')) for k in kw)]
    write_slice(os.path.join(BASE,'analysis/themes',f'{name}.txt'), sel)

print("companies:")
for f in sorted(os.listdir(os.path.join(BASE,'analysis/companies'))):
    n=sum(1 for _ in open(os.path.join(BASE,'analysis/companies',f),encoding='utf-8'))
    print(f"  {f}")
print("themes:")
for f in sorted(os.listdir(os.path.join(BASE,'analysis/themes'))):
    print(f"  {f}")
