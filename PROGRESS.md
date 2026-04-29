# PROGRESS

## Status: In Progress

## Completed
- [x] Project design (`project.md`)
- [x] `.gitignore` — `.idea/` excluded
- [x] `backend/ultrafeeder.py` — ultrafeeder client
- [x] `backend/enrichment.py` — adsbdb route lookup
- [x] `backend/state.py` — in-memory state + rolling history
- [x] `backend/serializer.py` — budget-aware webhook serializer
- [x] `backend/main.py` — Quart app + scheduler
- [x] `backend/Dockerfile`
- [x] `backend/requirements.txt`
- [x] `docker-compose.yml`
- [x] `.env.example`
- [x] `plugin/src/settings.yml` — webhook plugin config
- [x] `plugin/src/transform.js` — REMOVED (transform.js does not run for webhook strategy)
- [x] `plugin/src/shared.liquid` — radar + stats + sparklines layout
- [x] `plugin/src/full.liquid`
- [x] `plugin/src/half_horizontal.liquid`
- [x] `plugin/src/half_vertical.liquid`
- [x] `plugin/src/quadrant.liquid`
- [x] `plugin/.trmnlp.yml` — local dev mock data
- [x] `test/transform/run.js`
- [x] `test/transform/package.json`
- [x] `test/transform/data/sample.json`

## Not yet done
- [ ] `trmnlp push` — push templates to TRMNL (plugin ID 296015 assigned)
- [ ] Docker image not yet published to ghcr.io
- [ ] `version.json` not yet created
- [ ] GitHub Actions workflows not yet created
- [ ] Route doesn't work
- [ ] Plane type doesn't work, shows adsb_icao
## Key decisions
- Webhook push model: container polls ultrafeeder, pushes to TRMNL on schedule
- No Redis — all state in-memory; history persisted to STATE_PATH via atomic JSON write
- Route enrichment (adsbdb) included in v1, disabled with `ROUTE_DISPLAY=off`
- transform.js removed — does not run for webhook strategy; projection done in inline template JS
- Backend pushes fc=[lat,lon,cos_factor], hn_max, hr_max so template can project + normalize without server roundtrip
- Radar: inline JS SVG, altitude→opacity bands, callsign labels for closest 10
- Budget algorithm: planes sorted by distance, trails added for closest if budget allows

