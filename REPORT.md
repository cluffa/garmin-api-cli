# REPORT: garmin-official (official-API rewrite of garmin-connect-cli)

Date: 2026-10-21. Built autonomously from `BRIEF.md`. The old repo (`~/workspace/garmin-connect-cli`) was
only read (README, plus its git identity); it was not modified, and none of its client code was reused.

## Headline

1. **Garmin published an official Personal API client today** (`garmin-connect-personal-api-python`
   1.0.0 on PyPI, authored by Garmin Ltd.). It settled the questions the brief left open: base URL
   `https://personal.connectapi.garmin.com`, auth as a **key → bearer-token exchange**
   (`Authorization: ApiKey <key>`, then `Bearer <jwt>`), and 24 GET endpoints. The defaults in this CLI
   follow it. Base URL and key header remain configurable, as the brief asked.
2. **The Personal tier covers much more than the brief assumed.** **HRV** and **Body Battery** are both
   available, so `health hrv` and `health body-battery` are *supported* rather than stubbed. The brief
   explicitly allowed this if the docs said so.
3. I verified with **live read-only probes** using Alex's key. All data commands were exercised end to end
   against the real API. The probes also showed that the Personal API gateway is an **allowlist**: workouts,
   calendar, personal records, training status, readiness, badges, splits and TCX/GPX export all return
   HTTP 404. That is hard evidence for every unsupported row.
4. **Writes are the real loss.** Workouts and scheduling need the Starter-tier Training API (pending,
   push/cloud, publish-only). `workout publish` is implemented behind that credential boundary and
   currently returns the `unsupported` envelope naming the blocker.

## What was built

- `uv` project, Python ≥ 3.12, package `garmin_official_cli`, console script **`garmin-official`**
  (does not shadow `garmin`). Runtime dependencies: `click`, `requests`, `python-toon`, `garmin-fit-sdk`.
