# ADS-B Ultrafeeder — TRMNL Plugin

Live aircraft radar on your TRMNL display, powered by your own [docker-adsb-ultrafeeder](https://github.com/sdr-enthusiasts/docker-adsb-ultrafeeder) receiver. No cloud API, no rate limits.

![radar screenshot placeholder](docs/screenshot.png)

## What it shows

- **Radar** — aircraft dots positioned by lat/lon, brightness by altitude, trail dots, emergency squawk flag
- **Stats** — live aircraft count, MLAT count, max range, message rate, gain dB, strong signals, positions/min
- **Sparklines** — rolling history of aircraft count, max range, message rate, and gain dB

---

## Requirements

- A running [docker-adsb-ultrafeeder](https://github.com/sdr-enthusiasts/docker-adsb-ultrafeeder) instance (or any feeder that exposes `/data/aircraft.json` and `/data/stats.json`)
- A server reachable from your ADS-B host — Raspberry Pi on the same LAN works fine
- Docker (or Docker Compose) on that server

---

## Setup

### 1. Add the plugin to TRMNL

Install the **ADS-B Ultrafeeder** plugin from the TRMNL plugin store. Open its settings page and copy the **Webhook URL** — you'll need it in the next step.

### 2. Configure the backend

Create a `.env` file (use `.env.example` as a starting point):

```env
# Required
TRMNL_WEBHOOK_URL=https://usetrmnl.com/api/custom_plugins/YOUR_UUID
FEEDER_LAT=51.1234
FEEDER_LON=4.5678
ULTRAFEEDER_URL=http://ultrafeeder   # or the hostname/IP of your feeder

# Optional
TIER=standard                # standard (2 KB budget) or plus (5 KB)
POLL_INTERVAL_SECONDS=300    # how often to push, in seconds
HISTORY_TIMEFRAME=2h         # how much history to keep (e.g. 1h, 30m)
ROUTE_DISPLAY=codes          # codes (IATA) or names (full city names)
```

### 3. Run with Docker Compose

```yaml
# docker-compose.yml
services:
  trmnl-adsb-ultrafeeder:
    image: ghcr.io/excusemi/trmnl-adsb-ultrafeeder:latest
    container_name: trmnl-adsb-ultrafeeder
    restart: unless-stopped
    env_file: .env
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=4)"]
      interval: 30s
      timeout: 5s
      retries: 3
    volumes:
      - trmnl-adsb-state:/data

volumes:
  trmnl-adsb-state:
```

```sh
docker compose up -d
```

The container pushes data to TRMNL on every poll cycle. Check it's working:

```sh
docker logs trmnl-adsb-ultrafeeder
# push: HTTP 200 | 34 ac | 1842/2048 bytes
```

### 4. Configure the plugin in TRMNL

Back on the plugin settings page:

| Setting | Description |
|---|---|
| **Webhook URL** | Already set — this is where the backend pushes |
| **Measurement Units** | Imperial (ft, kt) or Metric (m, km/h) |
| **Radar Scale** | Max range shown on radar (50 / 100 / 200 / 300 nm) |
| **Radar Center Latitude / Longitude** | Override the map center. Leave blank to use your feeder position. Useful if most traffic is in one direction. |
| **Feeder Icon** | Show or hide the house marker on the radar |

---

## Running alongside ultrafeeder

If both containers run on the same host, add `trmnl-adsb-ultrafeeder` to your existing compose file and put both services on a shared network so the backend can reach `http://ultrafeeder`:

```yaml
services:
  ultrafeeder:
    # ... your existing config ...
    networks:
      - adsb

  trmnl-adsb-ultrafeeder:
    image: ghcr.io/excusemi/trmnl-adsb-ultrafeeder:latest
    container_name: trmnl-adsb-ultrafeeder
    restart: unless-stopped
    env_file: .env
    networks:
      - adsb
    volumes:
      - trmnl-adsb-state:/data

networks:
  adsb:

volumes:
  trmnl-adsb-state:
```

Set `ULTRAFEEDER_URL=http://ultrafeeder` in `.env`.

---

## Environment variables reference

| Variable | Default | Description |
|---|---|---|
| `TRMNL_WEBHOOK_URL` | *(required)* | Webhook URL from TRMNL plugin settings |
| `FEEDER_LAT` | `51.1234` | Your antenna latitude |
| `FEEDER_LON` | `4.5678` | Your antenna longitude |
| `ULTRAFEEDER_URL` | `http://ultrafeeder` | Base URL of your feeder |
| `TIER` | `standard` | `standard` (2 KB) or `plus` (5 KB payload budget) |
| `POLL_INTERVAL_SECONDS` | `300` | Push interval in seconds |
| `HISTORY_TIMEFRAME` | `2h` | Sparkline history window (e.g. `1h`, `90m`) |
| `ROUTE_DISPLAY` | `codes` | `codes` for IATA codes, `names` for city names |
| `STATE_PATH` | `/data/state.json` | Path for persisted state |
| `CACHE_PATH` | `/data/enrichment.db` | Path for route/aircraft SQLite cache |

---

## Architecture

```
ultrafeeder ──► /data/aircraft.json
             └► /data/stats.json
                      │
                      ▼
          trmnl-adsb-ultrafeeder (Python/Quart)
          • fetches + parses aircraft + RF stats
          • enriches with route/type from cache
          • builds compact CSV payload
          • pushes via TRMNL webhook
                      │
                      ▼
              TRMNL webhook endpoint
                      │
                      ▼
              TRMNL Liquid template
              renders radar + stats
```

State and enrichment cache survive container restarts via the `trmnl-adsb-state` volume.

---

## Health check

```sh
curl http://localhost:8080/health
# {"aircraft": 34, "interval": 300, "last_poll": 123456.78, "status": "ok", "tier": "standard"}
```
