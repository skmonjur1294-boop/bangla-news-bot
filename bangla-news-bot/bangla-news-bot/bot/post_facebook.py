"""
Upload the rendered video to a Facebook Page using Meta's official Graph API.

Needs two environment variables (saved as GitHub Secrets):
    FB_PAGE_ID      - numeric ID of your Facebook Page
    FB_PAGE_TOKEN   - long-lived Page access token (pages_manage_posts permission)

Usage:
    python bot/post_facebook.py content/2026-11-12.json build/2026-11-12.mp4
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

API = os.environ.get("FB_API_VERSION", "v23.0")
ROOT = Path(__file__).resolve().parent.parent


def fail(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def main():
    content, video = Path(sys.argv[1]), Path(sys.argv[2])
    page_id = os.environ.get("FB_PAGE_ID")
    token = os.environ.get("FB_PAGE_TOKEN")
    if not page_id or not token:
        fail("FB_PAGE_ID or FB_PAGE_TOKEN secret is missing")

    data = json.loads(content.read_text(encoding="utf-8"))
    date = data["date"]
    log = ROOT / "posted" / f"{date}-facebook.json"
    if log.exists() and os.environ.get("FORCE_POST") != "true":
        print(f"Already posted for {date} (see {log}); skipping. Set FORCE_POST=true to post again.")
        return

    title = f"{data.get('title', 'দৈনিক সংবাদ বুলেটিন')} – {data.get('date_bn', date)}"
    caption = data.get("caption") or title
    caption += "\n\n(এই ভিডিওতে AI ভয়েস ব্যবহার করা হয়েছে)"

    # quick token check gives a clear error instead of a failed upload
    r = requests.get(f"https://graph.facebook.com/{API}/{page_id}",
                     params={"fields": "name", "access_token": token}, timeout=30)
    if r.status_code != 200:
        fail(f"token/page check failed: {r.text}")
    print(f"Posting to page: {r.json().get('name')}")

    files = {"source": (video.name, open(video, "rb"), "video/mp4")}
    thumb = video.with_name(f"{video.stem}-thumb.png")
    if thumb.exists():
        files["thumb"] = (thumb.name, open(thumb, "rb"), "image/png")

    for attempt in range(3):
        r = requests.post(
            f"https://graph-video.facebook.com/{API}/{page_id}/videos",
            data={"title": title, "description": caption, "access_token": token, "published": "true"},
            files=files, timeout=900)
        if r.status_code == 200:
            break
        print(f"upload attempt {attempt+1} failed: {r.text}")
        time.sleep(20)
        for f in files.values():
            f[1].seek(0)
    else:
        fail("upload failed 3 times")

    vid = r.json()["id"]
    url = f"https://www.facebook.com/{page_id}/videos/{vid}"
    print(f"Uploaded video id {vid}: {url}")
    log.parent.mkdir(exist_ok=True)
    log.write_text(json.dumps({"date": date, "video_id": vid, "url": url,
                               "posted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                              ensure_ascii=False, indent=2))
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"url={url}\n")


if __name__ == "__main__":
    main()
