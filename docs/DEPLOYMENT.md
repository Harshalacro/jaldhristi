# Deploying JalDrishti

The **backend** (FastAPI) runs on **Render**. The **frontend** (React + Vite) runs on **Vercel**.

```
Browser ──► Vercel (static React app)
               │  VITE_API_BASE = https://<your-api>.onrender.com
               ▼
            Render (FastAPI, uvicorn) ──► Open-Meteo, GloFAS, CWC, NDMA SACHET, OSM
               │  JALDRISHTI_CORS = https://<your-app>.vercel.app
```

Deploy the backend first, because the frontend needs its URL.

---

## 0. Before you start

- The code must be on GitHub. This guide uses `Harshalacro/jaldhristi`.
- You need accounts on [render.com](https://render.com) and [vercel.com](https://vercel.com). Sign in to both with GitHub.
- Optional free API keys, listed in [`backend/.env.example`](../backend/.env.example):
  - `GEMINI_API_KEY` or `GROQ_API_KEY`: gives the AI Copilot and advisories a large language model. Without one they use built-in fallbacks.
  - `OPENWEATHER_API_KEY`: adds a second rainfall forecast for the consensus check.

  Never commit keys. You enter them in the Render dashboard.

---

## 1. Backend on Render

### Option A: Blueprint (recommended)

The repository includes [`render.yaml`](../render.yaml), so Render can read the settings from it.

1. Open the Render dashboard, then **New → Blueprint**.
2. Connect GitHub and pick the **jaldhristi** repository. Choose the branch you want to deploy, usually `main` once the PR is merged.
3. Render shows one service, **jaldrishti-api**. It asks for the values marked `sync: false`:
   - `GEMINI_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, `OPENWEATHER_API_KEY`
   - Paste the keys you have. Leave the others empty.
4. Click **Apply**. The first build takes about 3–5 minutes.
5. When the service shows **Live**, copy its URL, for example `https://jaldrishti-api.onrender.com`.

### Option B: Manual web service

1. **New → Web Service**, then connect the repository.
2. Fill in these settings:

   | Field | Value |
   |---|---|
   | Root Directory | `backend` |
   | Runtime | Python 3 |
   | Region | Singapore (closest to India) |
   | Build Command | `pip install --upgrade pip && pip install -r requirements.txt` |
   | Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"` |
   | Health Check Path | `/api/health` |
   | Instance Type | Free (or Starter) |

3. Under **Environment**, add:

   | Key | Value |
   |---|---|
   | `PYTHON_VERSION` | `3.12.8` |
   | `PYTHONUNBUFFERED` | `1` |
   | `JALDRISHTI_CORS` | `https://jaldrishti.vercel.app` (you will fix this in step 3) |
   | `JALDRISHTI_CORS_REGEX` | `https://jaldrishti(-[a-z0-9-]+)?\.vercel\.app` |
   | `GEMINI_API_KEY` etc. | optional |

4. Click **Create Web Service**.

### Check the backend

Open these in a browser. Replace the host with your own.

| URL | Expected |
|---|---|
| `https://jaldrishti-api.onrender.com/api/health` | `{"ok": true, "locations": 112, ...}`. Right after boot, `ok` can be `false` for about 30–60 s while the first refresh runs. |
| `https://jaldrishti-api.onrender.com/api/official/summary` | `stations_read_directly` in the hundreds, plus live `danger` and `warning` counts |
| `https://jaldrishti-api.onrender.com/docs` | Interactive API documentation |

In **Logs** you should see these lines, in order:

1. `startup refresh ok: run N, 112 locations`
2. `gauge sweep: 9xx gauges reporting`

---

## 2. Frontend on Vercel

1. Open the Vercel dashboard, then **Add New… → Project**. Import **jaldhristi** from GitHub.
2. Configure the project:

   | Field | Value |
   |---|---|
   | Project Name | `jaldrishti`. The domain becomes `jaldrishti.vercel.app`; if you pick another name, see step 3. |
   | Framework Preset | Vite |
   | **Root Directory** | `frontend` (click **Edit** and select the folder; this setting is required) |
   | Build Command | `npm run build` (from [`frontend/vercel.json`](../frontend/vercel.json)) |
   | Output Directory | `dist` |

3. Under **Environment Variables**, add:

   | Key | Value | Environments |
   |---|---|---|
   | `VITE_API_BASE` | `https://jaldrishti-api.onrender.com` (your Render URL, **no trailing slash**) | Production, Preview, Development |

4. Click **Deploy**. It takes about 1 minute. Vercel then gives you a URL such as `https://jaldrishti.vercel.app`.

> `VITE_API_BASE` is built into the JavaScript bundle. If you change it later, **redeploy**: go to Deployments, open the ⋯ menu and choose Redeploy. Saving the variable alone does not update the site.

---

## 3. Connect the two (CORS)

The backend only answers browsers loading the site from origins it knows.

1. In Render, open **jaldrishti-api → Environment**.
2. Set `JALDRISHTI_CORS` to your exact Vercel production URL(s), separated by commas and without trailing slashes:
   ```
   https://jaldrishti.vercel.app
   ```
   If you add a custom domain, add it here as well, e.g. `https://jaldrishti.vercel.app,https://jaldrishti.in`.
3. `JALDRISHTI_CORS_REGEX` also allows Vercel **preview** deployments. They are named `<project>-<hash>-<team>.vercel.app` or `<project>-git-<branch>-<team>.vercel.app`. If your project is not called `jaldrishti`, change the pattern to match, for example:
   ```
   https://myproject(-[a-z0-9-]+)?\.vercel\.app
   ```
4. **Save Changes**. Render restarts the service automatically.

### Final check

Open the Vercel URL. The masthead should show **LIVE · x min ago**, and the map should show town circles.

If the page stays on "Cannot reach the JalDrishti API":

1. Open the browser's DevTools and look at the Console.
   - A **CORS** error means step 3 is wrong. The origin must match exactly: `https`, no trailing slash.
   - `ERR_NAME_NOT_RESOLVED` or 404 on `/api/...` means `VITE_API_BASE` is wrong, or you did not redeploy after setting it.
2. The free Render instance **sleeps after 15 minutes idle**. The first request then takes 30–60 s while it wakes. The app shows "warming up" and retries on its own.

---

## 4. Know the free-tier limits

| Topic | What happens | What to do |
|---|---|---|
| Sleep on idle (Render Free) | The first visit after 15 min idle waits for a cold start and a fresh data pull | Upgrade to Starter ($7/mo), or ping `/api/health` every 10 min with a free uptime monitor (e.g. UptimeRobot) |
| No persistent disk (Render Free) | The SQLite store and caches reset on each deploy or restart. The 30-year river climatology is rebuilt in the background after boot, using the Open-Meteo quota, and the scores are still valid meanwhile. | On Starter or above, uncomment the `disk:` block in `render.yaml` and set `JALDRISHTI_DB=/var/data/jaldrishti.db` and `JALDRISHTI_CACHE_DIR=/var/data/cache` |
| 512 MB RAM | PyTorch does not fit, so the **Chronos AI river forecast** is off. The station view still shows the CWC observations and marks. | On a ≥2 GB instance, change the build command to `pip install -r requirements-ml.txt` |
| Shared outbound IPs | Open-Meteo or Overpass may occasionally return HTTP 429 | The backend backs off and keeps the previous snapshot; nothing to do |

---

## 5. Updating

- **Push to the deployed branch.** Render and Vercel both redeploy automatically.
- **Open a pull request.** Vercel builds a **preview** URL for it. Previews reach the API because of `JALDRISHTI_CORS_REGEX`.
- **Rotate an API key.** Change it in Render → Environment → Save. No code change is needed.

---

## 6. Local production test (optional)

This runs the same setup as the hosted one: the frontend calls the API across origins, with no Vite proxy.

```bash
# terminal 1: API
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# terminal 2: production build pointed at that API
cd frontend
VITE_API_BASE=http://127.0.0.1:8000 npm run build      # PowerShell: $env:VITE_API_BASE="http://127.0.0.1:8000"; npm run build
npx vite preview --port 4173                            # http://localhost:4173
```

`localhost` on any port is always allowed by the backend's CORS setting.
