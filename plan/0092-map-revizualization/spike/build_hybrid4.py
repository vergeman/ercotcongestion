"""Hybrid v4 INTERACTIVE (scratch, plan/0092-0001): node-membership popover.

Nodes are deduplicated and ALL hoverable. Because a settlement point belongs to
many constraints, hovering it opens a cursor popover listing each constraint it's
in (sorted by |SF|), with its signed role (source=- / sink=+). Click a row to
isolate that constraint. Core dots remain a shortcut to isolate directly.
"""
import json
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

HERE = Path(__file__).parent
pl = json.loads((HERE / "hybrid_payload.json").read_text())
cons = pl["constraints"]
LON0, LON1 = -107.0, -93.0
LAT0, LAT1 = 25.4, 36.6
W = H = 820
PAD = 20
kmax = max(c["binding_hours"] for c in cons) or 1
COL = {"gtc": "#e0a83a", "transmission": "#a78bfa", "radial": "#2dd4bf"}


def proj(lat, lon):
    return (PAD + (lon - LON0) / (LON1 - LON0) * (W - 2 * PAD),
            PAD + (LAT1 - lat) / (LAT1 - LAT0) * (H - 2 * PAD))


def hav(a, b):
    la1, lo1, la2, lo2 = map(radians, [a[0], a[1], b[0], b[1]])
    h = sin((la2-la1)/2)**2 + cos(la1)*cos(la2)*sin((lo2-lo1)/2)**2
    return 2 * 6371.0 * asin(sqrt(min(1, h)))


def sev(c):
    return (c["binding_hours"] / kmax) ** 0.5


rank = {"gtc": 0, "transmission": 1, "radial": 2}
ordered = sorted(cons, key=lambda c: (rank[c["type"]], c["binding_hours"]))

# ---- structure groups (shadows + skeletons + cores), keyed for isolation ----
groups = []
for c in ordered:
    col = COL[c["type"]]
    t = sev(c)
    pts = [proj(n["lat"], n["lon"]) for n in c["nodes"]]
    cx, cy = proj(*c["core"])
    inner = []
    if c["type"] == "gtc":
        nmax = max(abs(n["sf"]) for n in c["nodes"]) or 1
        blobs = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" '
                        f'r="{7+9*(abs(n["sf"])/nmax)**0.5:.1f}"/>'
                        for (x, y), n in zip(pts, c["nodes"]))
        inner.append(f'<g class="shadow" filter="url(#goo)" fill="{col}">{blobs}</g>')
        inner.append(f'<g class="skel" stroke="{col}">' + "".join(
            f'<line x1="{pts[i][0]:.1f}" y1="{pts[i][1]:.1f}" x2="{pts[j][0]:.1f}" y2="{pts[j][1]:.1f}"/>'
            for i, j in c["edges"]) + '</g>')
        inner.append(f'<circle class="core" cx="{cx:.1f}" cy="{cy:.1f}" r="{3.5+3.5*t:.1f}" fill="{col}"/>')
    elif c["type"] == "radial":
        inner.append(f'<circle class="core" cx="{cx:.1f}" cy="{cy:.1f}" r="{3.5+3*t:.1f}" '
                     f'fill="none" stroke="{col}" stroke-width="2"/>')
    else:
        inner.append(f'<g class="skel corridor" stroke="{col}" stroke-width="{0.8+1.8*t:.2f}">' + "".join(
            f'<line x1="{pts[i][0]:.1f}" y1="{pts[i][1]:.1f}" x2="{pts[j][0]:.1f}" y2="{pts[j][1]:.1f}"/>'
            for i, j in c["edges"]
            if hav((c["nodes"][i]["lat"], c["nodes"][i]["lon"]),
                   (c["nodes"][j]["lat"], c["nodes"][j]["lon"])) <= 150) + '</g>')
        inner.append(f'<circle class="core" cx="{cx:.1f}" cy="{cy:.1f}" r="{3+2.5*t:.1f}" fill="{col}"/>')
    hit = f'<circle class="hit" cx="{cx:.1f}" cy="{cy:.1f}" r="12" fill-opacity="0" data-key="{c["key"]}"/>'
    groups.append(f'<g class="con con--{c["type"]}" data-key="{c["key"]}" '
                  f'data-type="{c["type"]}" data-bh="{c["binding_hours"]}">'
                  f'{"".join(inner)}{hit}</g>')

