# TRMNL ADS-B Ultrafeeder Plugin — Project Design

## What this is

A Docker container that sits alongside an existing
[docker-adsb-ultrafeeder](https://github.com/sdr-enthusiasts/docker-adsb-ultrafeeder)
deployment and feeds live aircraft data to a TRMNL e-paper display.

Two delivery paths from one data model:

- **Webhook** — container pushes compact JSON to TRMNL on a schedule. Works from
  any LAN, no inbound ports needed. Constrained to 2 KB (standard) / 5 KB (TRMNL+).
- **REST API** — container exposes a full-fidelity endpoint for BYOS / polling
  setups. No size constraints. Same in-memory data, different serializer.

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
      - TRMNL_WEBHOOK_URL=${TRMNL_WEBHOOK_URL}
      - POLL_INTERVAL_SECONDS=300             # 300 = safe for standard (12/hr), 120 for TRMNL+
      - RADIUS_NM=100
      - MAX_PLANES=22                         # reduced from 35 when trails enabled
      - TRAIL_PLANES=5                        # how many closest planes get trail history
      - TRAIL_POINTS=3                        # position history depth per trailed plane
      - HISTORY_POINTS=24                     # sparkline depth (24 × 5min = 2hr)
```

For the REST/BYOS path, add a new ingress rule to `cloudflared/config.yml`:

```yaml
- hostname: skywatch.bettens.dev   # new dedicated hostname, no Cloudflare Access policy
  service: http://trmnl-adsb:8080
```

The existing `adsb.bettens.dev` (tar1090 map) stays protected by Cloudflare Access
and is never touched.

---

## Privacy

The receiver's lat/lon (home address) is **never included in any outbound payload**.

- Webhook and REST API return plane data only.
- Center coordinates live in the TRMNL plugin settings (user-side), sent as query
  params to the REST endpoint: `?lat=51.12&lon=4.56&radius=100`.
- The REST endpoint uses those params for distance filtering and projection — they
  are not stored or logged.

---

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

#### `s` — feeder stats

`[total_ac, mlat_count, range_nm, day_max_range_nm, msg_rate]`

Daily max range resets at local midnight. `msg_rate` is messages/second from
`/data/stats.json`.

#### `ts`

Current time as `"HH:MM"` (local time of the container). No timezone — display
label only.

#### Units

Not included in the payload. Unit conversion (ft→m, kt→km/h) happens in the
Liquid template or `transform.js`, driven by a plugin setting on the TRMNL side.

### 2 KB budget breakdown

| Field | Bytes |
|---|---|
| 22 planes × ~55 bytes (no trail) | ~1210 |
| 5 trail arrays × ~35 bytes each | ~175 |
| `hn` 24 points | ~80 |
| `hr` 24 points | ~95 |
| `s` array | ~28 |
| `ts` + JSON wrapper | ~55 |
| **Total** | **~1643** |

~400 bytes headroom on standard tier. TRMNL+ (5 KB) allows ~40 planes + 48-point
history comfortably.

### REST API

Same in-memory state, no size constraints.

```json
{
  "aircraft": [
    {
      "flight":    "BAW123",
      "type":      "A320",
      "alt_baro":  35000,
      "alt_geom":  35225,
      "gs":        450,
      "track":     245,
      "src":       "adsb",
      "rssi":      -18.5,
      "nic":       8,
      "nac_p":     9,
      "emergency": "none",
      "nav_modes": ["autopilot", "althold"],
      "lat":       51.1234,
      "lon":       4.5678,
      "trail": [
        {"lat": 51.1104, "lon": 4.5498, "ts": "14:27"},
        {"lat": 51.0974, "lon": 4.5318, "ts": "14:22"},
        {"lat": 51.0844, "lon": 4.5138, "ts": "14:17"}
      ],
      "origin":   "LHR",
      "dest":     "AMS",
      "progress": 0.45
    }
  ],
  "history": [
    {"ts": "09:00", "count": 12, "range_nm": 45},
    {"ts": "09:05", "count": 18, "range_nm": 72}
  ],
  "stats": {
    "total":           42,
    "adsb":            34,
    "mlat":            8,
    "tisb":            0,
    "range_nm":        180,
    "day_max_range_nm":247,
    "msg_rate":        1250
  },
  "fetched_at": "2026-04-29T14:32:00Z"
}
```

REST gets: full field names, `rssi`, `nic`, `nac_p`, `nav_modes`, `alt_geom`,
`trail` with timestamps, named `history` with timestamps, airport list (future),
`fetched_at` ISO timestamp.

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
app/
├── main.py           # scheduler: poll ultrafeeder → update state → push webhook
├── api.py            # FastAPI: GET / → REST payload
├── state.py          # in-memory data model + rolling history deque
├── serializers.py    # webhook_payload(state, tier) / rest_payload(state)
├── ultrafeeder.py    # client for /data/aircraft.json + /data/stats.json
├── enrichment.py     # route lookup (adsbdb), airport filter (OurAirports)
└── history.py        # rolling deque, daily max range tracker
Dockerfile
requirements.txt
```

One data model (`state.py`), two serializers. The webhook scheduler and REST
endpoint both read from the same in-memory `State` object.

---

## Display concepts

### List view (webhook)

```
BAW123  A320  35000ft  450kt  ↗  LHR→AMS  ████░
~EZY42  A319  12000ft  380kt  ↑            ██░░░
        C172   2500ft   95kt  ↖

Plane count (2h)          Range (2h)
▂▃▄▆▇█▇▅▄▃▂▄▅▇          ▃▄▅▆▇█▇▅▄▃▅▆

42 ac · 8 MLAT · 247nm today · 14:32
```

`~` prefix = MLAT (interpolated position). Progress bar = route completion.
Brightness = altitude. Row `⚠` = emergency.

### Radar view (REST / BYOS)

CSS absolute-positioned dots projected from lat/lon. Trail dots rendered smaller
behind each plane symbol. Center = plugin settings lat/lon. Scale configurable.

---

## Open questions

- Route enrichment (adsbdb) — include in v1 or ship without and add later?
- Airport markers — include in REST v1, skip webhook entirely
- TRMNL+ auto-detection — configure tier in env or detect from 429 responses?
- Radar view — webhook template or REST/BYOS only?