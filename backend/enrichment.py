import asyncio
import re
import time
import logging
import aiohttp

log = logging.getLogger(__name__)

ADSBDB_BASE = 'https://api.adsbdb.com/v0/callsign/'
TTL = 4 * 3600

_cache: dict[str, tuple] = {}  # callsign -> (route_or_None, expires_at)
_backoff_until: float = 0.0
_sem: asyncio.Semaphore | None = None


def _valid(cs: str) -> bool:
    return bool(cs and len(cs) >= 4 and re.match(r'^[A-Z]{2,3}\d', cs))


def _label(airport: dict, mode: str) -> str:
    if not airport or mode == 'off':
        return ''
    if mode == 'cities':
        city = (airport.get('municipality') or '')[:20].upper()
        country = airport.get('country_iso_name', '')
        return f'{city} ({country})' if city and country else city or country
    return airport.get('iata_code') or airport.get('icao_code', '')


async def _fetch_one(cs: str, session: aiohttp.ClientSession) -> dict | None:
    global _backoff_until, _sem
    if _sem is None:
        _sem = asyncio.Semaphore(3)

    if time.monotonic() < _backoff_until:
        return None

    cached, expires = _cache.get(cs, (None, 0))
    if time.monotonic() < expires:
        return cached

    try:
        async with _sem:
            async with session.get(
                f'{ADSBDB_BASE}{cs}',
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
                    _cache[cs] = (route, time.monotonic() + TTL)
                    return route
                _cache[cs] = (None, time.monotonic() + TTL)
    except Exception as exc:
        log.debug('adsbdb %s: %s', cs, exc)
    return None


def _route_string(route: dict, mode: str) -> str | None:
    o = _label(route.get('origin', {}), mode)
    d = _label(route.get('destination', {}), mode)
    return f'{o}>{d}' if o and d else None


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


async def _maybe_fetch(cs: str, session: aiohttp.ClientSession) -> dict | None:
    return await _fetch_one(cs, session) if _valid(cs) else None


async def enrich(aircraft: list[dict], mode: str, session: aiohttp.ClientSession) -> None:
    if mode == 'off' or not aircraft:
        return

    callsigns = [a['callsign'] for a in aircraft]
    routes = await asyncio.gather(
        *[_maybe_fetch(cs, session) for cs in callsigns],
        return_exceptions=True,
    )

    for plane, route in zip(aircraft, routes):
        if not route or isinstance(route, Exception):
            continue
        rt = _route_string(route, mode)
        prog = _progress(plane, route)
        if rt:
            plane['route'] = rt
        if prog is not None:
            plane['progress'] = prog
