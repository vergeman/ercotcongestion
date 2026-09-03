# `/about` — data handoff (§3.5 always-on constraints + §6 case studies)

Concrete, pulled-from-prod numbers for the two data-dependent sections of
`AboutPage.outline.md`. **Real data only — do not invent past what's here.**

Source: prod `ercot_dam_shadow_prices` (settled DAM shadow prices) + `constraint_geo`
(latest fit window), queried 2026-09-03. Delivery days cut in **America/Chicago**.
Constraint key = `constraint_name | contingency_name`.

---

## §3.5 — The always-on constraints

**Definition used.** Rank every constraint by the number of distinct delivery
days it **appeared** with a nonzero settled shadow price, over a trailing window.
This mirrors the Brief's chronic/standout logic (`api/services/analysis/panels/constraints.py`,
`_settled_constraint_history` → trailing-day Σμ, chronic-bound-days count).

⚠️ **CAVEAT (honor this wording).** "Appeared" is a **lower bound** — a constraint
counts as appearing on a day if it shows a nonzero DAM shadow price that day. Say
a constraint *"appeared / was binding on N% of days"*, **never** "bound N times".

### Headline list — trailing 180 days (of 181 delivery days), summer-weighted

| Constraint | Contingency | Days | % days | $/day¹ | Zone | kV | Type |
|---|---|---:|---:|---:|---|---:|---|
| **LPLMK_LPLNE_1** | SBWDDBM5 | 175 | **96.7%** | 533 | West | 115 | transmission |
| HARGRO_TWINBU1_1 | SRUSBIG8 | 175 | 96.7% | 64 | North | 138 | transmission |
| **NELRIO** | BASE CASE | 173 | 95.6% | 95 | South | 345 | GTC |
| HEXT_YELWJC1_1 | DYETRJU8 | 173 | 95.6% | 72 | South | 69 | radial |
| NLARSW_PILONC1_1 | DFOAVLO5 | 171 | 94.5% | 174 | South | 138 | transmission |
| HARGRO_TWINBU1_1 | DBAKCED5 | 171 | 94.5% | 105 | West | 138 | transmission |
| **6437__F** | DMTSCOS5 | 170 | 93.9% | 451 | West | 138 | transmission |
| **E_PASP** | BASE CASE | 163 | 90.1% | 241 | South (El Paso) | 69 | GTC |
| **6830__B** | DGRMGRS8 | 155 | 85.6% | 361 | West | 69 | transmission |
| **LAKENA_SAMATH1_1** | DBAKCED5 | 149 | 82.3% | **1,558** | West | 138 | transmission |
| **BRUNI_69_1** | DFOAVLO5 | 144 | 79.6% | **1,432** | West/South | 69 | transmission |

¹ `$/day` = mean Σ|shadow price| over the days it appeared (magnitude, not a lower bound).

### Full-year robustness (trailing 365 days, of 366) — proves it's not just summer

The same names top the list across a full year of seasons:

| Constraint | Contingency | Days | % days | $/day |
|---|---|---:|---:|---:|
| LPLMK_LPLNE_1 | SBWDDBM5 | 351 | 95.9% | 686 |
| HARGRO_TWINBU1_1 | DBAKCED5 | 348 | 95.1% | 722 |
| 6437__F | DMTSCOS5 | 341 | 93.2% | 599 |
| E_PASP | BASE CASE | 320 | 87.4% | 504 |
| NELRIO | BASE CASE | 315 | 86.1% | 86 |
| BRUNI_69_1 | DFOAVLO5 | 264 | 72.1% | **1,317** |

### The narrative angle for the page

- **The signature payoff:** a handful of West Texas / South Texas 69–138 kV
  constraints (`LPLMK_LPLNE_1`, `6437__F`, `HARGRO_TWINBU1_1`, `E_PASP`,
  `BRUNI_69_1`) are binding on **>90% of delivery days, year-round**. They quietly
  govern regional flow, and no public map shows them.
- **Always-on ≠ always-expensive (worth one sentence).** Some constraints appear
  nearly every day but at trivial price — monitored GTCs like `DIESEL_FMR1`
  (91.7% of days, **~$0/day**) and `THW_AT2T` (90.1%, ~$2/day). Contrast them with
  `LAKENA_SAMATH1_1` / `BRUNI_69_1`: appear ~72–82% of days but carry **$1,300–1,600/day**
  of congestion. "Always-on" and "high-impact" are two different axes — the
  interesting constraints score high on both (`LPLMK_LPLNE_1`, `6437__F`).
- **Geography clusters in the West.** Dominant zone for the high-impact always-on
  set is `west` (Permian/Far West) — consistent with case study "Far West Sign Flip".

