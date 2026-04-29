import asyncio
import logging
import os
import aiohttp
from quart import Quart, jsonify

from state import AppState
from serializer import build_payload
from ultrafeeder import fetch_aircraft, fetch_stats, parse_aircraft, parse_rf_stats
from enrichment import enrich

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger(__name__)

app = Quart(__name__)

ULTRAFEEDER_URL     = os.getenv('ULTRAFEEDER_URL', 'http://ultrafeeder')
FEEDER_LAT          = float(os.getenv('FEEDER_LAT', '51.1234'))
FEEDER_LON          = float(os.getenv('FEEDER_LON', '4.5678'))
TRMNL_WEBHOOK_URL   = os.getenv('TRMNL_WEBHOOK_URL', '')
TIER                = os.getenv('TIER', 'standard')
POLL_INTERVAL       = int(os.getenv('POLL_INTERVAL_SECONDS', '300'))
HISTORY_TIMEFRAME   = os.getenv('HISTORY_TIMEFRAME', '2h')
ROUTE_DISPLAY       = os.getenv('ROUTE_DISPLAY', 'codes')
STATE_PATH          = os.getenv('STATE_PATH', '/data/state.json')

_state: AppState | None = None
_last_poll: float = 0.0


def _parse_timeframe(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith('h'):
        return int(tf[:-1]) * 3600
    if tf.endswith('m'):
        return int(tf[:-1]) * 60
    return int(tf)


async def _poll_and_push() -> None:
    global _last_poll
    _last_poll = asyncio.get_event_loop().time()

    try:
        async with aiohttp.ClientSession() as session:
            raw_ac, raw_stats = await asyncio.gather(
                fetch_aircraft(session, ULTRAFEEDER_URL),
                fetch_stats(session, ULTRAFEEDER_URL),
            )

            parsed = parse_aircraft(raw_ac, FEEDER_LAT, FEEDER_LON)
            msg_rate, strong, pos_min, gain_db = parse_rf_stats(raw_stats)
            log.info('rf stats: msg/s=%d strong=%d pos=%d gain=%ddB', msg_rate, strong, pos_min, gain_db)

            await enrich(parsed, ROUTE_DISPLAY, session)

            _state.update(parsed, msg_rate, strong, pos_min, gain_db)

            payload = build_payload(_state, TIER)
            budget = payload.pop('_budget', 0)
            used = payload.pop('_used', 0)

            if not TRMNL_WEBHOOK_URL:
                log.info('No TRMNL_WEBHOOK_URL — skipping push (%d ac, %d/%d bytes)', len(parsed), used, budget)
                return

            async with session.post(
                TRMNL_WEBHOOK_URL,
                json=payload,
                headers={
                    'Content-Type': 'application/json',
                    'X-Payload-Budget': str(budget),
                    'X-Payload-Used': str(used),
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                log.info('push: HTTP %d | %d ac | %d/%d bytes', resp.status, len(parsed), used, budget)

    except Exception as exc:
        log.error('poll/push error: %s', exc)


async def _scheduler() -> None:
    while True:
        await _poll_and_push()
        await asyncio.sleep(POLL_INTERVAL)


@app.before_serving
async def startup() -> None:
    global _state
    tf_s = _parse_timeframe(HISTORY_TIMEFRAME)
    max_points = max(1, tf_s // POLL_INTERVAL)
    _state = AppState(FEEDER_LAT, FEEDER_LON, max_points, STATE_PATH)
    log.info(
        'start: feeder=(%s,%s) tier=%s interval=%ds history=%d pts',
        FEEDER_LAT, FEEDER_LON, TIER, POLL_INTERVAL, max_points,
    )
    asyncio.create_task(_scheduler())


@app.route('/health')
async def health():
    return jsonify({
        'status': 'ok',
        'aircraft': len(_state.aircraft) if _state else 0,
        'last_poll': _last_poll,
        'tier': TIER,
        'interval': POLL_INTERVAL,
    })
