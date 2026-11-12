"""
Turn a daily bulletin JSON (content/YYYY-MM-DD.json) into a vertical news video.

Each spoken sentence becomes one "frame": the news card for that item plus the
sentence shown as a subtitle. Audio for every sentence is generated separately,
so subtitles are always in sync with the voice.

Usage:
    python bot/render.py content/2026-11-12.json            # real voice (edge-tts)
    python bot/render.py content/2026-11-12.json --dry-run  # silent audio, for testing
"""
import argparse
import asyncio
import html
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
W, H = 1080, 1920
VOICE = os.environ.get("TTS_VOICE", "bn-BD-PradeepNeural")  # or bn-BD-NabanitaNeural (female)
RATE = os.environ.get("TTS_RATE", "+0%")
PAUSE = 0.35  # seconds of silence after each sentence

# ---------------------------------------------------------------- page design
CSS = f"""
@font-face {{ font-family: Bn; src: url('file://{FONTS}/NotoSansBengali.ttf'); font-weight: 100 900; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
html,body {{ width:{W}px; height:{H}px; overflow:hidden; }}
body {{ font-family: Bn, sans-serif; color:#f4f1ea;
  background: radial-gradient(1200px 900px at 80% -10%, #1f6f5c 0%, transparent 60%),
              radial-gradient(900px 900px at -10% 110%, #7a1f2b 0%, transparent 55%),
              #0d1b2a; display:flex; flex-direction:column; }}
.top {{ display:flex; justify-content:space-between; align-items:center; padding:70px 70px 0; }}
.brand {{ font-weight:700; font-size:44px; letter-spacing:.5px; }}
.brand small {{ display:block; font-weight:400; font-size:28px; opacity:.75; }}
.flag {{ width:110px; height:66px; border-radius:8px; background:#006a4e; position:relative; box-shadow:0 4px 20px rgba(0,0,0,.4); }}
.flag:after {{ content:''; position:absolute; width:40px; height:40px; border-radius:50%; background:#f42a41; left:40px; top:13px; }}
.card {{ margin:80px 50px 0; padding:60px 56px 64px; background:rgba(255,255,255,.07);
  border:1px solid rgba(255,255,255,.14); border-radius:36px; }}
.tag {{ display:inline-block; font-size:32px; font-weight:700; padding:8px 26px; border-radius:40px;
  background:#e9b949; color:#1a1a1a; margin-bottom:34px; }}
.num {{ font-size:34px; opacity:.7; margin-left:16px; }}
.emoji {{ font-family:'Noto Color Emoji'; font-size:96px; line-height:1; margin-bottom:24px; }}
h1 {{ font-size:76px; line-height:1.3; font-weight:700; margin-bottom:34px; }}
ul {{ list-style:none; }}
li {{ font-size:48px; line-height:1.45; margin:0 0 20px; padding-left:46px; position:relative; }}
li:before {{ content:''; position:absolute; left:6px; top:28px; width:16px; height:16px; border-radius:50%; background:#e9b949; }}
.src {{ font-size:32px; opacity:.6; margin-top:26px; }}
.spacer {{ flex:1; }}
.sub {{ margin:0 50px 90px; padding:34px 40px; background:rgba(0,0,0,.62); border-radius:28px;
  font-size:52px; line-height:1.45; font-weight:700; text-align:center; border-left:8px solid #e9b949; }}
.big {{ text-align:center; margin-top:200px; padding:0 70px; }}
.big .emoji {{ font-size:140px; }}
.big h1 {{ font-size:84px; }}
.big p {{ font-size:46px; opacity:.85; line-height:1.5; }}
.arabic {{ font-family: 'Noto Naskh Arabic', 'Noto Sans Arabic', serif; direction:rtl; font-size:54px; line-height:1.7; margin-bottom:28px; color:#e9b949; }}
.quote {{ font-size:52px; line-height:1.5; }}
.ref {{ font-size:32px; opacity:.75; margin-top:26px; }}
.ai {{ position:absolute; right:40px; bottom:28px; font-size:22px; opacity:.45; }}
"""

def esc(s):
    return html.escape(s or "")

def header(data):
    return f"""<div class="top"><div class="brand">{esc(data.get('title','দৈনিক সংবাদ বুলেটিন'))}
      <small>{esc(data.get('date_bn',''))}</small></div><div class="flag"></div></div>"""

