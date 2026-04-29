import json
import math

TIER_BUDGET = {'standard': 2048, 'plus': 5120}


def _size(obj) -> int:
    return len(json.dumps(obj, separators=(',', ':')))


def _build_entry(plane: dict) -> list:
    # 11 fixed fields. Absent optional fields use 0 (not null) — TRMNL strips null from
    # JSON arrays, which would collapse indices and shift every field after the first absent one.
    # [0]=callsign [1]=type [2]=alt [3]=spd [4]=trk [5]=src [6]=lat [7]=lon
    # [8]=origin   [9]=dest [10]=desc
    ac_type = (plane.get('type', '') or '').strip()
    if ac_type.lower() in ('adsb_icao', 'mode_s', 'tis-b', 'ads-r', 'unknown', ''):
        ac_type = ''
    return [
        plane.get('callsign', '') or '',  # 0
        ac_type or '',                    # 1
        plane.get('altitude', 0) or 0,         # 2
        plane.get('speed', 0) or 0,            # 3
        plane.get('track', 0) or 0,            # 4
        plane.get('source', 0) or 0,           # 5
        round(plane['lat'], 4) or 9,           # 6
        round(plane['lon'], 4) or 0,           # 7
        plane.get('origin', '') or '',         # 8 — 0 if absent
        plane.get('dest', '') or '',           # 9 — 0 if absent
        plane.get('desc', '') or '',           # 10 — 0 if absent
    ]


def build_payload(state, tier: str = 'standard') -> dict:
    budget = TIER_BUDGET.get(tier, 2048)
    hn = list(state.hn_history)
    hr = list(state.hr_history)
    s = state.stats
    hm = list(state.hm_history)
    cos_f = round(math.cos(math.radians(state.feeder_lat)), 6)
    fc = [state.feeder_lat, state.feeder_lon, cos_f]
    ts = state.timestamp
    hn_max = max(hn) if hn else 0
    hr_max = max(hr) if hr else 0
    hm_max = max(hm) if hm else 0
    ts_start = state.ts_start
    aircraft = state.sorted_aircraft()

    def total_size(ac_list):
        return _size({
            'merge_variables': {
                'ac': ac_list, 'hn': hn, 'hr': hr, 'hm': hm, 's': s,
                'fc': fc, 'ts': ts, 'hn_max': hn_max, 'hr_max': hr_max,
                'hm_max': hm_max, 'ts_start': ts_start,
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
        if not trimmed:
            break

    used = total_size(ac_entries)

    return {
        'merge_variables': {
            'ac': ac_entries, 'hn': hn, 'hr': hr, 'hm': hm, 's': s,
            'fc': fc, 'ts': ts, 'hn_max': hn_max, 'hr_max': hr_max,
            'hm_max': hm_max, 'ts_start': ts_start,
        },
        '_budget': budget,
        '_used': used,
    }
