import math
import logging
import aiohttp

log = logging.getLogger(__name__)

AIRCRAFT_PATH = '/data/aircraft.json'
STATS_PATH = '/data/stats.json'


def _source(ac: dict) -> int:
    mlat = ac.get('mlat') or []
    tisb = ac.get('tisb') or []
    if 'lat' in mlat or 'lon' in mlat:
        return 1  # MLAT
    if 'lat' in tisb or 'lon' in tisb:
        return 2  # TIS-B
    return 0  # ADS-B


def _emergency(ac: dict) -> str | None:
    em = ac.get('emergency', 'none') or 'none'
    if em != 'none':
        return em
    sq = ac.get('squawk', '') or ''
    if sq in ('7500', '7600', '7700'):
        return sq
    return None


async def fetch_aircraft(session: aiohttp.ClientSession, base_url: str) -> list[dict]:
    try:
        async with session.get(
            f'{base_url}{AIRCRAFT_PATH}',
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
            aircraft = data.get('aircraft', [])
            log.info('ultrafeeder: %d aircraft', len(aircraft))
            return aircraft
    except Exception as exc:
        log.warning('fetch_aircraft failed: %s', exc)
        return []


async def fetch_stats(session: aiohttp.ClientSession, base_url: str) -> dict:
    try:
        async with session.get(
            f'{base_url}{STATS_PATH}',
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)
    except Exception as exc:
        log.debug('fetch_stats failed: %s', exc)
        return {}


def parse_aircraft(raw: list[dict], feeder_lat: float, feeder_lon: float) -> list[dict]:
    NM_PER_DEG = 60.0
    cos_lat = math.cos(math.radians(feeder_lat))
    result = []

    for ac in raw:
        lat = ac.get('lat')
        lon = ac.get('lon')
        if lat is None or lon is None:
            continue

        alt = ac.get('alt_baro')
        alt = -1 if alt == 'ground' else (int(alt) if alt is not None else 0)

        dlat = lat - feeder_lat
        dlon = (lon - feeder_lon) * cos_lat
        dist_nm = round(math.sqrt(dlat ** 2 + dlon ** 2) * NM_PER_DEG, 1)

        raw_type = (ac.get('t') or ac.get('type') or '').strip()
        if raw_type.lower() in ('adsb_icao', 'mode_s', 'tis-b', 'ads-r'):
            raw_type = ''

        result.append({
            'hex':       ac.get('hex', ''),
            'callsign':  (ac.get('flight') or '').strip(),
            'type':      raw_type,
            'altitude':  alt,
            'speed':     int(ac.get('gs') or 0),
            'track':     int(ac.get('track') or 0),
            'source':    _source(ac),
            'lat':       round(lat, 4),
            'lon':       round(lon, 4),
            'emergency': _emergency(ac),
            'dist_nm':   dist_nm,
        })

    result.sort(key=lambda x: x['dist_nm'])
    return result


def parse_msg_rate(stats: dict) -> int:
    try:
        stats_list = stats.get('stats', [])
        if not stats_list:
            return 0
        last = stats_list[-1]
        accepted = last.get('local', {}).get('accepted', [])
        if isinstance(accepted, list):
            return int(sum(accepted) / 60)
        if isinstance(accepted, (int, float)):
            return int(accepted / 60)
    except Exception:
        pass
    return 0
