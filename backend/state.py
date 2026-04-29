from collections import deque
from datetime import datetime, timezone


class AppState:
    def __init__(self, feeder_lat: float, feeder_lon: float, max_history: int):
        self.feeder_lat = feeder_lat
        self.feeder_lon = feeder_lon
        self.aircraft: dict[str, dict] = {}
        self.hn_history: deque = deque(maxlen=max_history)
        self.hr_history: deque = deque(maxlen=max_history)
        self._day_max_range: float = 0.0
        self._day_date: str = ''
        self.timestamp: str = '00:00'
        self._stats: list = [0, 0, 0, 0, 0]

    @property
    def stats(self) -> list:
        return self._stats

    def update(self, parsed: list[dict], msg_rate: int) -> None:
        now = datetime.now(timezone.utc)
        today = now.strftime('%Y-%m-%d')
        self.timestamp = now.strftime('%H:%M')

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

    def sorted_aircraft(self) -> list[dict]:
        return sorted(self.aircraft.values(), key=lambda x: x['dist_nm'])
