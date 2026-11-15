#!/usr/bin/env python3
"""
Full-footprint scraper for a Xueqiu user.
Default target: 大道无形我有型 (段永平 / Duan Yongping), user_id=1247347556

Captures EVERYTHING reachable:
  - profile (bio, followers, etc.)
  - full timeline: own posts + replies to others, untruncated text
  - context for each reply: the original post he is responding to (retweeted_status)
  - comment threads under each of his posts
  - his public portfolios (组合) / followed stocks

AUTH: Xueqiu requires a logged-in session cookie + passes its WAF this way.
  Put your logged-in Cookie header in cookie.txt (same folder) OR set COOKIE env var.

Usage:
  python3 xueqiu_scrape.py                      # default user, everything
  python3 xueqiu_scrape.py 1247347556           # specific user
  python3 xueqiu_scrape.py 1247347556 --no-comments   # skip per-post comment threads (much faster)
  python3 xueqiu_scrape.py 1247347556 --max-pages 10
"""
import os
import sys
import json
import time
import re
import html
import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

SLEEP = 2.0          # seconds between requests (anti-scraping politeness)
COMMENT_SLEEP = 1.0  # seconds between comment-thread fetches


# ---------------------------------------------------------------- session
def load_cookie():
    cookie = os.environ.get("COOKIE", "").strip()
    if not cookie:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookie.txt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cookie = f.read().strip()
    if not cookie:
        sys.exit("ERROR: no cookie. Put your logged-in Xueqiu Cookie header in cookie.txt "
                 "(same folder) or set the COOKIE env var.")
    return cookie


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://xueqiu.com/",
        "Cookie": load_cookie(),
    })
    return s


def clean_text(t):
    if not t:
        return ""
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return t.strip()


def get_json(s, url, params=None, label=""):
    try:
        r = s.get(url, params=params, timeout=20)
    except requests.RequestException as e:
        print(f"  ! request error {label}: {e}")
        return None
    if r.status_code != 200:
        print(f"  ! HTTP {r.status_code} {label}: {r.text[:150]}")
        return None
    txt = r.text.lstrip()
    if txt.startswith("<"):   # WAF / HTML challenge instead of JSON
        print(f"  ! WAF/HTML (not JSON) {label}. Cookie likely expired or not logged in.")
        return None
    try:
        return r.json()
    except json.JSONDecodeError:
        print(f"  ! bad JSON {label}: {r.text[:150]}")
        return None


# ---------------------------------------------------------------- profile
def fetch_profile(s, uid):
    print("Fetching profile ...")
    d = get_json(s, "https://xueqiu.com/users/show.json",
                 {"id": uid}, "profile")
    if not d:
        return {}
    return {
        "id": d.get("id"),
        "screen_name": d.get("screen_name"),
        "description": clean_text(d.get("description")),
        "followers_count": d.get("followers_count"),
        "friends_count": d.get("friends_count"),
        "status_count": d.get("status_count"),
        "province": d.get("province"),
        "city": d.get("city"),
        "verified": d.get("verified"),
        "verified_description": d.get("verified_description"),
        "profile_url": f"https://xueqiu.com/u/{uid}",
    }


# ---------------------------------------------------------------- portfolios
def fetch_portfolios(s, uid):
    print("Fetching portfolios (组合) ...")
    d = get_json(s, "https://xueqiu.com/cubes/list.json",
                 {"user_id": uid}, "portfolios")
    if not d:
        return []
    out = []
    for c in d.get("list", []):
        out.append({
            "name": c.get("name"),
            "symbol": c.get("symbol"),
            "net_value": c.get("net_value"),
            "daily_gain": c.get("daily_gain"),
            "monthly_gain": c.get("monthly_gain"),
            "total_gain": c.get("total_gain"),
            "url": f"https://xueqiu.com/P/{c.get('symbol')}" if c.get("symbol") else None,
        })
    return out


# ---------------------------------------------------------------- comments
def fetch_comments(s, status_id):
    """All comment-thread replies under one status."""
    comments, page, maxp = [], 1, 1
    while page <= maxp:
        d = get_json(s, "https://xueqiu.com/statuses/comments.json",
                     {"id": status_id, "count": 50, "page": page,
                      "reply": "true", "asc": "false", "type": "status"},
                     f"comments(status {status_id} p{page})")
        if not d:
            break
        for c in d.get("comments", []):
            u = c.get("user") or {}
            comments.append({
                "id": c.get("id"),
                "user": u.get("screen_name"),
                "user_id": u.get("id"),
                "created_at": c.get("created_at"),
                "text": clean_text(c.get("text")),
                "like_count": c.get("like_count"),
            })
        maxp = d.get("maxPage", 1) or 1
        page += 1
        time.sleep(COMMENT_SLEEP)
    return comments


