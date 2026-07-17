"""Render the 'core' paradigm (scratch, plan/0092-0001):
centroid pile vs |SF|^2 geo-median cores, + the hover 'intense components' concept.
Marker hue = violet (constraint identity, deliberately NOT red/blue, which are
reserved for signed drill-down). Severity -> size + opacity.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
pl = json.loads((HERE / "core_payload.json").read_text())
cons = pl["constraints"]
LON0, LON1 = -107.0, -93.0
LAT0, LAT1 = 25.4, 36.6
PAD = 16
kmax = max(c["binding_hours"] for c in cons) or 1
VIOLET = "#a78bfa"


def proj(lat, lon, W, H):
    return (PAD + (lon - LON0) / (LON1 - LON0) * (W - 2 * PAD),
            PAD + (LAT1 - lat) / (LAT1 - LAT0) * (H - 2 * PAD))


def sev(c):
    return (c["binding_hours"] / kmax) ** 0.5


def field_map(key_field, W=560, H=560):
    s = [f'<rect width="{W}" height="{H}" fill="#0a0d12"/>']
    for c in sorted(cons, key=sev):
        x, y = proj(*c[key_field], W, H)
        t = sev(c)
        r = 2.0 + 7.0 * t
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{VIOLET}" '
                 f'fill-opacity="{0.28+0.5*t:.2f}" stroke="#c4b5fd" stroke-width="0.4" '
                 f'stroke-opacity="0.5"/>')
    return f'<svg viewBox="0 0 {W} {H}">{"".join(s)}</svg>'


# hover concept: core marker + its most intense component nodes as spokes
def hover_panel(c, W=300, H=300):
    s = [f'<rect width="{W}" height="{H}" fill="#0a0d12"/>']
    cx, cy = proj(*c["gmed2"], W, H)
    nmax = max(abs(n["sf"]) for n in c["nodes"]) or 1
    for n in c["nodes"]:
        nx, ny = proj(n["lat"], n["lon"], W, H)
        s.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{nx:.1f}" y2="{ny:.1f}" '
                 f'stroke="{VIOLET}" stroke-width="0.8" stroke-opacity="0.35"/>')
    for n in c["nodes"]:
        nx, ny = proj(n["lat"], n["lon"], W, H)
        r = 2 + 5 * (abs(n["sf"]) / nmax) ** 0.5
        s.append(f'<circle cx="{nx:.1f}" cy="{ny:.1f}" r="{r:.1f}" fill="#8b78d0" '
                 f'fill-opacity="0.75" stroke="#0a0d12" stroke-width="0.5"/>')
    # the core marker (the geo-median), drawn on top
    s.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="7" fill="{VIOLET}" '
             f'stroke="#fff" stroke-width="1.5" stroke-opacity="0.85"/>')
    top = c["nodes"][0]
    return (c["key"], top["sp"], f'<svg viewBox="0 0 {W} {H}">{"".join(s)}</svg>')


picks = [c for c in cons if c["key"] in
         ("MCCAMY|BASE CASE", "LPLMK_LPLNE_1|SBWDDBM5", "WESTEX|BASE CASE",
          "LENSW_PUTN2_1|SCISPUT8")]
hovers = "".join(
    f'<figure class="hp"><figcaption><span class="k">{k}</span>'
    f'<span class="sub2">core &rarr; top intense node: {sp}</span></figcaption>{svg}</figure>'
    for (k, sp, svg) in map(hover_panel, picks))

html = f'''<title>Core paradigm — plan/0092-0001</title>
<style>body{{margin:0}}.r{{background:#0f1217;color:#e2e8f0;
font-family:-apple-system,system-ui,sans-serif;padding:20px;max-width:1180px;margin:0 auto}}
h1{{font-size:19px;margin:0 0 5px}}h2{{font-size:15px;margin:26px 0 6px}}
.s{{color:#8899aa;font-size:12.5px;margin:0 0 12px;line-height:1.5}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.card h3{{font-size:13.5px;margin:0 0 3px}}.card p{{color:#8899aa;font-size:11.5px;margin:0 0 7px}}
svg{{display:block;width:100%;border:1px solid #252d3a;border-radius:8px;background:#0a0d12}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}}
.hp{{margin:0;border:1px solid #252d3a;border-radius:8px;overflow:hidden;background:#0a0d12}}
.hp figcaption{{padding:8px 10px;border-bottom:1px solid #1a2029}}
.hp .k{{font-family:"Space Mono",ui-monospace,monospace;font-size:11.5px;font-weight:600}}
.hp .sub2{{display:block;color:#8899aa;font-size:10.5px;margin-top:2px}}
.hp svg{{border:none;border-radius:0}}</style>
<div class="r">
<h1>The 'core' paradigm: cluster each constraint at its intensity core</h1>
<p class="s">Marker at each constraint's <b>|SF|&sup2;-weighted geometric median</b> &mdash; the strongest,
densest region, not the averaged middle. Violet (constraint identity; red/blue reserved for signed
drill-down). Size + opacity = binding severity.</p>
<div class="two">
<div class="card"><h3>Before: |SF|-weighted mean centroid</h3>
<p>50% land within 100&nbsp;km of the state center &mdash; the pile.</p>{field_map("centroid")}</div>
<div class="card"><h3>After: |SF|&sup2; geo-median core</h3>
<p>Only 15% near center; markers pulled onto real regional cores.</p>{field_map("gmed2")}</div>
</div>
<h2>Hover: the core opens to its most intense components</h2>
<p class="s">The core marker (white-ringed) sits on the strongest cluster; hovering reveals the constraint's
top intense settlement points (spokes). This is the drill-in affordance &mdash; still no sign coloring at
the overview level.</p>
<div class="grid">{hovers}</div>
</div>'''

Path(HERE / "core_render.html").write_text(html)
print("wrote core_render.html")
