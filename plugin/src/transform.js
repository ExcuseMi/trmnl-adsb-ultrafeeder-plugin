function transform(input) {
  var ac       = Array.isArray(input.ac) ? input.ac : [];
  var hn       = Array.isArray(input.hn) ? input.hn : [];
  var hr       = Array.isArray(input.hr) ? input.hr : [];
  var s        = Array.isArray(input.s)  ? input.s  : [];
  var fc       = Array.isArray(input.fc) ? input.fc : [51.0, 4.5];
  var ts       = input.ts || '--:--';

  var cfv      = ((input.trmnl || {}).plugin_settings || {}).custom_fields_values || {};
  var unit     = cfv.unit || 'imperial';
  var scale    = parseFloat(cfv.radar_scale || '200'); // nm radius shown

  var feederLat = fc[0];
  var feederLon = fc[1];
  var NM_PER_DEG = 60.0;
  var cosLat = Math.cos(feederLat * Math.PI / 180);

  var planes = ac.map(function (a) {
    var lat = a[6];
    var lon = a[7];
    var dlat = lat - feederLat;
    var dlon = (lon - feederLon) * cosLat;

    // x/y as percentage of radar panel (50% = centre)
    var x = Math.round((50 + dlon * NM_PER_DEG / scale * 50) * 10) / 10;
    var y = Math.round((50 - dlat * NM_PER_DEG / scale * 50) * 10) / 10;
    x = Math.max(1, Math.min(99, x));
    y = Math.max(1, Math.min(99, y));

    var alt = a[2]; // ft, or -1 for ground
    var spd = a[3]; // kt
    if (unit === 'metric') {
      if (alt > 0) alt = Math.round(alt * 0.3048 / 100) * 100;
      spd = Math.round(spd * 1.852);
    }

    var ab = 0;
    if (alt > 0) {
      if      (alt >= 35000) ab = 7;
      else if (alt >= 25000) ab = 6;
      else if (alt >= 15000) ab = 5;
      else if (alt >= 8000)  ab = 4;
      else if (alt >= 4000)  ab = 3;
      else if (alt >= 1000)  ab = 2;
      else                   ab = 1;
    }

    // Index 8 is trail (array) or null; index 9 is route string; 10 progress; 11 emergency
    var trailRaw = a[8];
    var trail = null;
    if (Array.isArray(trailRaw)) {
      trail = trailRaw.map(function (d) {
        // d = [delta_lat, delta_lon] in 0.001° units
        var tx = Math.round((50 + (dlon + d[1] / 1000) * NM_PER_DEG / scale * 50) * 10) / 10;
        var ty = Math.round((50 - (dlat + d[0] / 1000) * NM_PER_DEG / scale * 50) * 10) / 10;
        return [Math.max(0, Math.min(100, tx)), Math.max(0, Math.min(100, ty))];
      });
    }

    var route    = (typeof a[9]  === 'string') ? a[9]  : null;
    var progress = (typeof a[10] === 'number') ? a[10] : null;
    var em       = (a[11] != null)              ? String(a[11]) : null;

    return {
      cs:    a[0] || '',
      ty:    a[1] || '',
      alt:   alt,
      spd:   spd,
      trk:   a[4] || 0,
      src:   a[5] || 0,
      x:     x,
      y:     y,
      rt:    route,
      prog:  progress,
      em:    em,
      ab:    ab,
      trail: trail
    };
  });

  var hnMax = hn.length ? Math.max.apply(null, hn) : 1;
  var hrMax = hr.length ? Math.max.apply(null, hr) : 1;

  var stats = {
    total:    s[0] || 0,
    mlat:     s[1] || 0,
    range:    s[2] || 0,
    dayRange: s[3] || 0,
    msgRate:  s[4] || 0
  };

  return {
    data: {
      planes:   planes,
      hn:       hn,
      hr:       hr,
      hnBars:   hn.map(function (v) { return Math.round(v / hnMax * 100); }),
      hrBars:   hr.map(function (v) { return Math.round(v / hrMax * 100); }),
      hnMax:    hnMax,
      hrMax:    hrMax,
      stats:    stats,
      fc:       fc,
      ts:       ts,
      unitAlt:  unit === 'metric' ? 'm' : 'ft',
      unitSpd:  unit === 'metric' ? 'km/h' : 'kt'
    }
  };
}
