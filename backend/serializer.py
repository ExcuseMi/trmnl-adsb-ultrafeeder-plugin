import json
import math

TIER_BUDGET = {'standard': 2048, 'plus': 5120}


def _size(obj) -> int:
    return len(json.dumps(obj, separators=(',', ':')))


def _build_entry(plane: dict) -> str:
    # CSV string: callsign,type,alt,spd,trk,src,lat,lon,origin,dest,desc
    # Fixed 11 fields; empty string fields cost 0 chars and are immune to TRMNL null-stripping.
    ac_type = (plane.get('type', '') or '').strip()
    if ac_type.lower() in ('adsb_icao', 'mode_s', 'tis-b', 'ads-r', 'unknown', ''):
        ac_type = ''
    return ','.join([
        plane.get('callsign', '') or '',
        ac_type,
        str(plane.get('altitude', 0) or 0),
        str(plane.get('speed', 0) or 0),
        str(plane.get('track', 0) or 0),
        str(plane.get('source', 0) or 0),
        str(round(plane['lat'], 4)),
        str(round(plane['lon'], 4)),
        plane.get('origin', '') or '',
        plane.get('dest', '') or '',
        plane.get('desc', '') or '',
    ])


def build_payload(state, tier: str = 'standard') -> dict:
    budget = TIER_BUDGET.get(tier, 2048)
    hn = list(state.hn_history)
    hr = list(state.hr_history)
    s = state.stats
    hm = list(state.hm_history)
    hg = list(state.hg_history)
    cos_f = round(math.cos(math.radians(state.feeder_lat)), 6)
    fc = [state.feeder_lat, state.feeder_lon, cos_f]
    ts = state.timestamp
    hn_max = max(hn) if hn else 0
    hr_max = max(hr) if hr else 0
    hm_max = max(hm) if hm else 0
    hg_max = max(hg) if hg else 0
    ts_start = state.ts_start
    aircraft = state.sorted_aircraft()

    def total_size(ac_list):
        return _size({
            'merge_variables': {
                'ac': ac_list, 'hn': hn, 'hr': hr, 'hm': hm, 'hg': hg, 's': s,
                'fc': fc, 'ts': ts, 'hn_max': hn_max, 'hr_max': hr_max,
                'hm_max': hm_max, 'hg_max': hg_max, 'ts_start': ts_start,
            }
        })

    ac_entries: list = []
    for plane in aircraft:
        entry = _build_entry(plane)
        if total_size(ac_entries + [entry]) > budget:
            break
        ac_entries.append(entry)

    while total_size(ac_entries) > budget:
        trimmed = False
        if hn:
            hn.pop(0)
            trimmed = True
        if hr:
            hr.pop(0)
            trimmed = True
        if hm:
            hm.pop(0)
            trimmed = True
        if hg:
            hg.pop(0)
            trimmed = True
        if not trimmed:
            break

    used = total_size(ac_entries)

    return {
        'merge_variables': {
            'ac': ac_entries, 'hn': hn, 'hr': hr, 'hm': hm, 'hg': hg, 's': s,
            'fc': fc, 'ts': ts, 'hn_max': hn_max, 'hr_max': hr_max,
            'hm_max': hm_max, 'hg_max': hg_max, 'ts_start': ts_start,
        },
        '_budget': budget,
        '_used': used,
    }