def page(body, subtitle):
    sub = f'<div class="sub">{esc(subtitle)}</div>' if subtitle else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head>
      <body>{body}<div class="spacer"></div>{sub}<div class="ai">AI ভয়েস</div></body></html>"""

def build_segments(data):
    """Return list of (html_body, sentence) pairs in speaking order."""
    segs = []
    hdr = header(data)

    intro_body = hdr + f"""<div class="big"><div class="emoji">📰</div>
        <h1>{esc(data.get('title','দৈনিক সংবাদ বুলেটিন'))}</h1>
        <p>{esc(data.get('subtitle','ইতালি প্রবাসী বাংলাদেশিদের জন্য প্রতিদিনের খবর'))}</p></div>"""
    for s in data.get("intro", []):
        segs.append((intro_body, s))

    items = data.get("items", [])
    for i, it in enumerate(items, 1):
        pts = "".join(f"<li>{esc(p)}</li>" for p in it.get("points", []))
        src = f'<div class="src">সূত্র: {esc(it["source"])}</div>' if it.get("source") else ""
        body = hdr + f"""<div class="card">
            <span class="tag">{esc(it.get('tag','খবর'))}</span><span class="num">{i}/{len(items)}</span>
            <div class="emoji">{esc(it.get('emoji','📰'))}</div>
            <h1>{esc(it['headline'])}</h1><ul>{pts}</ul>{src}</div>"""
        for s in it.get("narration", []):
            segs.append((body, s))

    iman = data.get("iman")
    if iman:
        ar = f'<div class="arabic">{esc(iman["arabic"])}</div>' if iman.get("arabic") else ""
        body = hdr + f"""<div class="card"><span class="tag">ঈমানী বার্তা</span>
            <div class="emoji">🌙</div>
            {ar}<div class="quote">{esc(iman.get('text',''))}</div>
            <div class="ref">{esc(iman.get('reference',''))}</div></div>"""
        for s in iman.get("narration", []):
            segs.append((body, s))

    outro_body = hdr + f"""<div class="big"><div class="emoji">🙏</div>
        <h1>{esc(data.get('outro_title','পেজটি ফলো করুন'))}</h1>
        <p>{esc(data.get('outro_text','প্রতিদিনের গুরুত্বপূর্ণ খবর পেতে সাথে থাকুন'))}</p></div>"""
    for s in data.get("outro", []):
        segs.append((outro_body, s))
    return segs

# ---------------------------------------------------------------- helpers
def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-3000:])
        raise SystemExit(f"command failed: {' '.join(cmd[:3])} ...")
    return r.stdout

def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.strip())

async def tts_edge(text, out):
    import edge_tts
    for attempt in range(4):
        try:
            await edge_tts.Communicate(text, VOICE, rate=RATE).save(str(out))
            if out.exists() and out.stat().st_size > 1000:
                return True
        except Exception as e:  # network hiccup: retry
            print(f"  edge-tts retry {attempt+1}: {e}")
            await asyncio.sleep(3 * (attempt + 1))
    return False

def tts_gtts(text, out):
    from gtts import gTTS
    gTTS(text=text, lang="bn").save(str(out))

def make_audio(text, out, dry_run):
    if dry_run:
        secs = max(2.0, len(text) / 13.0)  # rough Bengali speaking speed
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{secs:.2f}", str(out)])
        return
    if not asyncio.run(tts_edge(text, out)):
        print("  edge-tts failed, falling back to gTTS")
        tts_gtts(text, out)

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("content")
    ap.add_argument("--out", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-segments", type=int, default=0, help="only render first N sentences (testing)")
    a = ap.parse_args()

    data = json.loads(Path(a.content).read_text(encoding="utf-8"))
    date = data["date"]
    work = ROOT / "build" / date
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    out = Path(a.out or ROOT / "build" / f"{date}.mp4")

    segs = build_segments(data)
    if a.max_segments:
        segs = segs[: a.max_segments]
    print(f"{len(segs)} sentences to render")

    # 1) images (one browser for all frames)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        for i, (body, sent) in enumerate(segs):
            pg.set_content(page(body, sent), wait_until="load")
            pg.evaluate("document.fonts.ready")
            pg.screenshot(path=str(work / f"{i:03d}.png"))
        b.close()

    # 2) audio + 3) one clip per sentence
    clips = []
    for i, (_, sent) in enumerate(segs):
        print(f"  [{i+1}/{len(segs)}] {sent[:50]}")
        mp3 = work / f"{i:03d}.mp3"
        make_audio(sent, mp3, a.dry_run)
        d = duration(mp3) + PAUSE
        clip = work / f"{i:03d}.mp4"
        run(["ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-i", str(work / f"{i:03d}.png"),
             "-i", str(mp3), "-af", f"apad=pad_dur={PAUSE}", "-t", f"{d:.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(clip)])
        clips.append(clip)

    # 4) join
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{c}'\n" for c in clips))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
         "-movflags", "+faststart", str(out)])
    # thumbnail = first item card
    first_item = next((i for i, (b, _) in enumerate(segs) if 'class="card"' in b), 0)
    shutil.copy(work / f"{first_item:03d}.png", out.with_name(f"{out.stem}-thumb.png"))
    print(f"done: {out} ({duration(out):.0f} s)")

if __name__ == "__main__":
    main()
