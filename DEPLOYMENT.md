# Deployment

Two deployment shapes are supported. Pick based on whether you need writes.

| | GitHub Pages | Fly.io / Docker |
|---|---|---|
| Graph visualization | ✅ | ✅ |
| Search, clusters, collaboration candidates | ✅ | ✅ |
| Login, profiles, author claiming | ❌ | ✅ |
| Admin curation UI, contribution queue | ❌ | ✅ |
| Notifications | ❌ | ✅ |
| Cost | free | needs a persistent volume |
| Maintenance | none | updates, backups, secret rotation |

The static site is a genuine product on its own — Phase 0/1 were designed that
way. Only deploy the backend when you actually want members writing data.

## Before either option

```bash
uv run python -m unittest discover -s tests   # 51 tests
uv run scripts/check_data.py                  # corpus integrity
uv run scripts/preflight.py --target pages    # or --target fly
```

`preflight.py` is the deploy gate: it checks secrets, migrations, admin
accounts, and — importantly — that `site/data.json` is **newer** than
`data/syriac.db`. Deploying a stale export ships a graph that silently
disagrees with the database.

## Option A — GitHub Pages (static, free)

Already automated. `.github/workflows/pages.yml` publishes `site/` after CI
passes on `main`.

```bash
uv run scripts/export_json.py    # refresh the export first
uv run scripts/preflight.py --target pages
git add site/data.json && git commit -m "chore: refresh export" && git push
```

Enable once in the repo: **Settings → Pages → Source: GitHub Actions**.

`login.html`, `admin.html` and `profile.html` are still served but every API
call returns 404 — there is no backend. Either accept that or remove the header
links before publishing.

## Option B — Fly.io (full app)

`fly.toml` and `Dockerfile` are ready. The database lives on a mounted volume
at `/app/data`, so it survives deploys.

```bash
fly auth login
fly launch --no-deploy          # reuses the existing fly.toml
fly volumes create syriac_data --size 1 --region ams

# REQUIRED — without it every restart logs all users out
fly secrets set SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
fly secrets set ALLOWED_ORIGINS=https://your-domain.example

fly deploy
```

The image ships **without** a database (`data/` is gitignored except the
committed `syriac.db`). Seed the volume once:

```bash
fly ssh console -C "ls -la /app/data"          # confirm the mount
fly sftp shell                                  # then: put data/syriac.db /app/data/syriac.db
```

Then register the first account immediately — `api/routes/auth.py` bootstraps
the **first** registered user as admin, so anyone who beats you to it owns the
curation tools.

### Local Docker (same image, good rehearsal)

```bash
cp .env.example .env    # fill in SECRET_KEY
docker compose up --build
```

## Post-deploy checklist

1. `GET /healthz` returns `{"status":"ok"}`.
2. Register the admin account — before announcing the URL.
3. `GET /api/status` returns 403 when logged out, 200 as admin.
4. Work through the duplicate queue in the admin UI (currently 920 pending).
5. Schedule the data refresh (see below).

## Keeping data fresh

```bash
uv run scripts/update_data.py            # backs up, fetches, analyses, exports,
                                         # and rolls back if any step fails
uv run scripts/generate_notifications.py # tell claimed profiles what changed
```

`update_data.py` snapshots the database to `data/backups/` before touching it.
`generate_notifications.py` is idempotent, so a nightly cron is safe — it will
not re-send anything a user already has.

## Domain names

Buy and manage domains through [WordPress.com domains](https://wordpress.com/domains),
then point a CNAME at the Fly.io app or the Pages site.
