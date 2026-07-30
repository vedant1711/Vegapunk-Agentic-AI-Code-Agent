# Deploy Vegapunk on free-tier hosting

Two paths depending on how much control you want:

- **[Managed](#managed-vercel--render)** — Vercel for the frontend, Render for the backend. Zero infra work, fully free tier.
- **[Self-host](#self-host-docker-compose)** — one `docker compose up`, runs anywhere with Docker.

Both paths use the same repo.

---

## Managed: Vercel + Render

### Backend on Render (free web service)

The repo ships a `render.yaml` blueprint at the root. Render reads it and provisions the service in one click.

1. Push the repo to GitHub.
2. Log in to <https://render.com> (free tier, no credit card needed).
3. Click **New +** → **Blueprint** → point it at your GitHub repo.
4. Render reads `render.yaml`, then prompts for the secret env vars:

   | Secret | Where to get it |
   |---|---|
   | `NVIDIA_API_KEY` | <https://build.nvidia.com> (free credits on signup) |
   | `GEMINI_API_KEY` | <https://aistudio.google.com/apikey> (free tier: 15 RPM) |
   | `GITHUB_TOKEN` | <https://github.com/settings/tokens?type=beta> (needs `repo` scope) |
   | `GITHUB_WEBHOOK_SECRET` | Optional; needed only if you wire webhooks |

5. Click **Apply**. First build takes ~3-5 minutes.
6. Note the URL Render gives you (e.g. `https://vegapunk-api.onrender.com`) — you'll paste it into Vercel next.

**Free-tier caveats to be aware of:**
- Web service auto-sleeps after 15 min of inactivity; first request after wake takes ~30s.
- 750 instance-hours/month across your Render account.
- No Docker daemon available — the sandbox falls back to local subprocess execution.
- Best-of-N with K=3 triples LLM cost per Coder step; if you hit rate limits, set `CODER_BON_K=1` in the dashboard.

### Frontend on Vercel (free hobby tier)

1. Log in to <https://vercel.com>.
2. **Add New** → **Project** → import the same GitHub repo.
3. **Root directory:** set to `frontend`.
4. Environment variables:

   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | your Render URL from step 6 above (e.g. `https://vegapunk-api.onrender.com`) |

5. Click **Deploy**. First build takes ~2-3 minutes.
6. Your live URL is `https://<project-name>.vercel.app`. Paste it into the "Try it live" section of the root README so reviewers can find it.

Vercel auto-detects Next.js from `frontend/vercel.json` and `package.json` — no other config needed.

### Verify

- Visit your Vercel URL.
- Click **Try demo** — should show a full trace animate through in ~17 seconds without touching any LLM.
- Optional: paste a real GitHub issue URL and click **Run agent** to burn some real LLM credits.

---

## Self-host: docker-compose

If you have Docker and don't want to deal with managed platforms:

```bash
git clone https://github.com/OWNER/REPO.git vegapunk
cd vegapunk
cp .env.example .env
# edit .env with your NVIDIA_API_KEY, GEMINI_API_KEY, GITHUB_TOKEN

docker compose up --build
```

- Backend: <http://localhost:8000>
- Frontend: <http://localhost:3000>
- Health checks are wired in the compose file; `docker compose ps` shows service state.

Both services run under production Node/Python, not dev-reload. For dev mode, use `make dev-api` + `make dev-web` instead.

To put this behind a real domain, add a reverse proxy in front (Caddy, Traefik, nginx). Not included in the shipped compose file since it's environment-specific.

---

## Cost check

Everything above is on free tiers as of the doc date:

| Resource | Tier | What you pay |
|---|---|---|
| Vercel (frontend) | Hobby | $0 |
| Render (backend web service) | Free | $0 (750 hrs/month, sleeps) |
| NVIDIA NIM | Signup credits | Free until credits exhausted |
| Google Gemini | Free tier | $0 (15 RPM for Pro, 30 RPM for Flash) |
| GitHub Actions | Public repo | Unlimited free minutes |
| GitHub PAT | Personal | $0 |

Total cost to run a portfolio demo: **$0**.
