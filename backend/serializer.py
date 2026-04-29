import json
import math
from collections import deque

TIER_BUDGET = {'standard': 2048, 'plus': 5120}


def _size(obj) -> int:
    return len(json.dumps(obj, separators=(',', ':')))


def _trail_deltas(aircraft: dict) -> list | None:
    trail: deque = aircraft.get('_trail')
    if not trail:
        return None
    clat, clon = aircraft['lat'], aircraft['lon']
    deltas = []
    for lat, lon in reversed(list(trail)):
        dlat = round((lat - clat) * 1000)
        dlon = round((lon - clon) * 1000)
        deltas.append([dlat, dlon])
    return deltas or None


def _build_entry(plane: dict, include_trail: bool) -> list:
    trail = _trail_deltas(plane) if include_trail else None
    route = plane.get('route')
    progress = plane.get('progress')
    emergency = plane.get('emergency')

    # Final safety check for generic types
    ac_type = (plane.get('type', '') or '').strip()
    if ac_type.lower() in ('adsb_icao', 'mode_s', 'tis-b', 'ads-r', 'unknown', ''):
        ac_type = ''

    # Return exactly 12 elements to ensure index stability in Liquid template
    return [
        plane.get('callsign', '') or '', # 0
        ac_type,                         # 1
        plane.get('altitude', 0),        # 2
        plane.get('speed', 0),           # 3
        plane.get('track', 0),           # 4
        plane.get('source', 0),          # 5
        round(plane['lat'], 4),          # 6
        round(plane['lon'], 4),          # 7
        trail,                           # 8: trail
        route,                           # 9: route
        progress,                        # 10: progress
        emergency                        # 11: emergency
    ]


def build_payload(state, tier: str = 'standard', trails_enabled: bool = True) -> dict:
    budget = TIER_BUDGET.get(tier, 2048)
    hn = list(state.hn_history)
    hr = list(state.hr_history)
    s = state.stats
    cos_f = round(math.cos(math.radians(state.feeder_lat)), 6)
    fc = [state.feeder_lat, state.feeder_lon, cos_f]
    ts = state.timestamp
    hn_max = max(hn) if hn else 0
    hr_max = max(hr) if hr else 0
    aircraft = state.sorted_aircraft()

    def total_size(ac_list):
        return _size({
            'merge_variables': {
                'ac': ac_list, 'hn': hn, 'hr': hr, 's': s,
                'fc': fc, 'ts': ts, 'hn_max': hn_max, 'hr_max': hr_max,
            }
        })

    # Phase 1: add planes without trails
    ac_entries: list = []
    for plane in aircraft:
        entry = _build_entry(plane, include_trail=False)
        if total_size(ac_entries + [entry]) > budget:
            break
        ac_entries.append(entry)

    # Phase 2: upgrade to trails for closest planes
    if trails_enabled:
        for i, plane in enumerate(aircraft[:len(ac_entries)]):
            if not plane.get('_trail'):
                continue
            with_trail = _build_entry(plane, include_trail=True)
            trial = ac_entries[:i] + [with_trail] + ac_entries[i + 1:]
            if total_size(trial) <= budget:
                ac_entries[i] = with_trail

    # Phase 3: trim oldest history if needed
    while total_size(ac_entries) > budget:
        trimmed = False
        if hn:
            hn.pop(0)
            trimmed = True
        if hr:
            hr.pop(0)
            trimmed = True
        if not trimmed:
            break

    used = total_size(ac_entries)

    return {
        'merge_variables': {
            'ac': ac_entries, 'hn': hn, 'hr': hr, 's': s,
            'fc': fc, 'ts': ts, 'hn_max': hn_max, 'hr_max': hr_max,
        },
        '_budget': budget,
        '_used': used,
    }