# ---- deduplicated interactive node layer + membership index ----
nodemap = {}
for c in ordered:
    for n in c["nodes"]:
        nd = nodemap.setdefault(n["sp"], {"sp": n["sp"], "lat": n["lat"], "lon": n["lon"], "members": []})
        nd["members"].append({"key": c["key"], "type": c["type"], "sf": round(n["sf"], 4),
                              "bh": c["binding_hours"]})
nodes = list(nodemap.values())
for nd in nodes:
    nd["members"].sort(key=lambda m: -abs(m["sf"]))
node_circles = "".join(
    f'<circle class="node" cx="{proj(nd["lat"], nd["lon"])[0]:.1f}" '
    f'cy="{proj(nd["lat"], nd["lon"])[1]:.1f}" r="3.2" data-ni="{i}"/>'
    for i, nd in enumerate(nodes))

GOO = ('<defs><filter id="goo" x="-30%" y="-30%" width="160%" height="160%">'
       '<feGaussianBlur in="SourceGraphic" stdDeviation="6" result="b"/>'
       '<feColorMatrix in="b" mode="matrix" '
       'values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 20 -9"/></filter></defs>')

data_js = json.dumps([{"sp": nd["sp"], "members": nd["members"]} for nd in nodes])

html = f'''<title>Hybrid v4 node membership — plan/0092-0001</title>
<style>
  body{{margin:0}}
  .r{{background:#0f1217;color:#e2e8f0;font-family:-apple-system,system-ui,sans-serif;
    padding:18px;max-width:1000px;margin:0 auto}}
  h1{{font-size:19px;margin:0 0 5px}}
  .s{{color:#8899aa;font-size:12.5px;margin:0 0 10px;line-height:1.5}}
  .legend{{display:flex;gap:18px;flex-wrap:wrap;font-size:12.5px;color:#c3ccd6;margin:8px 0}}
  .legend .sw{{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:6px}}
  .wrap{{position:relative}}
  svg{{display:block;width:100%;border:1px solid #252d3a;border-radius:8px;background:#0a0d12}}
  .shadow{{opacity:.32}} .skel line{{stroke-opacity:.2;stroke-width:.8}}
  .corridor line{{stroke-opacity:.65}} .core{{stroke:#0a0d12;stroke-width:1;pointer-events:none}}
  .hit{{cursor:pointer}}
  .node{{fill:#c9d3df;fill-opacity:.5;stroke:#0a0d12;stroke-width:.5;cursor:pointer}}
  .node:hover{{fill:#fff;fill-opacity:1;stroke:#38bdf8;stroke-width:1.4}}
  svg.dim .con:not(.iso){{opacity:.06}}
  svg.dim .node{{fill-opacity:.15}}
  .con.iso .shadow{{opacity:.72}} .con.iso .skel line{{stroke-opacity:.9;stroke-width:1.6}}
  .con.iso .core{{stroke:#fff;stroke-width:1.6}} .con{{transition:opacity .12s}}
  .pop{{position:absolute;pointer-events:auto;background:#0f1217f2;border:1px solid #2b3442;
    border-radius:7px;padding:6px;font-size:11.5px;min-width:210px;max-width:290px;
    box-shadow:0 6px 22px #000a;opacity:0;transition:opacity .1s;z-index:5}}
  .pop.on{{opacity:1}}
  .pop .sp{{font-family:"Space Mono",ui-monospace,monospace;font-weight:600;font-size:11.5px;
    padding:2px 5px 6px;color:#e2e8f0;border-bottom:1px solid #222b36;margin-bottom:4px}}
  .pop .sp small{{color:#8899aa;font-weight:400}}
  .row{{display:flex;align-items:center;gap:7px;padding:4px 5px;border-radius:4px;cursor:pointer}}
  .row:hover{{background:#1b2431}}
  .row .chip{{width:8px;height:8px;border-radius:2px;flex:0 0 auto}}
  .row .ck{{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
    font-family:"Space Mono",ui-monospace,monospace;font-size:10.5px}}
  .row .role{{font-weight:700;font-size:10.5px}} .src{{color:#3b82f6}} .snk{{color:#ef4444}}
  .row .bh{{color:#8899aa;font-size:10px;width:34px;text-align:right}}
  .maxnote{{color:#8899aa;font-size:10px;text-align:center;padding:3px}}
</style>
<div class="r">
  <h1>Hybrid v4: hover a node to see every constraint it belongs to</h1>
  <p class="s">Every settlement point (grey dot) is hoverable and deduplicated. Because a node belongs to
  many constraints, hovering opens a popover listing them &mdash; sorted by |SF|, tagged
  <b class="src">source</b> (&minus;) / <b class="snk">sink</b> (+). Click a row to isolate that constraint.
  Hovering a <b>core dot</b> isolates directly. (Overlap is also eased by zoom in the real map.)</p>
  <div class="legend">
    <span><span class="sw" style="background:#e0a83a"></span>GTC / interface</span>
    <span><span class="sw" style="background:#a78bfa"></span>Transmission</span>
    <span><span class="sw" style="background:#2dd4bf"></span>Radial</span>
    <span><span class="sw" style="background:#c9d3df"></span>Settlement point (hover)</span>
  </div>
  <div class="wrap">
    <svg id="map" viewBox="0 0 {W} {H}">{GOO}<rect width="{W}" height="{H}" fill="#0a0d12"/>
      <g id="struct">{''.join(groups)}</g>
      <g id="nodes">{node_circles}</g>
    </svg>
    <div class="pop" id="pop"></div>
  </div>
</div>
<script>
  const NODES = {data_js};
  const COL = {json.dumps(COL)};
  const svg = document.getElementById('map'), pop = document.getElementById('pop'),
        wrap = svg.parentNode;
  const byKey = {{}};
  svg.querySelectorAll('.con').forEach(g => byKey[g.dataset.key] = g);
  let cur = null, pinned = false;
  function iso(key){{
    if(cur) cur.classList.remove('iso');
    cur = key ? byKey[key] : null;
    if(cur){{ svg.classList.add('dim'); cur.classList.add('iso'); }}
    else svg.classList.remove('dim');
  }}
  // core-dot shortcut
  svg.querySelectorAll('.hit').forEach(h =>
    h.addEventListener('mouseenter', () => {{ if(!pinned) iso(h.dataset.key); }}));
  // node popover
  function showPop(ni, cx, cy){{
    const nd = NODES[ni];
    const rows = nd.members.slice(0, 10).map(m => {{
      const src = m.sf < 0;
      return '<div class="row" data-k="'+encodeURIComponent(m.key)+'">'
        + '<span class="chip" style="background:'+COL[m.type]+'"></span>'
        + '<span class="ck">'+m.key+'</span>'
        + '<span class="role '+(src?'src':'snk')+'">'+(src?'src':'snk')
        + ' '+m.sf.toFixed(2)+'</span>'
        + '<span class="bh">'+m.bh+'h</span></div>';
    }}).join('');
    const more = nd.members.length > 10 ? '<div class="maxnote">+'+(nd.members.length-10)+' more</div>' : '';
    pop.innerHTML = '<div class="sp">'+nd.sp+' <small>&middot; '+nd.members.length
      +' constraint'+(nd.members.length>1?'s':'')+'</small></div>'+rows+more;
    const r = svg.getBoundingClientRect(), sx = r.width/{W}, sy = r.height/{H};
    let px = cx*sx + 12, py = cy*sy + 12;
    if(px > r.width-300) px = cx*sx - 300;
    pop.style.left = px+'px'; pop.style.top = py+'px';
    pop.classList.add('on');
    pop.querySelectorAll('.row').forEach(row =>
      row.addEventListener('mouseenter', () => iso(decodeURIComponent(row.dataset.k))));
    pop.querySelectorAll('.row').forEach(row =>
      row.addEventListener('click', () => {{ pinned = true; iso(decodeURIComponent(row.dataset.k)); }}));
  }}
  svg.querySelectorAll('.node').forEach(c => {{
    c.addEventListener('mouseenter', () => {{
      if(pinned) return;
      showPop(+c.dataset.ni, +c.getAttribute('cx'), +c.getAttribute('cy'));
    }});
  }});
  // leaving the whole thing clears (unless pinned)
  wrap.addEventListener('mouseleave', () => {{ if(pinned) return; pop.classList.remove('on'); iso(null); }});
  // click empty map clears pin
  svg.querySelector('rect').addEventListener('click', () => {{ pinned=false; iso(null); pop.classList.remove('on'); }});
</script>'''

Path(HERE / "hybrid4.html").write_text(html)
print("wrote hybrid4.html", f"({len(nodes)} nodes)")
