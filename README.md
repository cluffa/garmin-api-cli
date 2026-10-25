# garmin

**Agent-first CLI for Garmin Connect, built only on the official Garmin Connect Developer Program APIs.**
It is a from-scratch rewrite of `cluffa/garmin-connect-cli`, which used Garmin's unofficial internal web
APIs. The UX contract is the same; the data source is official.

- JSON envelope: `{"ok":true,"data":...}` on stdout, or `{"ok":false,"error":{...}}` on stderr
- Exit codes: 0 success, 1 internal, 2 usage, 3 auth, 4 API / unsupported
- `--format json|json-pretty|toon`; `--full` returns raw Garmin payloads instead of slim projections
- Unified date specs: `today`, `yesterday`, `-7d`, `+7d`, `YYYY-MM-DD`, ranges `start:end` (capped at 366 days unless `--max-days`)
- `capabilities`: one call lists every command with its official **support status**
- Every feature the official API cannot provide still exists as a command and returns a uniform
  `unsupported` envelope. See [GAP_ANALYSIS.md](GAP_ANALYSIS.md).

The console script is `garmin`. It replaces the old `garmin` from `cluffa/garmin-connect-cli`, so uninstall that one first if both are on your PATH.

## Which official tier this uses

| Tier | Status | What a local CLI can do with it |
|---|---|---|
| **Personal** | active (free, key-based, **pull**) | Everything marked *supported* below. |
| Starter Business | applied 2026-10-21, **pending** | Training API publish only (`workout publish`). Health/Activity are push-only webhooks. |
| Enterprise | not applied | Nothing a local CLI needs beyond Starter (adds Golf, backfill, ping/pull). |

## Setup

```bash
uv sync
uv run garmin auth set-key      # prints the steps below
```

1. Create a Personal API key at <https://connect.garmin.com/app/settings/personalApiToken>.
   Keys start with `GCDC_` and are valid for one year. Only one key can exist at a time.
2. Store it in `~/.config/garmin/personal-api-key.env` (directory 700, file **600**) as the single line
   `GARMIN_PERSONAL_API_KEY=<key>`. Use an editor, not `echo`, so the key stays out of shell history.
3. Check it: `uv run garmin auth status --verify`.

