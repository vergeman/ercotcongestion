# 0121 - Reduce API content

Type: refactor
Branch: refactor/0121-reduce-api-content

## Goal

* Reduce initial map-range requests and repeated realized payload data.
* Compress API responses and remove excess congestion precision.

## Context

* The map previously fetched realized congestion and SPP separately.
* Each response repeated timestamps and settlement-point IDs per hour.

## Approach

* Add `/ercot_range`: one SPP query, shared `sp_ids` index, aligned congestion/SPP arrays.
* Decode the compact response once in `web/src/api/prefetch.ts`; preserve map cache shapes.
* Round served realized and forecast congestion values to cents, half-up.
* Attach Traefik `compress` middleware to the HTTPS API route.
* Keep legacy realized endpoints compatible; do not merge unrelated map bootstrap calls.

## Acceptance

* [x] Explicit map windows make two range requests, not three.
* [x] `/ercot_range` sends one SP index and aligned values.
* [x] Congestion is served at cent precision.
* [x] The HTTPS API route has compression middleware.
* [x] Focused Compose API tests and Compose web build pass.
