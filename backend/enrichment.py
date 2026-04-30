import asyncio
import json
import logging
import re
import sqlite3
import time
import aiohttp

log = logging.getLogger(__name__)

ADSBDB_CALLSIGN = 'https://api.adsbdb.com/v0/callsign/'
ADSBDB_AIRCRAFT = 'https://api.adsbdb.com/v0/aircraft/'
TTL = 4 * 3600

_db: sqlite3.Connection | None = None
_backoff_until: float = 0.0
_sem: asyncio.Semaphore | None = None


def init_cache(db_path: str) -> None:
    global _db
    _db = sqlite3.connect(db_path, check_same_thread=False)
    _db.execute('PRAGMA journal_mode=WAL')
    _db.execute('''CREATE TABLE IF NOT EXISTS route_cache (
        callsign TEXT PRIMARY KEY,
        data     TEXT,
        expires  REAL NOT NULL
    )''')
    _db.execute('''CREATE TABLE IF NOT EXISTS ac_cache (
        hex         TEXT PRIMARY KEY,
        icao_type   TEXT,
        description TEXT,
        expires     REAL NOT NULL
    )''')
    now = time.time()
    _db.execute('DELETE FROM route_cache WHERE expires < ?', (now,))
    _db.execute('DELETE FROM ac_cache WHERE expires < ?', (now,))
    _db.commit()
    rc = _db.execute('SELECT COUNT(*) FROM route_cache').fetchone()[0]
    ac = _db.execute('SELECT COUNT(*) FROM ac_cache').fetchone()[0]
    log.info('enrichment cache: %d routes, %d aircraft loaded from %s', rc, ac, db_path)


def _get_route(callsign: str):
    if _db is None:
        return None, 0
    row = _db.execute(
        'SELECT data, expires FROM route_cache WHERE callsign = ?', (callsign,)
    ).fetchone()
    if row:
        return (json.loads(row[0]) if row[0] else None), row[1]
    return None, 0


def _set_route(callsign: str, data, expires: float) -> None:
    if _db is None:
        return
    _db.execute(
        'INSERT OR REPLACE INTO route_cache (callsign, data, expires) VALUES (?, ?, ?)',
        (callsign, json.dumps(data) if data is not None else None, expires),
    )
    _db.commit()


def _get_ac(hex_code: str):
    if _db is None:
        return None, 0
    row = _db.execute(
        'SELECT icao_type, description, expires FROM ac_cache WHERE hex = ?', (hex_code,)
    ).fetchone()
    if row:
        return (row[0], row[1]), row[2]
    return None, 0


def _set_ac(hex_code: str, icao_type, description, expires: float) -> None:
    if _db is None:
        return
    _db.execute(
        'INSERT OR REPLACE INTO ac_cache (hex, icao_type, description, expires) VALUES (?, ?, ?, ?)',
        (hex_code, icao_type, description, expires),
    )
    _db.commit()


def _valid(cs: str) -> bool:
    return bool(cs and len(cs) >= 3 and re.match(r'^[A-Z]{1,5}', cs))


def _label(airport: dict, mode: str) -> str:
    if not airport or mode == 'off':
        return ''
    if mode == 'cities':
        city = (airport.get('municipality') or '')[:20].upper()
        country = airport.get('country_iso_name', '')
        return f'{city} ({country})' if city and country else city or country
    return airport.get('iata_code') or airport.get('icao_code', '')


