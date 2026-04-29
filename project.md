# TRMNL ADS-B Ultrafeeder Plugin — Project Design

## What this is

A Docker container that sits alongside an existing
[docker-adsb-ultrafeeder](https://github.com/sdr-enthusiasts/docker-adsb-ultrafeeder)
deployment and feeds live aircraft data to a TRMNL e-paper display.

Webhook-only: container polls ultrafeeder, maintains rolling state in-memory, and
pushes compact JSON to TRMNL on a schedule. Works from any LAN — no inbound ports
needed. Constrained to 2 KB (standard) / 5 KB (TRMNL+).

---

## Integration context

The container is designed to slot into an existing Pi setup alongside ultrafeeder,
wireguard, and cloudflared. It reads from the ultrafeeder's local HTTP API
(`http://wireguard/data/aircraft.json`, `stats.json`) and pushes outbound — no
inbound ports required for the webhook path.

```yaml
# addition to existing docker-compose.yml
services:
  trmnl-adsb:
    image: ghcr.io/excusemi/trmnl-adsb-ultrafeeder-plugin:latest
    restart: unless-stopped
    environment:
      - ULTRAFEEDER_URL=http://wireguard      # reachable within docker network
      - FEEDER_LAT=51.1234
      - FEEDER_LON=4.5678
      - TRMNL_WEBHOOK_URL=${TRMNL_WEBHOOK_URL}
      - TIER=standard                         # standard (2 KB) or plus (5 KB)
      - POLL_INTERVAL_SECONDS=300             # 300 = safe for standard (12/hr), 120 for plus
      - TRAILS_ENABLED=true                   # include position trails for closest planes
      - HISTORY_TIMEFRAME=2h                  # sparkline depth: 1h, 2h, 3h, 6h, 12h, 24h
      - ROUTE_DISPLAY=codes                   # codes (LHR>AMS), cities (London>Amsterdam), off
```

## Payload design

### Webhook (2 KB budget)

Single `deep_merge` push per interval. Container maintains all state in-memory.

```json
{
  "merge_variables": {
    "ac": [
      ["BAW123", "A320", 35000, 450, 245, 0, 51.1234, 4.5678, [[-13,-18],[-26,-36],[-39,-54]], "LHR>AMS", 45],
      ["EZY42V", "A319", 12000, 380, 178, 1, 51.0987, 4.6012],
      ["",       "C172",  2500,  95, 312, 0, 51.2100, 4.4900]
    ],
    "hn": [42,38,35,41,44,40,37,39,42,41,38,36,33,35,38,40,43,44,42,39,37,40,42,44],
    "hr": [180,175,168,182,190,185,178,172,180,183,188,175,170,168,172,175,180,185],
    "s":  [42, 8, 180, 247, 1250],
    "fc": [51.1234, 4.5678],
    "ts": "14:32"
  }
}
```

#### `ac` field indices

| Index | Field | Notes |
|---|---|---|
| 0 | callsign | `""` if anonymous |
| 1 | type code | `""` if unknown |
| 2 | altitude ft | `-1` = on ground |
| 3 | ground speed kt | integer |
| 4 | track degrees | 0–359 |
| 5 | source | `0`=ADS-B `1`=MLAT `2`=TIS-B |
| 6 | latitude | float, 4 dp (~10 m) |
| 7 | longitude | float, 4 dp |
| 8 | trail | `[[Δlat,Δlon],...]` in 0.001° units — **only on closest N planes**, omitted otherwise |
| 9 | route | `"LHR>AMS"`, omitted if unknown |
| 10 | progress | 0–100 integer, omitted if no route |
| 11 | emergency | squawk string `"7700"` or ADS-B code — **omitted unless active** |

Trailing optional fields are dropped from the array when not present. Liquid accesses
by index; missing trailing indices return nil.

Trail deltas are relative to `[6]`/`[7]` (current position), in units of 0.001°
(~100 m precision). Most recent trail point first.

#### `hn` / `hr` — history arrays

Parallel flat integer arrays. Index 0 = oldest, last index = current interval.

- `hn` — aircraft count per interval
- `hr` — max observed range (nm) per interval

Flat arrays (not array-of-objects) to maximize point density within the byte budget.
At 5-min intervals, 24 points = 2 hours. At 15-min, 6 hours.

#### `fc` — feeder station coordinates

`[lat, lon]` — the receiver's fixed position, 4 dp. Sourced from `FEEDER_LAT` /
`FEEDER_LON` env vars. Used by the Liquid template to compute bearing/distance to
each plane without needing a server-side calculation.

#### `s` — feeder stats

`[total_ac, mlat_count, range_nm, day_max_range_nm, msg_rate]`

Daily max range resets at local midnight. `msg_rate` is messages/second from
`/data/stats.json`.

#### `ts`

Current time as `"HH:MM"` UTC. Timezone conversion to display time happens in the
Liquid template, driven by a plugin setting on the TRMNL side.

#### Units / timezone

Not included in the payload. Unit conversion (ft→m, kt→km/h) and timezone offset
happen in the Liquid template, driven by plugin settings on the TRMNL side. All
timestamps in the payload are UTC.

### Dynamic serializer

Fits as much data as possible within the tier budget — no fixed plane/history
limits. Algorithm (planes sorted by distance ascending):

1. Reserve fixed overhead: `hn`, `hr`, `s`, `fc`, `ts`, JSON wrapper (~280 bytes).
2. Add planes one by one, measuring actual serialized byte cost before committing.
3. If `TRAILS_ENABLED=true`, add trails for closest planes first; each trail
   measured and committed only if it fits. Trails are the first thing dropped.
4. History trimmed from the oldest end last if still over budget.

`TIER` sets the budget: `standard` = 2048 bytes, `plus` = 5120 bytes. Plane count
and trail depth are automatic consequences — not configured directly.

`HISTORY_TIMEFRAME` sets the rolling window depth. Point count =
`timeframe / POLL_INTERVAL_SECONDS` (e.g. `2h` at 300 s = 24 points). The
serializer trims to fit if the budget requires it.

The serializer exposes `X-Payload-Budget` and `X-Payload-Used` response headers for
layout debugging.

### Budget reference (standard tier, ~typical)

| Field | Bytes |
|---|---|
| 22 planes × ~55 bytes (no trail) | ~1210 |
| 5 trail arrays × ~30 bytes each | ~150 |
| `hn` 24 points | ~80 |
| `hr` 24 points | ~95 |
| `s` array | ~28 |
| `fc` coords | ~22 |
| `ts` + JSON wrapper | ~55 |
| **Total** | **~1640** |

~400 bytes headroom on standard tier. TRMNL+ (5 KB) allows ~40 planes + 48-point
history comfortably.

---

## Features unique to ultrafeeder vs public API

| Feature | Public API | Ultrafeeder |
|---|---|---|
| Rate limits | 10–30 req/hr | None (local LAN) |
| Source type | Unknown | ADS-B / MLAT / TIS-B |
| Signal strength (RSSI) | No | Yes |
| Explicit emergency type | Inferred from squawk | Direct from transponder |
| Nav modes (autopilot, approach) | No | Yes |
| Geometric altitude | No | Yes |
| Message count / freshness | No | Yes |
| Position integrity (NIC, NACp) | No | Yes |
| Feeder stats (msg/s, range) | No | Yes |
| Offline operation | No | Yes (LAN only) |

---

## Container structure

```
backend/
├── main.py           # scheduler: poll ultrafeeder → update state → push webhook
├── state.py          # in-memory data model + rolling history deque
├── serializer.py     # webhook_payload(state) — dynamic, budget-aware
├── ultrafeeder.py    # client for /data/aircraft.json + /data/stats.json
├── enrichment.py     # route lookup (adsbdb)
├── history.py        # rolling deque keyed by HISTORY_TIMEFRAME
└── enrichment.py     # adsbdb route lookup — in-process cache, 4 h TTL, backoff
docker-compose.yml
.env.example
Dockerfile
requirements.txt
```

---

## Display concepts

### Radar + stats layout

```
┌─────────────────────────────┬──────────┐
│                             │  Stats   │
│                             │          │
│       Radar  (70 × 70%)     │  42 ac   │
│                             │  8 MLAT  │
│                             │ 247nm ↑  │
│                             │ 1250 m/s │
├─────────────────────────────┴──────────┤
│  ▂▃▄▆▇█▇▅▄▃▂▄▅▇   ▃▄▅▆▇█▇▅▄▃▅▆       │
│  Planes (2h)       Range (2h)   14:32  │
└────────────────────────────────────────┘
```

- **Radar panel** — 70% width × 70% height. CSS absolute-positioned dots projected
  from lat/lon (`ac[6]`/`ac[7]`). Feeder at centre (`fc`). Trail dots smaller
  behind each plane symbol. Scale configurable via plugin setting.
- **Stats panel** — right strip (~30% width). Counts, max range, msg rate,
  emergency badge if active.
- **Graph panel** — bottom strip (~30% height). Dual sparklines from `hn` / `hr`.
  Window label matches `HISTORY_TIMEFRAME`. Timestamp bottom-right, timezone-converted
  in Liquid from the UTC `ts` value.

Dot brightness = altitude band. `⚠` overlay = emergency. `~` = MLAT source.

---

## Open questions

- Route enrichment (adsbdb) — include in v1 or ship without and add later?