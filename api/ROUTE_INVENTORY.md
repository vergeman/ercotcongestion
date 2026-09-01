# Web route inventory

This is the in-repository consumer inventory for the 0160 API migration.
`web/src/api/client.ts` and `web/src/api/prefetch.ts` are the only runtime HTTP
consumers found in this repository. The operational and compute references are
documentation or job descriptions, not HTTP clients. Public callers of the
root-mounted API remain possible, so compatibility routes stay mounted through
their scheduled version boundary.

| Route group | Ownership | Known consumer | Migration status |
| --- | --- | --- | --- |
| `/topology`, `/forecast_range`, `/conditions_range` | primitive | Web Map and Brief | Stable resource reads |
| `/ercot_range` | primitive | Web Map and Brief | Sole realized range resource |
| `/map/summary` | bootstrap | Web Map | Typed per-section `availability` accompanies nullable sections |
| `/map/meta`, `/map/overview` | primitive | Map summary and Web Map | Stable independently readable resources |
| `/map/exposures`, `/map/reach`, `/map/constraints/ranked` | interaction | Web Map | Deliberately excluded from `/map/summary` |
| `/matrix/frame` | interaction | Web Matrix | Cursor and selection-specific resource |
| `/scoreboard/summary` | bootstrap | Web Scoreboard | Typed per-section `availability` accompanies nullable sections |
| `/analysis/brief`, `/analysis/brief/hero`, `/analysis/brief/hero/stats`, `/analysis/brief/details` | bootstrap | Web Brief | Server resolves the published run; `day` remains a deprecated `delivery_date` alias |
| `/analysis/hero`, `/analysis/hero/latest` | bootstrap/discovery | Web Brief | Server resolves the published run; `date` remains a deprecated alias on `/hero` |
| `/analysis/standouts`, `/analysis/grade` | primitive | Web Brief | Artifact-day resources with typed availability unions |
| `/analysis/node`, `/analysis/settlement-points`, `/analysis/constraints`, `/analysis/forecast-mu`, `/analysis/essp` | interaction/primitive | Web Matrix and Brief | Selection or artifact vocabulary resources |
| `/healthz` | operational | Deploy/runtime health checks | Not a web data resource |

Before removing either compatibility range route, observe public traffic through
the deprecation window and schedule the removal at a version boundary.