- Layers:
  - `client.py`: `Settings.from_env`, key discovery (env var → explicit file → `~/.config/garmin/personal-api-key.env` → Garmin's raw-key file), token exchange and cache (mode 600; stores a key *fingerprint*, never the key), a `Transport` protocol with a `requests` implementation, `PersonalApiClient` (with one re-exchange on 401), and `TrainingApiClient` (Starter boundary).
  - `endpoints.py`: **every** path, HTTP method and measured range limit, in one module.
  - `dates.py`: date specs and ranges, the 366-day cap / `--max-days`, chunking.
  - `output.py`: envelope, `json` / `json-pretty` / `toon`, NaN cleaning, **secret redaction of all output**, projection helpers.
  - `projections.py`: slim projections. `fit.py`: ZIP extraction and FIT lap decoding. `aggregate.py`: weekly and progress aggregations.
  - `models.py`: the support registry (status / tier / reason / old command) that drives `capabilities` and the stubs.
  - `workouts/`: spec validation, translation to the Training API format, JSON Schema.
  - `commands/`: auth, activity, health, stats, workout, badge, meta (`capabilities`, `api get`).
- 41 commands: 22 supported, 2 partial, 17 unsupported (`workout publish` included while blocked).
- Docs: `README.md`, `GAP_ANALYSIS.md`, `docs/API_NOTES.md`, this report.
- Git: repo initialized with one commit. Nothing was pushed.

## Test results

```
$ uv run pytest -q
185 passed in 0.9s
```

The suite is fully offline. A fake `Transport` routes requests to synthetic fixtures built from the live
shapes. `RequestsTransport` is patched to raise if constructed, HOME is a temp dir, and the clock is fixed.
Coverage:

- envelope and exit codes 0/1/2/3/4, stdout vs stderr, `--format` on errors
- date specs, range caps and chunk boundaries
- key discovery and env-file parsing, token exchange headers, cache fingerprint and expiry, the 401 retry, HTTP status → error type mapping
- every unsupported stub (envelope shape, exit 4, old-style arguments accepted, zero network calls)
- `capabilities` covers every command in the click tree, and the registry matches the tree one to one
- activity, health and stats parsing against fixtures; FIT laps decoded from a synthetic FIT built in the tests
- workout parsing, validation error paths, translation and publish (blocked, success with schedule, partial failure)
- docs consistency (README and GAP_ANALYSIS mention every command)
- **secret lint**: no `GCDC_…`-shaped string and not the real key (read from `~/.config/garmin/personal-api-key.env` when present) in any repo file; `.gitignore` excludes key material

Live smoke test (not part of the suite; run 2026-10-21 with the real key, read-only): exit 0 for
`auth status --verify`, `activity list/get/--samples/download/splits`, `health
steps/stress/heart-rate/sleep/hrv/body-battery/weight/weekly-steps/weekly-stress` (single dates and
multi-chunk ranges), `stats summary/weekly/progress`, `api get`, and `--format toon`. `activity download
--format-file tcx` and `workout publish` returned the unsupported envelope, exit 4. All outputs were
grepped for `GCDC_`, with no matches. Probe data and scratch bearer tokens were deleted afterwards.
No personal data is committed: all fixtures are synthetic.

## Design decisions (defaults I chose)

| Decision | Rationale |
|---|---|
| `click` directly instead of typer | typer 0.27 vendors click as a private module (`typer._click`); depending on its exception classes would be fragile. Click gives stable `UsageError` handling for the envelope contract. |
| `requests` behind a `Transport` protocol | It matches Garmin's client and worked through this VM's proxy (AGENTS.md notes httpx trouble with bracketed IPv6 `NO_PROXY`). The protocol keeps tests network-free. |
| Our own token cache (`~/.config/garmin-official-cli/bearer-token.json`) | Avoids coupling to Garmin's cache file format. It uses the same fingerprint idea (key + base URL). |
| One forced re-exchange on 401 | Recovers from early revocation automatically. Garmin's client does not retry. |
| Range endpoints chunked by measured limits (28/31/366 days) | Garmin rejects longer spans with 400. Chunks are merged so callers see one list. |
| Relative date specs (`-7d:today`) allowed as positional args (`ignore_unknown_options` on date commands) | Otherwise click parses `-7d` as an option. Side effect: a mistyped option on those commands shows up as an "invalid date spec" usage error. |
| `health weight` defaults to `-30d:today` | A single day of weigh-ins is almost always empty. Other commands keep `today`. |
| `activity download` extracts the FIT from Garmin's ZIP, refuses to overwrite without `--force`, and `--zip` keeps the raw ZIP | Safer than silent overwrite. The official delivery is a ZIP. |
| `activity splits` = FIT `lap_mesgs` | The Connect splits endpoints are 404 on the Personal API. The FIT is official data. |
| `workout create` kept as an unsupported stub pointing to `publish` | No silent omissions of old commands. |
| `workout publish` checks credentials **before** validating | The brief requires the blocker envelope while Starter credentials don't exist. |
| Invalid workout spec → `usage` error, exit 2, with per-path `results` | Fits the existing error types. The batch semantics of the old CLI are preserved. |
| `auth status` without a key → exit 3 with the status in `error.auth_status` | Agents can branch on exit 3, but still see the diagnosis. |
| New `api get` passthrough | Garmin's README says its wrappers lag behind the API. This reaches hydration, SpO₂, HR zones, fitness age and other endpoints without new code. |
| `auth set-key` is guidance only | It never reads or writes the key, so there is no chance of clobbering Alex's existing file. |
| Git identity: **repo-local** `Alex Cluff <alex@cluffa.dev>` | The brief said to use the global identity, but **no global git identity is configured** on this VM. The old repo uses this identity as its local config, so I copied that convention into the new repo. Global config was not touched. |

## Open questions and assumptions

1. **Training API wire format is unverified.** The base URL, `/training-api/workout`, `/training-api/schedule`, step field names and enums come from a forum report plus general knowledge of Garmin's Training API PDF, which could not be fetched (portal-gated, see `docs/API_NOTES.md` S5–S7). `workout validate` output should be checked against the real PDF once Starter is approved.
2. **Training API auth**: the CLI expects a ready user access token in `$GARMIN_TRAINING_API_TOKEN`. It doesn't implement the OAuth 2.0 PKCE flow, which needs a registered app and redirect URI.
3. **Can the Training API read or delete workouts the same app created?** Possibly. If so, partial `workout get/delete/schedule` become possible for CLI-published workouts only. They are stubbed per the brief for now.
4. Range limits are *measured*, not documented. Garmin could change them; they live in `endpoints.py`.
5. `stats summary` `spo2_avg` maps to `pulseOx.avgValue`. The probed day had only `avgAltitudeInMeters` there, so this field may always be null. Dedicated SpO₂ data is available via `api get /wellness-service/wellness/daily/spo2acclimation/{date}`.
6. Key expiry (2027-10-21 per the brief) isn't readable from the API or the key. `auth status` shows it if `GARMIN_PERSONAL_API_KEY_EXPIRES=2027-10-21` is set.
7. `activityType=running` in the search is assumed to include subtypes. The aggregation also filters locally.
8. The Personal tier's "Women's Health" data is reachable only via `api get` (menstrual-cycle endpoints). The old CLI had no such command.

## Exact list of unsupported features

Each exists as a command returning
`{"ok":false,"error":{"type":"unsupported","message":...,"reason":...,"tier_required":...}}` on stderr,
exit 4:

| # | Command | tier_required | Why |
|---|---|---|---|
| 1 | `auth login` | none | Password/MFA login is gone by design (key-based auth) |
| 2 | `activity download --format-file tcx` | none | No official TCX export (404) |
| 3 | `activity download --format-file gpx` | none | No official GPX export (404) |
| 4 | `stats records` | none | Not an official data type (404) |
| 5 | `stats training-status` | none | Proprietary derived metric (404) |
| 6 | `stats readiness` | none | Proprietary derived metric (404) |
| 7–11 | `badge earned`, `badge in-progress`, `badge available`, `badge adhoc`, `badge challenges` | none | No official badges/challenges API (404) |
| 12 | `workout publish` | starter | Implemented. Blocked until Starter approval and a Training API token |
| 13 | `workout create` | starter | Renamed to `workout publish` |
| 14–19 | `workout list`, `workout get`, `workout delete`, `workout schedule`, `workout unschedule`, `workout scheduled` | none | The Training API is publish-only; no library/calendar management (workout and calendar services 404 on the Personal API) |

Partial: `activity download` (original .FIT only) and `activity splits` (FIT laps; no Connect typed-split labels).

## How to use it now

```bash
cd ~/workspace/garmin-connect-official-cli
uv sync
uv run garmin-official auth status --verify
uv run garmin-official health hrv -7d:today
uv run garmin-official stats weekly
uv run garmin-official capabilities | jq '.data.unsupported'
```
