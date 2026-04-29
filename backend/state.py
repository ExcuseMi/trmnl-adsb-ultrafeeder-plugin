import json
import logging
import os
import tempfile
from collections import deque
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class AppState:
    def __init__(self, feeder_lat: float, feeder_lon: float, max_history: int, state_path: str = ''):
        self.feeder_lat = feeder_lat
        self.feeder_lon = feeder_lon
        self._max_history = max_history
        self._state_path = state_path
        self.aircraft: dict[str, dict] = {}
        self.hn_history: deque = deque(maxlen=max_history)
        self.hr_history: deque = deque(maxlen=max_history)
        self._day_max_range: float = 0.0
        self._day_date: str = ''
        self.timestamp: int = 0
        self._stats: list = [0, 0, 0, 0, 0]
        if state_path:
            self._load()

    @property
    def stats(self) -> list:
        return self._stats

    def update(self, parsed: list[dict], msg_rate: int) -> None:
        now = datetime.now(timezone.utc)
        today = now.strftime('%Y-%m-%d')
        self.timestamp = int(now.timestamp())

        if today != self._day_date:
            self._day_max_range = 0.0
            self._day_date = today

        seen = set()
        for ac in parsed:
            h = ac['hex']
            seen.add(h)
            if h in self.aircraft:
                prev = self.aircraft[h]
                trail = prev.get('_trail', deque(maxlen=20))
                trail.append((prev['lat'], prev['lon']))
                ac['_trail'] = trail
            else:
                ac['_trail'] = deque(maxlen=20)
            self.aircraft[h] = ac

        for h in list(self.aircraft):
            if h not in seen:
                del self.aircraft[h]

        ranges = [a['dist_nm'] for a in parsed if a['dist_nm'] > 0]
        max_range = max(ranges) if ranges else 0

        self.hn_history.append(len(parsed))
        self.hr_history.append(int(max_range))

        if max_range > self._day_max_range:
            self._day_max_range = max_range

        mlat = sum(1 for a in parsed if a['source'] == 1)
        self._stats = [len(parsed), mlat, int(max_range), int(self._day_max_range), msg_rate]
        self._save()

    def sorted_aircraft(self) -> list[dict]:
        return sorted(self.aircraft.values(), key=lambda x: x['dist_nm'])

    def _load(self) -> None:
        try:
            with open(self._state_path) as f:
                d = json.load(f)
            for v in d.get('hn', [])[-self._max_history:]:
                self.hn_history.append(v)
            for v in d.get('hr', [])[-self._max_history:]:
                self.hr_history.append(v)
            self._day_max_range = float(d.get('day_max_range', 0.0))
            self._day_date = d.get('day_date', '')
            log.info('state: loaded %d history points from %s', len(self.hn_history), self._state_path)
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning('state: load failed (%s), starting fresh', exc)

    def _save(self) -> None:
        if not self._state_path:
            return
        d = {
            'hn': list(self.hn_history),
            'hr': list(self.hr_history),
            'day_max_range': self._day_max_range,
            'day_date': self._day_date,
        }
        tmp = self._state_path + '.tmp'
        try:
            with open(tmp, 'w') as f:
                json.dump(d, f)
            os.replace(tmp, self._state_path)
        except Exception as exc:
            log.warning('state: save failed: %s', exc)
