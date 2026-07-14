# 0087 - ruc-probe-and-ingest

Type: feat
Branch: feat/0087-ruc-probe-and-ingest

**Status: CLOSED. Gates A and B both failed. No data was ingested.**
Ships one file — `compute/mu/ruc_probe.py` — and this verdict.

## What this branch was for

Prove NP5-753/754 (RUC enforced constraints) is (a) archived deep enough to cover
the 46 backtest weeks and (b) joinable to the existing μ keys — **before** a single
row is ingested. Then land the migration, loader, and backfill.

The probe was the gate. It failed, so commits 2–3 (migration 27, `load_ruc_constraints`,
backfill + `live_updater` wiring) **were never written**.

## Verdict

**The RUC arm is dead. It is dead for a reason no amount of ingest effort fixes.**

**1. The products do not exist.** `NP5-753-CD` and `NP5-754-CD` both return **HTTP
404**. They are not on the public-reports API — all 107 products are enumerable and
neither is among them. The only RUC transmission-constraint product on our access
path is **`NP5-755-CD` — Hourly RUC Active and Binding Transmission Constraints**.

**2. Gate A — FAIL (archive depth).** NP5-755's archive holds **1,801 documents
starting 2026-04-30**. Backtest week 1 is **2025-08-14** — the archive falls **259
days short**, covering roughly 9 of the 46 weeks. (The product metadata advertises
`archiveDuration: 2555` days. That field is aspirational, not retention. For
contrast, NP6-86 genuinely reaches 2014-05-01.)

**3. The structural kill — and this is the one that matters.** HRUC runs hourly,
but runs at hours **00:00–15:00 never leave the current operating day**. The first
run that sees delivery day D fires at **16:00 on D-1 — six hours *after* the 10:00
DAM close.** Of 3,959 rows from pre-close runs, **zero** describe a future delivery
day.

> The planned vintage rule — *"the vintage whose `RUCTimestamp` falls in
> (D-1 00:00, D-1 10:00]"* — selects the **empty set**. Every RUC feature would be
> NaN, and the only way to make one non-NaN is to reach for the 16:00 run, which is
> precisely the later-vintage fallback that manufactured the retired 0.986.
>
> **Gate A alone would only mean "we lack history." This means buying or scraping
> deeper RUC history fixes nothing** — the feed structurally does not know about
> tomorrow at the moment we must predict tomorrow. Do not spend a day on an archive
> workaround.

**4. Gate B — FAIL, but narrowly and honestly: 88.5% vs the 90% bar.**
μ-mass-weighted `ConstraintName|ContingencyName` match against NP4-191 over the
full two-month overlap (86.7% over a clean single month). **The namespace does
join** — this is nothing like R4's 0.000. By key *count* only 26% match, because
HRUC publishes a far smaller, reliability-driven constraint set than DAM, but those
keys carry ~88% of binding μ-mass. Had Gate B been the only failure, this would have
been a conversation rather than a kill.

**5. Leg C — cadence is HOURLY** (24 runs/day, every day). Not weekly, not nightly.
The weekly-vs-nightly repricing question is moot.

**6. The remembered schema was wrong.** Real column set, verbatim:
`postedDatetime, deliveryDate, hourEnding, RUCTimestamp, constraintID,
constraintName, contingencyName, limit, value, violationAmount, fromStation,
toStation, fromStationkV, toStationkV, DSTFlag` — the plan's field list omitted
`constraintID`, `limit`, `value`, `violationAmount`, and both kV columns. Dumping
the payload instead of trusting memory paid for itself.

## Consequences

* **0088 (`ruc-leakage-and-lift`) is deleted.** R7 — *does being on tomorrow's RUC
  list predict binding in tomorrow's DAM?* — is unanswerable on this access path,
  because there is no "tomorrow's RUC list" at DAM close.
* **Sprint 6's RUC arm is deleted.** `realtime_cutoff` goes with it: every surviving
  covariate is backward-only and legal under the existing `history_cutoff`.
* **The "one genuinely new information source" thesis is dead.** The remaining shots
  at R5's failure — lagged μ, geography, weather-response — are all *reorganisations
  of data we already hold*. See `plan/sprint-6.md`.
* **R4's lesson held, and paid.** The probe cost hours and killed the arm before the
  ingest, the migration, the backfill, and the model work were paid for.

## What shipped

`compute/mu/ruc_probe.py` — read-only, reuses `ercot_ingest/ErcotClient.py`, runs
all five legs to completion **even after an early gate fails**, because a partial
"no" hides *why*, and the why is the whole finding. Kept in the tree: it is the
evidence for this verdict and it re-runs in about a minute if anyone doubts it.
