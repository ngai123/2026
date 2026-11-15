#!/usr/bin/env python3
"""Q&A / search over 段永平 corpus.
Usage:
  python3 search.py 能力圈              # posts containing a keyword (top by likes)
  python3 search.py "护城河" --date     # sort chronologically instead of by likes
  python3 search.py "苹果" --n 30       # show 30 results
"""
import json,sys,datetime,os
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d=json.load(open(os.path.join(BASE,'大道无形我有型_posts.json'),encoding='utf-8'))
args=[a for a in sys.argv[1:]]
by_date='--date' in args; args=[a for a in args if a!='--date']
n=20
if '--n' in args:
    i=args.index('--n'); n=int(args[i+1]); del args[i:i+2]
kw=args[0] if args else ''
def ts(ms):return datetime.datetime.fromtimestamp(ms/1000).strftime('%Y-%m-%d') if ms else ''
hits=[p for p in d if kw in (p.get('text') or '')]
hits.sort(key=lambda p:(p.get('created_at') if by_date else (p.get('like_count') or 0)), reverse=True)
print(f'"{kw}": {len(hits)} 条  (显示前{min(n,len(hits))})\n')
for p in hits[:n]:
    print(f"[{ts(p['created_at'])}] 赞{p.get('like_count',0)}")
    c=p.get('ctx')
    if c and c.get('text'): print(f"  ↳@{c.get('author')}: {c['text'][:150]}")
    print("  "+(p.get('text') or '').replace(chr(10),' ')[:400])
    print(f"  https://xueqiu.com{p.get('url','')}\n")
