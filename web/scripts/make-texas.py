#!/usr/bin/env python3
"""Simplify the Texas state boundary into a light GeoJSON asset for the map.

Source is a 1826-point MultiPolygon; at the app's zoom range (4-14) most of that
detail is sub-pixel. Douglas-Peucker at ~0.004 deg (roughly 400 m) keeps the
Rio Grande's meanders and the Gulf coast readable while cutting the payload.
"""
import json, math

TOLERANCE = 0.004  # degrees
MIN_RING_PTS = 12  # drop slivers (barrier islands) that survive as noise


def perp_dist(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def dp(pts, tol):
    """Iterative Douglas-Peucker; recursion would blow the stack on long rings."""
    if len(pts) < 3:
        return pts[:]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        worst, idx = -1.0, -1
        for k in range(i + 1, j):
            d = perp_dist(pts[k], pts[i], pts[j])
            if d > worst:
                worst, idx = d, k
        if worst > tol:
            keep[idx] = True
            stack.append((i, idx))
            stack.append((idx, j))
    return [p for p, k in zip(pts, keep) if k]


def ring(coords):
    pts = [(round(x, 4), round(y, 4)) for x, y in coords]
    out = dp(pts, TOLERANCE)
    if out[0] != out[-1]:            # GeoJSON rings must close
        out.append(out[0])
    return [[x, y] for x, y in out]


src = json.load(open("4c0a20.json"))
g = src["geometry"]
parts = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]

before = sum(len(r) for p in parts for r in p)
new_parts = []
for poly in parts:
    rings = [ring(r) for r in poly]
    rings = [r for r in rings if len(r) >= MIN_RING_PTS]
    if rings:
        new_parts.append(rings)
after = sum(len(r) for p in new_parts for r in p)

out = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"name": "Texas", "abbr": "TX"},
        "geometry": {"type": "MultiPolygon", "coordinates": new_parts},
    }],
}
blob = json.dumps(out, separators=(",", ":"))
open("texas.geojson", "w").write(blob)
print(f"parts {len(parts)} -> {len(new_parts)}   pts {before} -> {after}   {len(blob)/1024:.1f} KB")

# SVG path in an equirectangular projection, for the specimen mock only.
xs = [c[0] for p in new_parts for r in p for c in r]
ys = [c[1] for p in new_parts for r in p for c in r]
minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
W, H = 420.0, 300.0
sc = min(W / (maxx - minx), H / (maxy - miny))
ox, oy = (W - (maxx - minx) * sc) / 2, (H - (maxy - miny) * sc) / 2
px = lambda x: (x - minx) * sc + ox
py = lambda y: H - ((y - miny) * sc + oy)
d = []
for poly in new_parts:
    for r in poly:
        d.append("M" + "L".join(f"{px(x):.1f},{py(y):.1f}" for x, y in r) + "Z")
open("texas_path.txt", "w").write("".join(d))
json.dump({"minx": minx, "maxx": maxx, "miny": miny, "maxy": maxy,
           "sc": sc, "ox": ox, "oy": oy, "W": W, "H": H},
          open("texas_proj.json", "w"))
print(f"svg path {len(''.join(d))/1024:.1f} KB")