**Suggested page copy (safe wording):**
> A handful of transmission limits bind almost every single day. `LPLMK_LPLNE_1`,
> a 115 kV line in West Texas, appeared in the day-ahead solution on **96.7% of
> delivery days over the last six months** — and **95.9% over a full year**. These
> always-on constraints effectively set the regional flow pattern, yet none of
> them appear on any public grid map.

Screenshot target (§3.5 asset): the Brief page's ranked-constraints panel, or
`LPLMK_LPLNE_1` / `6437__F` located on the Map SF overlay (West Texas footprint).

---

## §6 — Case-study dates (from `web/src/lib/events.ts`)

`events.ts` already curates real, described events with windows + cursor timestamps.
These are the case-study candidates. **4 are active, 2 are commented out.** Numbers
below are as authored in `events.ts` (owner-verified event descriptions).

### Active (recommended pool — pick 2–3)

| id | Label | Date | Cursor (UTC) | View | The story |
|---|---|---|---|---|---|
| `rabbit_hill_2025_feb20` | **Rabbit Hill** | Feb 19–21 2025 | 2025-02-20T12:00Z | congestion | Austin suburb radial overload → **+$5,977/MWh at 6am**, collapses to +$242 by noon; widest node spread of the year. Constraint peaked **$7,577 on the 20th vs only $323 the 19th**. |
| `farwest_diurnal_2025_jun20` | **Far West Sign Flip** | Jun 20–21 2025 | 2025-06-21T00:00Z | congestion | Permian congestion **flips sign twice a day**: +$34/MWh overnight (imports across saturated 138 kV) → −$24/MWh midday (5.6 GW local solar saturates export paths). Footprint test. |
| `winter_storm_fern_2026_jan24` | **Winter Storm Fern** | Jan 24–26 2026 | 2026-01-26T12:00Z | congestion | System-wide storm: widest congestion **$1,618/MWh**, peak system λ **$1,915**. RGV wind bottled at **−$1,454**; **PALACIOS_RN at $20,941 at 0600**. Scarcity + congestion together. |
| `pure_congestion_2026_apr26` | **Congestion without scarcity** | Apr 27 2026 | 2026-04-27T17:00Z | congestion | System λ **$7.53/MWh** — almost pure transmission congestion. Houston +$89 while Panhandle −$15; ~8h later solar collapses, λ hits **$490**, map inverts (coast −$123). Three footprints, one map. |

### Commented out in `events.ts` (available if a milder/positive story is wanted)

- `wind_oversupply_2025_jan05` — Jan 4–6 2025: West TX wind ramp → negative system
  prices overnight, then cold snap pushes system price >$70/MWh.
- `winter_scarcity_2025_jan15` — Jan 22 2025: record ~78 GW winter morning peak but
  stable prices — solar+wind placement mitigates. "Not total load, but geographic placement."

### Recommendation for §6 (2–3 case studies)

1. **Rabbit Hill** (Feb 20 2025) — cleanest single-constraint story; extreme,
   localized, one radial line, huge node spread. Best §3→§6 tie-in.
2. **Far West Sign Flip** (Jun 20 2025) — the sign-convention / import-export story
   (§3.4) and footprint-matching, in the West where the always-on constraints live.
3. **Winter Storm Fern** (Jan 25–26 2026) — the system-wide extreme; scarcity vs
   congestion. Highest drama, most recent.

⚠️ **§6 wants graded days** (model-called vs settled, scored vs persistence). The
`events.ts` entries are curated **map-playback** events, not necessarily the
per-day Brief/Scoreboard grades. If the page wants "the model called X, it settled
Y, it scored Z vs persistence," I can pull those grades from the brief_grade
artifacts for whichever 2–3 dates the owner picks — just say which.

---

## Reproduce

Queries live in the job tmp during the run; the shape:
```sql
-- always-on: distinct Chicago delivery days each constraint appeared (nonzero shadow price)
WITH w AS (
  SELECT btrim(constraint_name)||'|'||btrim(contingency_name) AS ckey,
         (interval_ts AT TIME ZONE 'America/Chicago')::date AS dday,
         abs(shadow_price) AS amu
  FROM ercot_dam_shadow_prices
  WHERE interval_ts >= (date '2026-09-03' - 180)::timestamp AT TIME ZONE 'America/Chicago'
    AND interval_ts <  (date '2026-09-03' + 1)::timestamp AT TIME ZONE 'America/Chicago'
    AND shadow_price IS NOT NULL)
SELECT ckey, count(DISTINCT dday) AS days_appeared, sum(amu) AS sum_abs_mu
FROM w GROUP BY ckey ORDER BY days_appeared DESC LIMIT 25;
```
Prod: `kubectl -n ercotstress exec -i postgres-0 -- psql -U ercot -d ercot`
(KUBECONFIG=`~/.kube/config-production-green.yml`).