Key lookup order: `$GARMIN_PERSONAL_API_KEY` → `$GARMIN_PERSONAL_API_KEY_FILE` →
`~/.config/garmin/personal-api-key.env` → `~/.config/garmin/connect-personal-api-key` (the raw-key file
used by Garmin's own `gc-personal`).

The CLI exchanges the key for a short-lived bearer token
(`POST /personalapitoken-service/personal-api/personal-api-key/token`, `Authorization: ApiKey <key>`)
and caches the token at `~/.config/garmin-official-cli/bearer-token.json` (mode 600). The cache stores
only a SHA-256 fingerprint of the key, never the key. A token with less than an hour left is replaced
automatically, and a 401 triggers one re-exchange. The key and the token are redacted from all output.

### Configuration (environment)

| Variable | Default | Purpose |
|---|---|---|
| `GARMIN_PERSONAL_API_KEY` | — | The key (overrides files) |
| `GARMIN_PERSONAL_API_KEY_FILE` | — | Explicit key file (env-file or raw-key format) |
| `GARMIN_PERSONAL_API_KEY_EXPIRES` | — | Optional `YYYY-MM-DD`; `auth status` then reports days remaining |
| `GARMIN_API_BASE_URL` | `https://personal.connectapi.garmin.com` | Personal API base URL (`GARMIN_PERSONAL_API_BASE_URL` also accepted) |
| `GARMIN_API_KEY_HEADER` | `Authorization` | Header that carries the key in the token exchange |
| `GARMIN_API_KEY_SCHEME` | `ApiKey` | Scheme prefix for that header (empty = raw key) |
| `GARMIN_API_TIMEOUT` | `30` | HTTP timeout, seconds |
| `GARMIN_BEARER_TOKEN_CACHE` | `~/.config/garmin-official-cli/bearer-token.json` | Token cache path |
| `GARMIN_TRAINING_API_BASE_URL` | `https://apis.garmin.com` | Training API base URL |
| `GARMIN_TRAINING_API_TOKEN` | — | Starter-tier Training API user token (does not exist yet) |

Every endpoint path lives in `src/garmin_official_cli/endpoints.py`. Sources and assumptions are in
[docs/API_NOTES.md](docs/API_NOTES.md).

## Global options

Global options go **before** the sub-command:

```bash
uv run garmin --format toon health steps -7d:today
uv run garmin --full stats summary yesterday
```

## Command reference

Status: **S** supported, **P** partial, **U** unsupported (returns the `unsupported` envelope, exit 4).
`capabilities` returns this table in machine-readable form.

### `auth`

| Command | Status | Description |
|---|---|---|
| `auth status [--verify]` | S | Is a key configured, from where, file mode, token cache, expiry note. `--verify` does one live exchange. Never prints the key. Exit 3 if no key is configured. |
| `auth set-key` | S | Setup guidance only; reads and writes nothing |
| `auth refresh` | S | Force a new bearer token |
| `auth logout` | S | Delete the cached bearer token |
| `auth login` | U | Password/MFA login is gone by design |

### `activity`

| Command | Status | Description |
|---|---|---|
| `activity list [--limit N] [--start N] [--type KEY] [--range R] [--miles]` | S | Activities, newest first |
| `activity get <id> [--miles] [--samples]` | S | One activity; `--samples` adds the time series |
| `activity download <id> [--format-file fit] [--out PATH] [--zip] [--force]` | P | Original file (.FIT), extracted from Garmin's ZIP. Refuses to overwrite without `--force` |
| `activity download <id> --format-file tcx\|gpx` | U | No official TCX/GPX export |
| `activity splits <id> [--miles]` | P | Laps decoded from the official .FIT (pace, HR, power, cadence, intensity, lap trigger) |

### `health`

| Command | Status | Request cost |
|---|---|---|
| `health steps [range]` | S | 1 request per 28 days |
| `health heart-rate [range]` | S | 1 request per day |
| `health sleep [range]` | S | 1 request (date) / per 31 days (range) |
| `health stress [range]` | S | 1 request per 28 days |
| `health weight [range]` (default `-30d:today`) | S | 1 request per 366 days |
| `health hrv [range]` | S | 1 request (date or range ≤ 366 days) |
| `health body-battery [range]` | S | 1 request per 31 days |
| `health weekly-steps [date] [--weeks N]` | S | Local aggregation; 1 request per 28 days |
| `health weekly-stress [date] [--weeks N]` | S | Local aggregation; 1 request per 28 days |

Shapes: the range endpoints (`steps`, `stress`, `body-battery`, `weight`, `sleep` and `hrv` for ranges)
return one projected record per day, ascending. `heart-rate` has no range endpoint. A single date returns
the day's object; a range returns `[{"date": ..., "data": {...}}]`. A failed day has `"data": null` plus
`"error"`, and the command fails (exit 4) only if every day failed. An auth failure stops the whole range
(exit 3).

### `stats`

| Command | Status | Description |
|---|---|---|
| `stats summary [range]` | S | Daily summary: steps, distance, floors, calories, HR, intensity minutes, stress, Body Battery, respiration, hydration |
| `stats weekly [date] [--week-start monday\|sunday]` | S | Running volume: this week, previous week, 4-week average, longest run, run count (km + mi) |
| `stats progress <start> [end] [--type KEY] [--miles]` | S | Activity totals per type between two dates |
| `stats records` | U | Not an official data type |
| `stats training-status` | U | Garmin-proprietary derived metric |
| `stats readiness` | U | Garmin-proprietary derived metric |

### `workout`

| Command | Status | Description |
|---|---|---|
| `workout validate --json '<spec>' \| --file F \| stdin` | S | Local validation + translation to the Training API workout JSON. Invalid spec → exit 2 with per-path errors |
| `workout schema` | S | JSON Schema of the spec |
| `workout publish --json\|--file\|stdin` | U (blocked) | Training API publish (and schedule when `date` is set). Returns `unsupported` naming the Starter-approval blocker until `$GARMIN_TRAINING_API_TOKEN` exists |
| `workout create` | U | Old name; use `workout publish` |
| `workout list` / `workout get` / `workout delete` | U | No official workout-library management |
| `workout schedule` / `workout unschedule` / `workout scheduled` | U | No official calendar management |

The spec format is the same as the old CLI's:

```json
{"workouts": [{"name": "Wk1 Tue", "sport": "running", "date": "2026-07-21", "notes": "cruise intervals",
  "steps": [
    {"type": "warmup", "duration": {"time": "10min"}, "note": "easy"},
    {"repeat": 5, "steps": [
      {"type": "interval", "duration": {"distance": "1km"}, "target": {"pace": ["4:00/km", "3:50/km"]}},
      {"type": "recovery", "duration": {"time": "2min"}}]},
    {"type": "cooldown", "duration": {"time": "10min"}}]}]}
```

- Step types: `warmup`, `interval`, `active`, `recovery`, `rest`, `cooldown`
- Duration: `time` (`"10min"`, `"45s"`, `"1h30min"`, `"4:00"`) or `distance` (`"400m"`, `"1km"`, `"1mi"`). Omit it for an open (lap-button) step
- Target: `pace` (running only), `speed`, `power`, or `hr`. Each takes one value or a `[low, high]` pair
- Sports: `running`, `cycling`, `swimming`, `strength`, `cardio`, `generic`
- A single workout object or a bare list is also accepted

### `badge`

| Command | Status |
|---|---|
| `badge earned`, `badge in-progress`, `badge available`, `badge adhoc`, `badge challenges` | U: no official badges API |

### Meta

| Command | Status | Description |
|---|---|---|
| `capabilities` | S | Every command with `status`/`tier`/`reason`/`old_command`/params, the workout schema, env vars |
| `api get <path> [--param K=V ...]` | S | Raw GET of any Personal API path, e.g. `/biometric-service/heartRateZones/v2` |

## Envelopes and exit codes

```json
{"ok":true,"data":[{"date":"2026-10-20","steps":13301,"goal":8000,"distance_m":12710}]}
{"ok":false,"error":{"type":"usage","message":"invalid date spec 'bogus'","hint":"..."}}
{"ok":false,"error":{"type":"unsupported","message":"`badge earned` is not available through the official Garmin Connect APIs","reason":"...","tier_required":"none"}}
```

| Code | `error.type` | Meaning |
|---|---|---|
| 0 | — | Success |
| 1 | `internal` | Bug / unexpected failure |
| 2 | `usage` | Bad arguments, invalid date spec, invalid workout spec |
| 3 | `auth` | No key configured, key rejected, HTTP 401/403 |
| 4 | `api` | HTTP error, network error, all days of a range failed |
| 4 | `unsupported` | The official APIs cannot do this (`reason`, `tier_required`) |

## Development

```bash
uv sync
uv run pytest            # fully offline: fake transport, synthetic fixtures, no key needed
```

The suite includes a secret scan. It fails if a `GCDC_…`-shaped string, or the real key from
`~/.config/garmin/personal-api-key.env` when present, appears in any repository file. Failure messages
name files only, never the value.

Layout: `client.py` (settings, key discovery, token exchange, transport), `endpoints.py` (every path),
`dates.py`, `output.py` (envelope/formats/redaction), `projections.py`, `fit.py` (ZIP/FIT laps),
`aggregate.py`, `models.py` (support registry), `workouts/` (spec + schema), `commands/`.
