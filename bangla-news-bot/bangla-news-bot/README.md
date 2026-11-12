# Bangla News Bot — automatic daily news video for Facebook

Every day:
1. **Claude** (your scheduled task) researches the news and writes `content/YYYY-MM-DD.json`, then pushes it to this repo.
2. **GitHub Actions** (free) sees the new file, makes a vertical video with a Bengali AI voice, news cards and subtitles.
3. It **posts the video to your Facebook Page** with Meta's official API and saves the link in `posted/`.

Cost: 0. GitHub Actions free minutes (~6 min per day), free Microsoft Bengali voice, free Meta API.

---

## One-time setup

### Step 1 — Put this code on GitHub
1. Create a free account at https://github.com
2. Click **New repository** → name: `bangla-news-bot` → **Private** → Create.
3. Click **uploading an existing file**, drag in all the files and folders from the zip (keep the folder structure, including `.github/workflows/daily-video.yml`), and click **Commit changes**.
   *(Hidden `.github` folder: on Mac press Cmd+Shift+. in Finder to see it.)*

### Step 2 — Get your Facebook keys (≈15 min)
1. Go to https://developers.facebook.com → log in with the Facebook account that is **admin of your Page** → **My Apps → Create App**.
2. Use case: **"Manage everything on your Page"** (or type "Other" → **Business**). Give it any name, e.g. `NewsBot`.
3. Open **Tools → Graph API Explorer** (https://developers.facebook.com/tools/explorer).
   - Meta App: choose `NewsBot`.
   - User or Page: **Get User Access Token**, tick these permissions:
     `pages_show_list`, `pages_read_engagement`, `pages_manage_posts` (and `publish_video` if it is in the list)
   - Click **Generate Access Token** and allow everything for your Page.
4. Make it long-lived: open https://developers.facebook.com/tools/debug/accesstoken → paste the token → **Debug** → **Extend Access Token** → copy the new long token.
5. Back in Graph API Explorer, paste the long token in the token box and run:
   `me/accounts`
   You will see your Page with its **`id`** and **`access_token`**. This Page token does not expire.
   - Copy `id` → this is **FB_PAGE_ID**
   - Copy `access_token` → this is **FB_PAGE_TOKEN**
   - (Optional check: paste the Page token in the Access Token Debugger — "Expires: Never".)

> Your app can stay in "Development" mode — you are the admin, so it can post to your own Page without Meta's App Review.
> Never share the token with anyone. If you change your Facebook password, make a new token (repeat 3–5).

### Step 3 — Save the keys in GitHub
Repo → **Settings → Secrets and variables → Actions**
- **Secrets** tab → New repository secret:
  - `FB_PAGE_ID` = your Page id
  - `FB_PAGE_TOKEN` = your Page access token
- **Variables** tab → New repository variable:
  - `TTS_VOICE` = `bn-BD-PradeepNeural` (male) or `bn-BD-NabanitaNeural` (female)
  - `AUTO_POST` = `false` for now (change to `true` when you are happy)

### Step 4 — Test
Repo → **Actions → Daily news video → Run workflow**
- First run: leave "Post to Facebook?" **unticked** → when it finishes (≈6 min) open the run and download the video under **Artifacts**. Watch it.
- Second run: tick **Post to Facebook?** → the video appears on your Page.
- Then set `AUTO_POST` = `true`. From now on, every new file in `content/` is posted automatically.

### Step 5 — Connect Claude to the repo
In Claude, connect your GitHub account (Settings → Connectors / GitHub) and give access to `bangla-news-bot`.
Then tell Claude the repo name, and it will change the daily scheduled task to write and push `content/<date>.json` every morning.

---

## Files
| Path | What it does |
|---|---|
| `bot/render.py` | JSON → video (cards + voice + subtitles). `--dry-run` = silent test |
| `bot/post_facebook.py` | Uploads the video to your Page, never posts the same date twice |
| `.github/workflows/daily-video.yml` | The automation |
| `content/` | One bulletin per day (written by Claude) |
| `posted/` | Log of posted videos with links |
| `fonts/` | Noto Sans Bengali (free, OFL licence) |

## If something fails
Open **Actions**, click the red run, read the last lines. Common ones:
- `token/page check failed` → token expired or wrong. Redo Step 2.3–2.5 and update the secret.
- `edge-tts failed, falling back to gTTS` → the Microsoft voice was unavailable; Google voice was used instead (video still made).
