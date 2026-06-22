# ERCOT Zonal vs Global Load Scaling Example

** A more thorough discussion alongside several experiments are handled in
`/compute/experiments/zonal_load` **.

Walkthrough of what we're doing in
`/compute/operating_data_adapter.py:_scale_loads*()`.

Purpose of all this is to apply the scale factors to the loads at the bus level.

This has nothing to do with the 4 zones comprising "bus_load_zone" - this is a
historic misnomer. ERCOT's context for "bus load zones" are pricing zones; e.g.
nodal hub pricing, CRR's, DA settlements.


## TAMU Snapshot (static)

```
┌────────┬──────────┬────────────────┬────────────────────┐
│ Bus    │ Zone     │ TAMU load (MW) │ Within-zone share  │
├────────┼──────────┼────────────────┼────────────────────┤
│ Bus A  │ Houston  │ 700            │ 20%                │
│ Bus B  │ Houston  │ 1,050          │ 30%                │
│ Bus C  │ Houston  │ 1,750          │ 50%                │
│                                                         │
│ Total  │ Houston  │ 3,500          │                    │
│                                                         │
│ Bus D  │ West     │ 400            │ 50%                │
│ Bus E  │ West     │ 400            │ 50%                │
│                                                         │
│ Total  │ West     │ 800            │                    │
│                                                         │
│ TAMU grand total  │ 4,300          │                    │
└────────┴──────────┴────────────────┴────────────────────┘
```

## ERCOT This Hour

```
┌─────────┬─────────────────┐
│ Zone    │ ERCOT load (MW) │
├─────────┼─────────────────┤
│ Houston │ 6,300           │
│ West    │ 450             │
│                           │
│ Total   │ 6,750           │
└─────────┴─────────────────┘
```

## Scale Factors
```
┌────────────────────────────────────────────────────────┐
│               Old (global)   │  New (per-zone)         │
├────────────────────────────────────────────────────────┤
│ Formula    6,750/4,300=1.57  │  Houston: 6300/3500=1.80│
│                              │  West:     450/ 800=0.56│
└────────────────────────────────────────────────────────┘
```

## Result
```
┌────────┬──────────┬─────────────────┬─────────────────┬────────────────────┐
│ Bus    │ Zone     │ Old (x1.57) MW  │ New MW          │ Within-zone share  │
├────────┼──────────┼─────────────────┼─────────────────┼────────────────────┤
│ Bus A  │ Houston  │ 1,099           │ 700  x1.80=1,260│ 20% <- unchanged   │
│ Bus B  │ Houston  │ 1,649           │ 1050 x1.80=1,890│ 30% <- unchanged   │
│ Bus C  │ Houston  │ 2,748           │ 1750 x1.80=3,150│ 50% <- unchanged   │
│                                                                            │
│ Total  │ Houston  │ 5,496  (X)      │ 6,300  (✓)      │                    │
│                                                                            │
│ Bus D  │ West     │ 628             │ 400  x0.56= 224 │ 50% <- unchanged   │
│ Bus E  │ West     │ 628             │ 400  x0.56= 224 │ 50% <- unchanged   │
│                                                                            │
│ Total  │ West     │ 1,256  (X)      │ 448 ~450 (✓)    │                    │
│                                                                            │
│ Grand total       │ 6,752  (✓)      │ 6,748  (✓)      │                    │
└────────┴──────────┴─────────────────┴─────────────────┴────────────────────┘
```

Global Factor: grand total correct but zone geography wrong (West 3x too high,
Houston 13% too low).

Zonal Factor: zone totals and grand total both match ERCOT. Within-zone bus
distribution (TAMU's spatial pattern) is fully preserved.
