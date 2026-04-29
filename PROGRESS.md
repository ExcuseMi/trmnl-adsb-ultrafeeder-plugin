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
- [x] `plugin/src/transform.js` — lat/lon → x/y projection, unit conversion
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
- [ ] `trmnlp init plugin` — must be run manually to assign a plugin ID
- [ ] `trmnlp push` — push plugin to TRMNL after init
- [ ] Route enrichment is included (adsbdb); can be disabled via `ROUTE_DISPLAY=off`
- [ ] Docker image not yet published to ghcr.io
- [ ] `version.json` not yet created
- [ ] GitHub Actions workflows not yet created (latest version docker image)

## Key decisions
- Webhook push model: container polls ultrafeeder, pushes to TRMNL on schedule
- No Redis — all state in-memory (deque for history, dict for aircraft)
- Route enrichment (adsbdb) included in v1, disabled with `ROUTE_DISPLAY=off`
- transform.js computes radar x/y projection from lat/lon (no server-side calc in template)
- Budget algorithm: planes sorted by distance, trails added for closest if budget allows
