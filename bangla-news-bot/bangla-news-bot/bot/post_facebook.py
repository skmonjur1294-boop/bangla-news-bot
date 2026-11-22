"""
Upload the rendered video to a Facebook Page using Meta's official Graph API.

By default the short vertical video is published as a Facebook REEL, because Reels are
shown to people who do not follow the Page yet (normal Page videos mostly reach followers).
If the Reel upload fails for any reason, it falls back to a normal Page video.

Needs two environment variables (saved as GitHub Secrets):
    FB_PAGE_ID      - numeric ID of your Facebook Page
    FB_PAGE_TOKEN   - long-lived Page access token (pages_manage_posts, pages_read_engagement;
                      pages_manage_engagement lets the bot put the source links in the first comment)
Optional:
    FB_POST_MODE    - "reel" (default) or "video"

Usage:
    python bot/post_facebook.py content/2026-11-22-3.json build/2026-11-22-3-reel.mp4
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

API = os.environ.get("FB_API_VERSION", "v23.0")
GRAPH = f"https://graph.facebook.com/{API}"
ROOT = Path(__file__).resolve().parent.parent
HASHTAGS = "#ইতালি #প্রবাসী #বাংলাদেশ #Italia #Bangladesh #ProbashiNews #reels"


def fail(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def build_texts(data):
    """Return (caption, sources_comment). Caption leads with the hook, links go to a comment."""
    title = data.get("title", "সংবাদ বুলেটিন")
    items = data.get("items", [])
    hook = data.get("hook") or (items[0]["headline"] if items else title)
    raw = data.get("caption", "")
    body, _, rest = raw.partition("\nসূত্র:\n")
    lines = [l for l in body.splitlines() if l.strip()]
    story_lines = [l for l in lines[2:]] if len(lines) > 2 else \
        [f"{it.get('emoji','📰')} {it['headline']}" for it in items]
    urls = [l.strip() for l in rest.splitlines() if l.strip().startswith("http")]
    tags = " ".join(w for l in rest.splitlines() for w in l.split() if w.startswith("#"))
    extra = " ".join(t for t in tags.split() if t not in HASHTAGS.split())

    caption = (f"🔴 {hook}\n\n"
               f"📰 {title} · {data.get('date_bn', data['date'])}\n"
               + "\n".join(story_lines) +
               "\n\n💬 আপনি ইতালির কোন শহরে থাকেন? কমেন্টে লিখুন, আপনার শহরের খবরও জানাব।"
               "\n🔁 যে বন্ধুর কাজে লাগবে তাকে শেয়ার করুন।"
               + ("\n🔗 সব খবরের সূত্র প্রথম কমেন্টে।" if urls else "") +
               f"\n\n{HASHTAGS} {extra}".rstrip() +
               "\n\n(এই ভিডিওতে AI ভয়েস ব্যবহার করা হয়েছে)")
    sources = ("📌 আজকের খবরের সূত্র:\n" + "\n".join(urls)) if urls else ""
    return caption, sources


def post_reel(page_id, token, video, caption):
    r = requests.post(f"{GRAPH}/{page_id}/video_reels",
                      data={"upload_phase": "start", "access_token": token}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"reel start failed: {r.text}")
    vid = r.json()["video_id"]
    size = video.stat().st_size
    with open(video, "rb") as f:
        r = requests.post(f"https://rupload.facebook.com/video-upload/{API}/{vid}",
                          headers={"Authorization": f"OAuth {token}", "offset": "0",
                                   "file_size": str(size)}, data=f, timeout=900)
    if r.status_code != 200 or not r.json().get("success"):
        raise RuntimeError(f"reel upload failed: {r.text}")
    r = requests.post(f"{GRAPH}/{page_id}/video_reels",
                      data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                            "description": caption, "access_token": token}, timeout=120)
    if r.status_code != 200 or not r.json().get("success"):
        raise RuntimeError(f"reel publish failed: {r.text}")
    # wait until Facebook has processed it (so the comment lands on a live post)
    for _ in range(30):
        s = requests.get(f"{GRAPH}/{vid}", params={"fields": "status", "access_token": token},
                         timeout=30).json().get("status", {})
        state = s.get("video_status")
        print(f"  reel status: {state}")
        if state in ("ready", "published") or s.get("publishing_phase", {}).get("status") == "complete":
            break
        if state == "error":
            raise RuntimeError(f"reel processing error: {s}")
        time.sleep(10)
    return vid, f"https://www.facebook.com/reel/{vid}"


def post_video(page_id, token, video, title, caption):
    files = {"source": (video.name, open(video, "rb"), "video/mp4")}
    thumb = video.with_name(f"{video.stem}-thumb.png")
    if thumb.exists():
        files["thumb"] = (thumb.name, open(thumb, "rb"), "image/png")
    for attempt in range(3):
        r = requests.post(f"https://graph-video.facebook.com/{API}/{page_id}/videos",
                          data={"title": title, "description": caption, "access_token": token,
                                "published": "true"}, files=files, timeout=900)
        if r.status_code == 200:
            vid = r.json()["id"]
            return vid, f"https://www.facebook.com/{page_id}/videos/{vid}"
        print(f"upload attempt {attempt+1} failed: {r.text}")
        time.sleep(20)
        for f in files.values():
            f[1].seek(0)
    fail("upload failed 3 times")


def add_sources(vid, token, sources, caption):
    """Put the source links in the first comment; if not allowed, add them to the description."""
    if not sources:
        return
    r = requests.post(f"{GRAPH}/{vid}/comments", data={"message": sources, "access_token": token}, timeout=60)
    if r.status_code == 200:
        print("sources posted as first comment")
        return
    print(f"comment failed ({r.text[:200]}); adding sources to the description instead")
    desc = caption.replace("\n🔗 সব খবরের সূত্র প্রথম কমেন্টে।", "") + "\n\n" + sources
    r = requests.post(f"{GRAPH}/{vid}", data={"description": desc, "access_token": token}, timeout=60)
    if r.status_code != 200:
        print(f"WARNING: could not add sources: {r.text[:200]}")


def main():
    content, video = Path(sys.argv[1]), Path(sys.argv[2])
    page_id = os.environ.get("FB_PAGE_ID")
    token = os.environ.get("FB_PAGE_TOKEN")
    if not page_id or not token:
        fail("FB_PAGE_ID or FB_PAGE_TOKEN secret is missing")

    data = json.loads(content.read_text(encoding="utf-8"))
    post_id = content.stem
    log = ROOT / "posted" / f"{post_id}-facebook.json"
    if log.exists() and os.environ.get("FORCE_POST") != "true":
        print(f"Already posted {post_id} (see {log}); skipping. Set FORCE_POST=true to post again.")
        return

    title = f"{data.get('title', 'সংবাদ বুলেটিন')} – {data.get('date_bn', data['date'])}"
    caption, sources = build_texts(data)

    r = requests.get(f"{GRAPH}/{page_id}", params={"fields": "name", "access_token": token}, timeout=30)
    if r.status_code != 200:
        fail(f"token/page check failed: {r.text}")
    print(f"Posting to page: {r.json().get('name')}")

    kind = "video"
    if os.environ.get("FB_POST_MODE", "reel") == "reel":
        try:
            vid, url = post_reel(page_id, token, video, caption)
            kind = "reel"
        except Exception as e:
            print(f"Reel failed, posting as normal video instead: {e}")
            vid, url = post_video(page_id, token, video, title, caption)
    else:
        vid, url = post_video(page_id, token, video, title, caption)
    print(f"Uploaded {kind} {vid}: {url}")
    add_sources(vid, token, sources, caption)

    log.parent.mkdir(exist_ok=True)
    log.write_text(json.dumps({"date": data["date"], "post": post_id, "type": kind, "video_id": vid,
                               "url": url, "posted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                              ensure_ascii=False, indent=2))
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"url={url}\n")


if __name__ == "__main__":
    main()
