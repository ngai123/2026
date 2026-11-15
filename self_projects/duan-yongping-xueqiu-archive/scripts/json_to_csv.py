#!/usr/bin/env python3
import json, csv, datetime, os
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d=json.load(open(os.path.join(BASE,'大道无形我有型_posts.json'),encoding='utf-8'))
d.sort(key=lambda p:p.get('created_at') or 0, reverse=True)
def dt(ms):return datetime.datetime.fromtimestamp(ms/1000) if ms else None
out=os.path.join(BASE,'大道无形我有型_posts.csv')
cols=['id','datetime','date','year','month','source','is_reply',
      'reply_to_author','reply_to_text','text',
      'like_count','reply_count','retweet_count','fav_count','view_count','url']
# utf-8-sig => BOM so Excel/Sheets show Chinese correctly
with open(out,'w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=cols)
    w.writeheader()
    for p in d:
        t=dt(p.get('created_at')); ctx=p.get('ctx') or {}
        w.writerow({
            'id':p.get('id'),
            'datetime':t.strftime('%Y-%m-%d %H:%M:%S') if t else '',
            'date':t.strftime('%Y-%m-%d') if t else '',
            'year':t.year if t else '',
            'month':t.strftime('%Y-%m') if t else '',
            'source':p.get('source',''),
            'is_reply':1 if p.get('is_reply') else 0,
            'reply_to_author':ctx.get('author','') or '',
            'reply_to_text':(ctx.get('text','') or '').replace('\n',' '),
            'text':(p.get('text','') or '').replace('\n',' '),
            'like_count':p.get('like_count',0) or 0,
            'reply_count':p.get('reply_count',0) or 0,
            'retweet_count':p.get('retweet_count',0) or 0,
            'fav_count':p.get('fav_count',0) or 0,
            'view_count':p.get('view_count',0) or 0,
            'url':('https://xueqiu.com'+p['url']) if p.get('url') else '',
        })
print('rows:',len(d))
