"""
Turn a bulletin JSON (content/YYYY-MM-DD-N.json) into a vertical 1080x1920 news video.

Two kinds of video:
  --reel   short Facebook Reel (< 90 s): hook -> stories ("short" lines) -> iman line -> follow
  default  full video (daily bulletin, or a "format": "long" detailed story of 3-5 minutes)

What makes it watchable:
  * the first screen is the hook, shown huge and spoken first
  * word-by-word "karaoke" subtitles (the spoken word lights up)
  * a colour theme per story type (alert = red, Bangladesh = green, world = blue ...)
  * a slow push-in on every frame, story progress bars, a soft whoosh between stories
  * optional background music (upload music.mp3 next to requirements.txt), ducked under the voice
  * loudness normalised to social-media level (-14 LUFS)

Usage:
    python bot/render.py content/2026-11-22-3.json --reel
    python bot/render.py content/2026-11-22-3.json            # full video
    python bot/render.py content/2026-11-22-3.json --reel --dry-run   # silent, for testing
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
PAUSE = 0.28  # seconds of silence after each sentence
REEL_MAX = float(os.environ.get("REEL_MAX_SECONDS", "86"))  # Facebook Reels limit is 90 s
MUSIC = Path(os.environ.get("MUSIC_FILE") or next(
    (p for p in (ROOT / "assets" / "music.mp3", ROOT / "music.mp3") if p.exists()), ROOT / "music.mp3"))
MUSIC_VOL = float(os.environ.get("MUSIC_VOLUME", "0.16"))
SFX = os.environ.get("SFX", "on") == "on"
KARAOKE = os.environ.get("KARAOKE", "on") == "on"

# ---------------------------------------------------------------- themes
THEMES = [  # (words in the tag, accent colour, text colour on accent, hook label)
    (("সতর্ক", "জরুরি", "ব্রেকিং", "শোক", "দুর্ঘটনা", "হামলা", "অপরাধ"), "#e63946", "#fff", "🔴 জরুরি খবর"),
    (("কমিউনিটি", "প্রবাসী"), "#f4a261", "#1a1a1a", "🔴 প্রবাসী কমিউনিটি"),
    (("বাংলাদেশ",), "#2a9d6f", "#fff", "🇧🇩 বাংলাদেশ"),
    (("মধ্যপ্রাচ্য", "মুসলিম", "ফিলিস্তিন", "গাজা", "ভারত", "বিশ্ব", "ইসলাম"), "#4f7cff", "#fff", "🌍 মুসলিম বিশ্ব"),
    (("টাকা", "কাজ", "ধর্মঘট", "যাতায়াত", "আবহাওয়া"), "#3fb8c9", "#0d1b2a", "🇮🇹 ইতালি"),
]
DEFAULT_THEME = ("#e9b949", "#1a1a1a", "🇮🇹 ইতালি প্রবাসীদের জন্য")
IMAN_THEME = ("#e9b949", "#1a1a1a", "🌙 ঈমানী বার্তা")


def theme(tag):
    tag = tag or ""
    for words, acc, ink, label in THEMES:
        if any(w in tag for w in words):
            return acc, ink, label
    return DEFAULT_THEME


# ---------------------------------------------------------------- page design
CSS = f"""
@font-face {{ font-family: Bn; src: url('file://{FONTS}/NotoSansBengali.ttf'); font-weight: 100 900; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
html,body {{ width:{W}px; height:{H}px; overflow:hidden; }}
body {{ font-family: Bn, sans-serif; color:#f4f1ea; position:relative;
  background: radial-gradient(1100px 900px at 85% -10%, color-mix(in srgb, var(--acc) 45%, transparent) 0%, transparent 60%),
              radial-gradient(900px 900px at -10% 110%, #7a1f2b 0%, transparent 55%),
              #0d1b2a; display:flex; flex-direction:column; }}
/* everything important stays inside the Reels safe area: not under the bottom caption, not under the right-hand buttons */
.top {{ display:flex; justify-content:space-between; align-items:center; padding:110px 150px 0 60px; }}
.brand {{ font-weight:700; font-size:40px; letter-spacing:.5px; }}
.brand small {{ display:block; font-weight:400; font-size:28px; opacity:.75; }}
.flag {{ width:100px; height:60px; border-radius:8px; background:#006a4e; position:relative; box-shadow:0 4px 20px rgba(0,0,0,.4); }}
.flag:after {{ content:''; position:absolute; width:36px; height:36px; border-radius:50%; background:#f42a41; left:36px; top:12px; }}
.card {{ margin:46px 150px 0 50px; padding:44px 44px 48px; background:rgba(255,255,255,.07);
  border:1px solid rgba(255,255,255,.14); border-left:10px solid var(--acc); border-radius:32px; }}
.tag {{ display:inline-block; font-size:32px; font-weight:700; padding:8px 26px; border-radius:40px;
  background:var(--acc); color:var(--ink); margin-bottom:28px; }}
.num {{ font-size:32px; opacity:.7; margin-left:16px; }}
.emoji {{ font-family:'Noto Color Emoji'; font-size:96px; line-height:1; margin-bottom:22px; }}
h1 {{ font-size:66px; line-height:1.3; font-weight:700; margin-bottom:28px; }}
ul {{ list-style:none; }}
li {{ font-size:42px; line-height:1.45; margin:0 0 16px; padding-left:44px; position:relative; }}
li:before {{ content:''; position:absolute; left:6px; top:25px; width:16px; height:16px; border-radius:50%; background:var(--acc); }}
.src {{ font-size:30px; opacity:.6; margin-top:20px; }}
.spacer {{ flex:1; }}
.sub {{ margin:0 150px 430px 50px; padding:30px 36px; background:rgba(0,0,0,.70); border-radius:26px;
  font-size:52px; line-height:1.45; font-weight:700; text-align:center; border-left:8px solid var(--acc); }}
.sub span {{ opacity:.42; }}
.sub span.said {{ opacity:1; }}
.sub span.now {{ opacity:1; color:var(--acc); }}
.big {{ text-align:center; margin-top:170px; padding:0 150px 0 70px; }}
.big .emoji {{ font-size:140px; }}
.big h1 {{ font-size:84px; }}
.big p {{ font-size:46px; opacity:.85; line-height:1.5; }}
.arabic {{ font-family: 'Noto Naskh Arabic', 'Noto Sans Arabic', serif; direction:rtl; font-size:52px; line-height:1.7; margin-bottom:24px; color:var(--acc); }}
.quote {{ font-size:50px; line-height:1.5; }}
.ref {{ font-size:30px; opacity:.75; margin-top:22px; }}
.ai {{ position:absolute; right:60px; top:62px; font-size:22px; opacity:.45; }}
.prog {{ position:absolute; top:40px; left:50px; right:50px; display:flex; gap:12px; }}
.prog i {{ flex:1; height:10px; border-radius:6px; background:rgba(255,255,255,.25); }}
.prog i.on {{ background:var(--acc); }}
.hook {{ margin:120px 150px 0 60px; }}
.hook .lbl {{ display:inline-block; background:var(--acc); color:var(--ink); font-size:40px; font-weight:700;
  padding:10px 30px; border-radius:12px; margin-bottom:36px; }}
.hook .emoji {{ font-size:150px; margin-bottom:30px; }}
.hook h1 {{ font-size:104px; line-height:1.3; color:#fff; text-shadow:0 6px 30px rgba(0,0,0,.5); }}
.hook h1 b {{ color:var(--acc); }}
.hook p {{ font-size:44px; margin-top:34px; opacity:.85; }}
"""


def esc(s):
    return html.escape(s or "")


def header(data):
    return f"""<div class="top"><div class="brand">{esc(data.get('title','দৈনিক সংবাদ বুলেটিন'))}
      <small>{esc(data.get('date_bn',''))}</small></div><div class="flag"></div></div>"""


def progress(n, active):
    return '<div class="prog">' + "".join(
        f'<i class="{"on" if k <= active else ""}"></i>' for k in range(1, n + 1)) + "</div>"


def sub_html(words, k):
    """Subtitle with words 0..k-1 already said, word k being said now (k = -1: none yet)."""
    if not words:
        return ""
    if not KARAOKE:
        return f'<div class="sub">{esc(" ".join(words))}</div>'
    parts = []
    for j, w in enumerate(words):
        cls = "now" if j == k else ("said" if j < k else "")
        parts.append(f'<span class="{cls}">{esc(w)}</span>')
    return '<div class="sub">' + " ".join(parts) + "</div>"


def page(body, words, k, acc, ink):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head>
      <body style="--acc:{acc};--ink:{ink}">{body}<div class="spacer"></div>{sub_html(words, k)}
      <div class="ai">AI ভয়েস</div></body></html>"""


# ---------------------------------------------------------------- segments
# a segment = dict(body, text, theme=(acc, ink), story=bool new-story-start, prio, order)

def hook_seg(data, n):
    items = data.get("items", [])
    first = items[0] if items else {}
    acc, ink, label = theme(first.get("tag"))
    title = data.get("title", "সংবাদ বুলেটিন")
    hook = data.get("hook") or first.get("headline") or title
    label = data.get("hook_label") or label
    body = progress(n, 0) + f"""<div class="hook"><span class="lbl">{esc(label)}</span>
        <div class="emoji">{esc(first.get('emoji','📰'))}</div><h1>{esc(hook)}</h1>
        <p>{esc(data.get('date_bn',''))}</p></div>"""
    text = hook if hook.endswith(("।", "?", "!")) else hook + "।"
    return [dict(body=body, text=text, theme=(acc, ink), story=True),
            dict(body=body, text=f"আসসালামু আলাইকুম, শুনুন আজকের {title}।" if data.get("format") != "long"
                 else "আসসালামু আলাইকুম। চলুন বিস্তারিত জেনে নিই।", theme=(acc, ink), story=False)]


def item_body(data, it, i, n, total, show_src=True):
    acc, ink, _ = theme(it.get("tag"))
    pts = "".join(f"<li>{esc(p)}</li>" for p in it.get("points", [])[:4])
    src = f'<div class="src">সূত্র: {esc(it["source"])}</div>' if show_src and it.get("source") else ""
    body = progress(n, i) + header(data) + f"""<div class="card">
        <span class="tag">{esc(it.get('tag','খবর'))}</span><span class="num">{i}/{total}</span>
        <div class="emoji">{esc(it.get('emoji','📰'))}</div>
        <h1>{esc(it['headline'])}</h1><ul>{pts}</ul>{src}</div>"""
    return body, (acc, ink)


def iman_body(data, n, short_ref=False):
    iman = data["iman"]
    acc, ink, _ = IMAN_THEME
    ref = iman.get("reference", "")
    if short_ref:
        ref = ref.split("—")[0].strip()
    arabic = (iman.get("arabic") or "").replace("\u06dd", " ")  # ayah-end sign often has no glyph
    ar = f'<div class="arabic">{esc(arabic)}</div>' if arabic.strip() else ""
    body = progress(n, n) + header(data) + f"""<div class="card"><span class="tag">ঈমানী বার্তা</span>
        <div class="emoji">🌙</div>{ar}<div class="quote">{esc(iman.get('text',''))}</div>
        <div class="ref">{esc(ref)}</div></div>"""
    return body, (acc, ink), ref


def end_body(data, n, text_h1, text_p, emoji="👍"):
    return progress(n, n) + header(data) + f"""<div class="big"><div class="emoji">{emoji}</div>
        <h1>{esc(text_h1)}</h1><p>{esc(text_p)}</p></div>"""


def build_full(data):
    items = data.get("items", [])
    n = len(items) + (1 if data.get("iman") else 0)
    segs = hook_seg(data, n)
    for i, it in enumerate(items, 1):
        body, th = item_body(data, it, i, n, len(items))
        for k, s in enumerate(it.get("narration", [])):
            segs.append(dict(body=body, text=s, theme=th, story=(k == 0)))
    if data.get("iman"):
        body, th, _ = iman_body(data, n)
        for k, s in enumerate(data["iman"].get("narration", [])):
            segs.append(dict(body=body, text=s, theme=th, story=(k == 0)))
    end = end_body(data, n, "ফলো ও শেয়ার করুন", "প্রতিদিন সকাল, দুপুর ও সন্ধ্যায় প্রবাসীদের জরুরি খবর")
    outro = data.get("outro") or ["প্রতিদিনের গুরুত্বপূর্ণ খবর পেতে পেজটি ফলো করুন এবং শেয়ার করুন।", "আল্লাহ হাফেজ।"]
    for k, s in enumerate(outro):
        segs.append(dict(body=end, text=s, theme=DEFAULT_THEME[:2], story=(k == 0)))
    return segs


def build_reel_candidates(data, teaser=False):
    """Sentences for the Reel, each with a priority (lower = keep first) and speaking order."""
    items = data.get("items", [])
    n = len(items) + 1
    segs = []
    for s in hook_seg(data, n):
        s["prio"] = 0
        segs.append(s)
    for i, it in enumerate(items, 1):
        body, th = item_body(data, it, i, n, len(items), show_src=False)
        sents = it.get("short") or it.get("narration", [])[:2]
        for k, sent in enumerate(sents[:2]):
            # first line of every story first, then second lines; later stories drop first
            segs.append(dict(body=body, text=sent, theme=th, story=(k == 0), prio=1 + k * 10 + i))
    if data.get("iman") and data["iman"].get("text") and not teaser:
        body, th, ref = iman_body(data, n, short_ref=True)
        segs.append(dict(body=body, text=f"আজকের ঈমানী বার্তা: {data['iman']['text']} {ref}।",
                         theme=th, story=True, prio=5))
    if teaser:
        end = end_body(data, n, "পুরো ভিডিও দেখুন", "বিস্তারিত ভিডিওর লিংক প্রথম কমেন্টে", "▶️")
        text = "পুরো বিস্তারিত ভিডিও আমাদের পেজে, লিংক কমেন্টে। পেজটি ফলো করুন।"
    else:
        end = end_body(data, n, "ফলো করুন", "প্রতিদিন সকাল, দুপুর ও সন্ধ্যায় প্রবাসীদের জরুরি খবর")
        text = "প্রতিদিন তিনবার জরুরি খবর পেতে পেজটি ফলো করুন। আল্লাহ হাফেজ।"
    segs.append(dict(body=end, text=text, theme=DEFAULT_THEME[:2], story=True, prio=0))
    for o, s in enumerate(segs):
        s["order"] = o
    return segs


def pick_reel(segs, durs, limit):
    """Keep the most important sentences that fit in `limit` seconds, in speaking order."""
    keep, total = set(), 0.0
    for j in sorted(range(len(segs)), key=lambda j: (segs[j]["prio"], segs[j]["order"])):
        if total + durs[j] <= limit or segs[j]["prio"] == 0:
            keep.add(j)
            total += durs[j]
    for j in sorted(keep, key=lambda j: -segs[j]["prio"]):
        if total <= limit:
            break
        if segs[j]["prio"] != 0:
            keep.discard(j)
            total -= durs[j]
    return sorted(keep)


# ---------------------------------------------------------------- helpers
def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-3000:])
        raise SystemExit(f"command failed: {' '.join(map(str, cmd[:3]))} ...")
    return r.stdout


def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.strip())


async def tts_edge(text, out):
    """Write speech to `out`; return word start times in seconds (may be empty)."""
    import edge_tts
    for attempt in range(4):
        times = []
        try:
            try:
                com = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary")
            except TypeError:  # older edge-tts without the boundary option
                com = edge_tts.Communicate(text, VOICE, rate=RATE)
            with open(out, "wb") as f:
                async for ch in com.stream():
                    if ch["type"] == "audio":
                        f.write(ch["data"])
                    elif ch["type"] == "WordBoundary":
                        times.append(ch["offset"] / 1e7)
            if out.exists() and out.stat().st_size > 1000:
                return times
        except Exception as e:  # network hiccup: retry
            print(f"  edge-tts retry {attempt+1}: {e}")
            await asyncio.sleep(3 * (attempt + 1))
    return None


def make_audio(text, out, dry_run):
    """Create the sentence audio; return word start times (list, maybe empty)."""
    if dry_run:
        secs = max(2.0, len(text) / 13.0)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{secs:.2f}", str(out)])
        return []
    times = asyncio.run(tts_edge(text, out))
    if times is None:
        print("  edge-tts failed, falling back to gTTS")
        from gtts import gTTS
        gTTS(text=text, lang="bn").save(str(out))
        times = []
    return times


def word_times(words, times, dur):
    """Start time of each word: real timings when they line up, otherwise by word length."""
    if times and len(times) == len(words):
        return times
    lead, speak = min(0.12, dur * 0.05), max(dur - 0.25, 0.5)
    lens = [len(w) + 2 for w in words]
    tot, acc, out = sum(lens), 0, []
    for L in lens:
        out.append(lead + speak * acc / tot)
        acc += L
    return out


def make_whoosh(path):
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=d=0.6:c=pink:a=0.6:r=48000",
         "-af", "highpass=f=400,lowpass=f=5000,afade=t=in:d=0.22,afade=t=out:st=0.22:d=0.38,volume=0.35",
         "-ac", "2", str(path)])


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("content")
    ap.add_argument("--out", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reel", action="store_true", help="short (<90 s) Reel")
    ap.add_argument("--teaser", action="store_true", help="Reel that points to the full video (for long stories)")
    ap.add_argument("--max-segments", type=int, default=0, help="only render first N sentences (testing)")
    a = ap.parse_args()
    if a.teaser:
        a.reel = True

    data = json.loads(Path(a.content).read_text(encoding="utf-8"))
    date = Path(a.content).stem
    kind = "reel" if a.reel else "full"
    work = ROOT / "build" / f"{date}-{kind}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    out = Path(a.out or ROOT / "build" / (f"{date}-reel.mp4" if a.reel else f"{date}.mp4"))

    # 1) audio for every candidate sentence (Reel needs real lengths to choose what fits)
    segs = build_reel_candidates(data, a.teaser) if a.reel else build_full(data)
    if a.max_segments:
        segs = segs[: a.max_segments]
    for i, s in enumerate(segs):
        print(f"  voice [{i+1}/{len(segs)}] {s['text'][:50]}")
        s["mp3"] = work / f"a{i:03d}.mp3"
        s["times"] = make_audio(s["text"], s["mp3"], a.dry_run)
        s["dur"] = duration(s["mp3"]) + PAUSE
    if a.reel:
        keep = pick_reel(segs, [s["dur"] for s in segs], REEL_MAX)
        segs = [segs[j] for j in keep]
    print(f"{len(segs)} sentences, ~{sum(s['dur'] for s in segs):.0f} s")

    # 2) frames: one image per spoken word (karaoke), one browser for all
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        for i, s in enumerate(segs):
            words = s["text"].split()
            starts = word_times(words, s["times"], s["dur"] - PAUSE)
            ks = list(range(len(words))) if KARAOKE else [-1]
            s["frames"] = []
            for k in ks:
                png = work / f"f{i:03d}_{k+1:03d}.png"
                pg.set_content(page(s["body"], words, k, *s["theme"]), wait_until="load")
                pg.evaluate("document.fonts.ready")
                pg.screenshot(path=str(png))
                s["frames"].append((png, starts[k] if k >= 0 else 0.0))
            if i == 0:
                shutil.copy(s["frames"][-1][0], out.with_name(f"{out.stem}-thumb.png"))
        b.close()

    # 3) one clip per sentence: word frames timed to the voice + slow push-in
    clips, story_starts, t = [], [], 0.0
    for i, s in enumerate(segs):
        d = s["dur"]
        if s.get("story") and i > 0:
            story_starts.append(t)
        lst = work / f"l{i:03d}.txt"
        fr = s["frames"]
        lines = []
        for j, (png, st) in enumerate(fr):
            st = 0.0 if j == 0 else st
            nxt = fr[j + 1][1] if j + 1 < len(fr) else d
            lines.append(f"file '{png}'\nduration {max(nxt - st, 0.04):.3f}\n")
        lines.append(f"file '{fr[-1][0]}'\n")
        lst.write_text("".join(lines))
        zoom = 0.045 if s.get("story") else 0.03
        vf = (f"fps=30,scale=w='trunc({W}*(1+{zoom}*t/{d:.3f})/2)*2':h=-2:eval=frame,"
              f"crop={W}:{H},setsar=1,format=yuv420p")
        clip = work / f"c{i:03d}.mp4"
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(s["mp3"]),
             "-af", f"apad=pad_dur={PAUSE}", "-t", f"{d:.3f}", "-vf", vf,
             "-c:v", "libx264", "-preset", "veryfast", "-r", "30",
             "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", str(clip)])
        clips.append(clip)
        t += duration(clip)

    # 4) join, then final sound mix: voice + whoosh between stories + optional music, loudness -14 LUFS
    joined = work / "joined.mp4"
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{c}'\n" for c in clips))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])

    inputs, chains, mix = ["-i", str(joined)], [], ["[v0]"]
    chains.append("[0:a]asplit=2[v0][sc]" if MUSIC.exists() else "[0:a]anull[v0]")
    idx = 1
    if MUSIC.exists():
        inputs += ["-stream_loop", "-1", "-i", str(MUSIC)]
        chains.append(f"[{idx}:a]aformat=channel_layouts=stereo:sample_rates=48000,volume={MUSIC_VOL}[m];"
                      f"[m][sc]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[md]")
        mix.append("[md]")
        idx += 1
        print(f"music: {MUSIC.name}")
    if SFX and story_starts:
        wh = work / "whoosh.wav"
        make_whoosh(wh)
        inputs += ["-i", str(wh)]
        n = len(story_starts)
        chains.append(f"[{idx}:a]asplit={n}" + "".join(f"[w{k}]" for k in range(n)) if n > 1 else f"[{idx}:a]anull[w0]")
        for k, st in enumerate(story_starts):
            ms = max(int(st * 1000) - 150, 0)
            chains.append(f"[w{k}]adelay={ms}|{ms}[wd{k}]")
            mix.append(f"[wd{k}]")
    chains.append("".join(mix) + f"amix=inputs={len(mix)}:normalize=0:duration=first,"
                  "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chains), "-map", "0:v", "-map", "[a]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(out)])
    print(f"done: {out} ({duration(out):.0f} s)")


if __name__ == "__main__":
    main()