# ---------------------------------------------------------------- timeline
def parse_retweet(st):
    """The original post this status is replying to / quoting (the CONTEXT)."""
    rt = st.get("retweeted_status")
    if not rt:
        return None
    u = rt.get("user") or {}
    return {
        "orig_id": rt.get("id"),
        "orig_author": u.get("screen_name"),
        "orig_author_id": u.get("id"),
        "orig_created_at": rt.get("created_at"),
        "orig_title": clean_text(rt.get("title")),
        "orig_text": clean_text(rt.get("text") or rt.get("description")),
        "orig_url": "https://xueqiu.com" + rt.get("target", "") if rt.get("target") else None,
    }


def fetch_timeline(s, uid, max_pages, want_comments):
    print("Fetching timeline (posts + replies) ...")
    posts, page, maxp = [], 1, None
    while page <= max_pages:
        d = get_json(s, "https://xueqiu.com/v4/statuses/user_timeline.json",
                     {"user_id": uid, "page": page}, f"timeline p{page}")
        if not d:
            print("  Stopping timeline (no data / blocked).")
            break
        statuses = d.get("statuses", [])
        if not statuses:
            print("  No more posts.")
            break
        for st in statuses:
            rec = {
                "id": st.get("id"),
                "created_at": st.get("created_at"),
                "title": clean_text(st.get("title")),
                "text": clean_text(st.get("text") or st.get("description")),
                "is_reply_or_quote": bool(st.get("retweeted_status")),
                "context_original_post": parse_retweet(st),
                "retweet_count": st.get("retweet_count"),
                "reply_count": st.get("reply_count"),
                "fav_count": st.get("fav_count"),
                "like_count": st.get("like_count"),
                "view_count": st.get("view_count"),
                "url": "https://xueqiu.com" + st.get("target", "") if st.get("target") else None,
                "comments": [],
            }
            if want_comments and (st.get("reply_count") or 0) > 0:
                rec["comments"] = fetch_comments(s, st.get("id"))
            posts.append(rec)
        maxp = d.get("maxPage")
        print(f"  page {page}: +{len(statuses)} (total {len(posts)}), maxPage={maxp}")
        if maxp and page >= maxp:
            print("  Reached last page.")
            break
        page += 1
        time.sleep(SLEEP)
    return posts


# ---------------------------------------------------------------- output
def write_outputs(uid, profile, portfolios, posts):
    bundle = {"profile": profile, "portfolios": portfolios,
              "post_count": len(posts), "posts": posts}
    jpath = f"xueqiu_{uid}_full.json"
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)
    print(f"\nSaved structured bundle -> {jpath}")

    tpath = f"xueqiu_{uid}_full.txt"
    with open(tpath, "w", encoding="utf-8") as f:
        if profile:
            f.write(f"# {profile.get('screen_name')} ({profile.get('profile_url')})\n")
            f.write(f"{profile.get('description','')}\n")
            f.write(f"followers={profile.get('followers_count')} posts={profile.get('status_count')}\n\n")
        for p in posts:
            f.write("=" * 70 + "\n")
            f.write(f"{p['created_at']} | id={p['id']} | likes={p['like_count']} replies={p['reply_count']}\n")
            ctx = p["context_original_post"]
            if ctx:
                f.write(f"[REPLY TO @{ctx['orig_author']}]\n")
                f.write(f"  original: {ctx['orig_text'][:500]}\n")
                if ctx['orig_url']:
                    f.write(f"  orig_url: {ctx['orig_url']}\n")
                f.write("  ---\n")
            if p["title"]:
                f.write(p["title"] + "\n")
            f.write((p["text"] or "") + "\n")
            if p["url"]:
                f.write(p["url"] + "\n")
            if p["comments"]:
                f.write(f"  -- {len(p['comments'])} comments --\n")
                for c in p["comments"]:
                    f.write(f"    @{c['user']}: {c['text']}\n")
            f.write("\n")
    print(f"Saved readable text   -> {tpath}")


# ---------------------------------------------------------------- main
def main():
    args = [a for a in sys.argv[1:]]
    uid = "1247347556"
    max_pages = 100000
    want_comments = True
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--no-comments":
            want_comments = False
        elif a == "--max-pages":
            i += 1
            max_pages = int(args[i])
        elif not a.startswith("--"):
            uid = a
        i += 1

    print(f"Target user_id = {uid} | comments={'yes' if want_comments else 'no'} | max_pages={max_pages}\n")
    s = make_session()

    profile = fetch_profile(s, uid)
    time.sleep(SLEEP)
    portfolios = fetch_portfolios(s, uid)
    time.sleep(SLEEP)
    posts = fetch_timeline(s, uid, max_pages, want_comments)

    write_outputs(uid, profile, portfolios, posts)
    print(f"\nDONE. {len(posts)} posts captured.")


if __name__ == "__main__":
    main()
