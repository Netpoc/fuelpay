# Running FuelPay locally

Two things to start: the **API** (`fuelpay-service/`) and the **web app**
(`fuelpay-web/`). Use two terminal tabs.

---

## Quick start

### Terminal 1 — the API

Start **Docker Desktop** first (it's installed but not running), wait for the
whale icon to settle, then:

```bash
cd ~/Projects/fuelpay/output/fuelpay-service
docker compose up --build
```

First run takes a few minutes: it builds the image, starts Postgres, runs the
migration, then generates **60 days of history** for 12 generators. You'll know
it's ready when the log says:

```
backfilled 12 generators over 60 days: ... readings, ... events
INFO:     Application startup complete.
```

The API is now on **http://localhost:8000** — try http://localhost:8000/docs.

### Terminal 2 — the web app

```bash
cd ~/Projects/fuelpay/output/fuelpay-web
npm install     # only needed the first time
npm run dev
```

Open **http://localhost:5173** and paste the key:

```
dev-local-key-change-me
```

That's it.

---

## What you can test

| Where | What to try |
|---|---|
| Fleet dashboard | Tank levels for all 12 generators. Units with a live incident sort to the top with a coloured banner and a pulsing badge on the tank. Filter by **Incidents**, **Running**, **Low fuel**, or by site. |
| Click any card | Generator detail: large tank, a **fuel-usage chart** with every drain and refill marked, and the incident list for that window. |
| Chart range buttons | 24h / 7d / 30d / 60d. The server picks a bucket size so a 60-day window is a few hundred points rather than the 17,280 raw readings behind it. Drag on the chart to zoom. |
| **Simulate drain** button | Fires a real siphon. The tank drops over several simulated steps, a red band and a `▼ −N L` marker appear on the chart, and the card gets a red **Suspected drain** banner. |
| **Simulate refill** button | Dispatches a tanker. The tank fills to 90–100% and a green `▲ +N L` marker lands on the chart. |
| http://localhost:8000/docs | Every endpoint, with a *Try it out* button. Click **Authorize** and paste the key. |

The tank surface ripples only while a generator's engine is running and settles
flat when it stops. On the 30-day view you can see the whole cycle: fuel
draining down to the reorder line, then a tanker refilling it.

**What counts as an alert.** A suspected drain always does. Low fuel only does
while it is unresolved — tanks cross their reorder line every cycle and a
tanker turns up, so flagging every crossing would light most of the fleet and
mean nothing.

### Watching a drain from the terminal instead

```bash
KEY=dev-local-key-change-me

# pick a generator
curl -s -H "X-API-Key: $KEY" localhost:8000/v1/generators | head -c 300

# siphon 200 litres from it
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"generator_id":"<paste-id>","volume_l":200}' \
  localhost:8000/v1/admin/simulate/drain

# see the events it produced
curl -s -H "X-API-Key: $KEY" \
  "localhost:8000/v1/events?event_type=SUSPECTED_DRAIN&limit=5"
```

---

## Stopping and resetting

```bash
# stop (keeps the data)
docker compose down

# start over from an empty database — re-seeds and re-backfills 60 days
docker compose down -v
```

Ctrl-C in each terminal stops the foreground processes.

---

## Making it feel more "live"

Out of the box a new reading appears every **5 real minutes**. That is by
design: the simulated clock is locked to wall-clock, so one simulated minute
takes one real minute.

For a livelier demo, add these to `fuelpay-service/.env` and restart:

```ini
FUELPAY_SIM_MINUTES_PER_TICK=1
FUELPAY_SIM_TICK_SECONDS=15
```

⚠️ Do this **before** the first run, or on a fresh `docker compose down -v`.
It also multiplies the backfill by five — about a million rows and a few
minutes of startup instead of ~200k. The `Simulate drain` / `Simulate refill`
buttons work instantly either way and are the better demo lever.

To make thefts happen on their own, raise the odds **and** open the hour window
(leaving the window at 22:00–04:00 means nothing happens during a daytime demo):

```ini
FUELPAY_SIM_THEFT_PROBABILITY_PER_DAY=20
FUELPAY_SIM_THEFT_WINDOW_START_HOUR=0
FUELPAY_SIM_THEFT_WINDOW_END_HOUR=24
```

---

## If something goes wrong

**`Cannot connect to the Docker daemon`** — Docker Desktop isn't running. Open
it from Applications and wait for it to finish starting.

**Port 5432 already in use** — you have PostgreSQL 17 running locally. Either
quit it, or change the port in `.env`:

```ini
POSTGRES_PORT=5433
```

(This only affects the port exposed on your machine; the API talks to the
database inside Docker either way.)

**Port 5173 or 8000 in use** — something else is on them:

```bash
lsof -nP -iTCP:5173 -sTCP:LISTEN     # see what
```

**The web app shows "That key was not accepted"** — the API isn't up yet, or is
still backfilling. Check Terminal 1 for `Application startup complete`.

**The web app loads but shows no generators** — check the browser console. If
you see a CORS error, the API's allowed origins don't include :5173; set this in
`.env` and restart:

```ini
FUELPAY_CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

---

## One thing to tidy in your `.env`

This line is stale:

```ini
FUELPAY_DATABASE_URL=postgresql+asyncpg://fuelpay:fuelpay@localhost:5432/fuelpay
```

It doesn't match your `POSTGRES_USER=postgres` / `POSTGRES_DB=third_party`.
Under Docker it's **harmless** — `docker-compose.yml` overrides it with the
right value (`postgres:root@db:5432/third_party`), which I verified. But it
would be used if you ever run the API directly on your machine without Docker,
and then it would fail to connect. Safe to delete the line, or correct it.

---

## Without Docker (only if you need it)

You have PostgreSQL 17 at `/Library/PostgreSQL/17/bin`. Create a database and
point the API at it:

```bash
export PATH="/Library/PostgreSQL/17/bin:$PATH"
createdb -h localhost -U postgres fuelpay      # will prompt for the password

cd ~/Projects/fuelpay/output/fuelpay-service
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

export FUELPAY_DATABASE_URL="postgresql+asyncpg://postgres:YOURPASSWORD@localhost:5432/fuelpay"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --port 8000
```

The frontend command is unchanged.

---

## Not built yet

`/incidents` is a placeholder, there are no charts on the generator page, and
the dashboard does not update by itself — reload to see new readings. Those are
the next slice.