async def _fetch_route(cs: str, session: aiohttp.ClientSession) -> dict | None:
    global _backoff_until, _sem
    if _sem is None:
        _sem = asyncio.Semaphore(3)

    if time.monotonic() < _backoff_until:
        return None

    cached, expires = _get_route(cs)
    if time.time() < expires:
        return cached

    try:
        async with _sem:
            async with session.get(
                f'{ADSBDB_CALLSIGN}{cs}',
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 429:
                    ra = float(resp.headers.get('Retry-After', 60))
                    _backoff_until = time.monotonic() + ra
                    log.warning('adsbdb rate-limited, backoff %.0fs', ra)
                    return None
                if resp.status == 200:
                    fr = (await resp.json()).get('response', {}).get('flightroute')
                    route = {'origin': fr.get('origin') or {}, 'destination': fr.get('destination') or {}} if fr else None
                    _set_route(cs, route, time.time() + TTL)
                    if route:
                        log.info('enriched route: %s', cs)
                    return route
                _set_route(cs, None, time.time() + TTL)
    except Exception as exc:
        log.debug('adsbdb route %s: %s', cs, exc)
    return None


async def _fetch_ac(hex_code: str, session: aiohttp.ClientSession) -> tuple[str | None, str | None]:
    global _backoff_until, _sem
    if _sem is None:
        _sem = asyncio.Semaphore(3)

    hex_code = hex_code.upper()
    if time.monotonic() < _backoff_until:
        return None, None

    cached, expires = _get_ac(hex_code)
    if time.time() < expires:
        return cached  # (icao_type, desc) — both may be None

    try:
        async with _sem:
            async with session.get(
                f'{ADSBDB_AIRCRAFT}{hex_code}',
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 429:
                    ra = float(resp.headers.get('Retry-After', 60))
                    _backoff_until = time.monotonic() + ra
                    return None, None
                if resp.status == 200:
                    data = (await resp.json()).get('response', {})
                    ac_data = data.get('aircraft') or data
                    icao_type = ac_data.get('icao_type') or None
                    manufacturer = (ac_data.get('manufacturer') or '').strip()
                    model = (ac_data.get('type') or ac_data.get('description') or '').strip()
                    if manufacturer and model and not model.lower().startswith(manufacturer.lower()):
                        desc: str | None = f'{manufacturer} {model}'
                    else:
                        desc = model or manufacturer or None
                    if desc:
                        desc = desc[:32]
                    _set_ac(hex_code, icao_type, desc, time.time() + TTL)
                    if icao_type:
                        log.info('enriched type: %s -> %s (%s)', hex_code, icao_type, desc)
                    return icao_type, desc
                _set_ac(hex_code, None, None, time.time() + TTL)
    except Exception as exc:
        log.debug('adsbdb ac %s: %s', hex_code, exc)
    return None, None


def _origin_dest(route: dict, mode: str) -> tuple[str | None, str | None]:
    o = _label(route.get('origin', {}), mode) or None
    d = _label(route.get('destination', {}), mode) or None
    return o, d


def _progress(plane: dict, route: dict) -> int | None:
    try:
        o, d = route['origin'], route['destination']
        olat, olon = float(o['latitude']), float(o['longitude'])
        dlat, dlon = float(d['latitude']), float(d['longitude'])
        total = ((dlat - olat) ** 2 + (dlon - olon) ** 2) ** 0.5
        if total < 1e-6:
            return None
        covered = ((plane['lat'] - olat) ** 2 + (plane['lon'] - olon) ** 2) ** 0.5
        return int(max(0, min(100, covered / total * 100)))
    except (KeyError, TypeError, ValueError):
        return None


async def enrich(aircraft: list[dict], mode: str, session: aiohttp.ClientSession) -> None:
    if not aircraft:
        return

    route_tasks = []
    ac_tasks = []

    for a in aircraft:
        cs = a['callsign']
        if mode != 'off' and _valid(cs):
            route_tasks.append(_fetch_route(cs, session))
        else:
            route_tasks.append(asyncio.sleep(0, result=None))

        if not a.get('type') or not a.get('desc'):
            ac_tasks.append(_fetch_ac(a['hex'], session))
        else:
            ac_tasks.append(asyncio.sleep(0, result=None))

        await asyncio.sleep(0.1)

    results = await asyncio.gather(*(route_tasks + ac_tasks), return_exceptions=True)
    routes = results[:len(aircraft)]
    ac_types = results[len(aircraft):]

    for plane, route, ac_type in zip(aircraft, routes, ac_types):
        if route and not isinstance(route, Exception):
            origin, dest = _origin_dest(route, mode)
            prog = _progress(plane, route)
            if origin:
                plane['origin'] = origin
            if dest:
                plane['dest'] = dest
            if prog is not None:
                plane['progress'] = prog

        if ac_type and not isinstance(ac_type, Exception):
            icao_type, desc = ac_type if isinstance(ac_type, tuple) else (ac_type, None)
            if icao_type:
                plane['type'] = icao_type
            if desc:
                plane['desc'] = desc[:28]
