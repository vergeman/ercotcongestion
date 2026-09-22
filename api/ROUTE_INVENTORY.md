# Web route inventory

This is the in-repository consumer inventory for the 0160 API migration.
`web/src/api/client.ts` and `web/src/api/prefetch.ts` are the only runtime HTTP
consumers found in this repository. The operational and compute references are
documentation or job descriptions, not HTTP clients. Public callers of the
root-mounted API remain possible, so compatibility routes stay mounted through
their scheduled version boundary.

| Route group                                                                                        | Ownership             | Known consumer               | Migration status                                                                    |
|----------------------------------------------------------------------------------------------------|-----------------------|------------------------------|-------------------------------------------------------------------------------------|
| `/topology`, `/forecast_range`                                                                     | primitive             | Web Map and Brief            | Stable resource reads                                                               |
| `/conditions_range`                                                                                | primitive             | Web Map                      | Shared D-1 10:00 CT DAM-close conditions; excludes delivered actuals and real-time pricing |
| `/ercot_range`                                                                                     | primitive             | Web Map and Brief            | Sole realized range resource                                                        |
| `/map/summary`                                                                                     | bootstrap             | Web Map                      | Typed per-section `availability` accompanies nullable sections                      |
| `/map/exposures`, `/map/reach`, `/map/constraints/ranked`                                          | interaction           | Web Map                      | Deliberately excluded from `/map/summary`                                           |
| `/matrix/frame`                                                                                    | interaction           | Web Matrix                   | Cursor and selection-specific resource                                              |
| `/scoreboard/summary`                                                                              | bootstrap             | Web Scoreboard               | Typed per-section `availability` accompanies nullable sections                      |
| `/analysis/brief/hero`, `/analysis/brief/details` | bootstrap             | Web Brief                    | Server resolves the published run; `day` remains a deprecated `delivery_date` alias |
| `/analysis/hero/latest`                                                                            | discovery             | Web Brief                    | Newest artifact-backed Brief delivery day                                           |
| `/analysis/standouts`                                                                               | primitive             | Web Brief                    | Artifact-day resource with typed availability unions                                |
| `/analysis/node`, `/analysis/settlement-points`, `/analysis/constraints`                           | interaction/primitive | Web Matrix and Brief         | Selection or artifact vocabulary resources                                          |
| `/healthz`                                                                                         | operational           | Deploy/runtime health checks | Not a web data resource                                                             |

Before removing either compatibility range route, observe public traffic through
the deprecation window and schedule the removal at a version boundary.
