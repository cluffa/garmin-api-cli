# Gap analysis: old `garmin` CLI vs official Garmin Connect APIs

This maps every command of the old CLI (`cluffa/garmin-connect-cli`, built on
Garmin Connect's internal web APIs) to what the **official Garmin Connect
Developer Program** can do. The new CLI (`garmin`) implements each row
as written here. Unsupported rows exist as commands that return the uniform
`unsupported` envelope (exit 4). None of them is left out silently, and none
returns fake data.

Verified 2026-10-21 against Garmin's own Personal API client
(`garmin-connect-personal-api-python` 1.0.0) and live read-only probes of the
Personal API with Alex's key. Sources are listed in [docs/API_NOTES.md](docs/API_NOTES.md).

## The short version

- **Almost everything you read from Garmin still works**, through the **Personal** tier (free, active, pull).
  Activities, the original .FIT files, steps, heart rate, sleep, stress, weight, HRV, **Body Battery** and
  the daily summaries all work. HRV and Body Battery turned out to be available on the Personal tier.
- **Everything you write to Garmin is gone for now.** Workouts, scheduling and the calendar need the
  **Training API**, which belongs to the Starter Business tier: the application is pending, the API is
  push/cloud-based, and it is publish-only. `workout validate` and `workout schema` still work locally.
- **Garmin's own derived metrics are not exposed**: personal records, training status, training readiness,
  badges and challenges. The Personal API gateway returns 404 for them, and no official tier lists them.
- **TCX/GPX export is gone.** The official file is the original upload (.FIT).
- **Password login is gone by design.** The Personal API key is the only credential.

## Legend

| Status | Meaning |
|---|---|
| supported | Same capability through an official API (possibly a different endpoint or shape) |
| partial | Works, with a documented limitation |
| unsupported | Command exists but returns `{"ok":false,"error":{"type":"unsupported",...}}`, exit 4 |

Tier values are the official tier that provides the feature: `personal` (active), `starter` (applied,
pending), `enterprise` (not applied), `local` (pure local logic), or `none` (no official tier offers it).

## Command-by-command

### auth

| Old command | New command | Status | Tier | Reason |
|---|---|---|---|---|
| `auth login` | `auth login` (stub) | unsupported | none | Email/password + MFA login is gone by design. The Personal tier authenticates with a Personal API key and the Business tiers with OAuth app authorization. This CLI handles no passwords. |
| `auth status` | `auth status` | supported | personal | Now reports whether a key is configured, its source file and mode (never the key itself), and the bearer-token cache state. `--verify` does a live key→token exchange. |
| `auth logout` | `auth logout` | supported | local | Deletes the cached bearer token. The key is left untouched. |
| — | `auth set-key` | supported | local | New: guidance for creating and storing the key. Reads and writes nothing. |
| — | `auth refresh` | supported | personal | New: forces a new key→bearer-token exchange. |

### activity

| Old command | New command | Status | Tier | Reason |
|---|---|---|---|---|
| `activity list` | `activity list` | supported | personal | Personal API activity search (`--limit`, `--start`, `--type`, `--miles`, plus a new `--range`). |
| `activity get <id>` | `activity get` | supported | personal | Personal API activity summary. The new `--samples` flag adds the detail time series. |
| `activity download <id> --format-file fit` | `activity download` | partial | personal | Official delivery is the **original file** (a ZIP holding the .FIT for device recordings). The CLI extracts it; `--zip` keeps Garmin's ZIP. |
| `activity download --format-file tcx\|gpx` | `activity download --format-file tcx\|gpx` | **unsupported** | none | No official API exports TCX/GPX. The Connect export endpoints return 404 on the Personal API. Download the FIT and convert it locally. |
| `activity splits <id>` | `activity splits` | partial | personal | Laps are decoded locally from the official .FIT (lap messages: distance, time, pace, HR, power, cadence, intensity). The Connect splits endpoints return 404, so the old "split type" labels are limited to the FIT `lap_trigger` (manual / distance / time / session_end ...). |

### health

| Old command | New command | Status | Tier | Reason |
|---|---|---|---|---|
| `health steps [range]` | `health steps` | supported | personal | Daily steps range endpoint. Garmin caps it at 28 days per call (measured), so the CLI chunks. |
| `health heart-rate [range]` | `health heart-rate` | supported | personal | Daily heart rate, one request per day (no range endpoint), with the old `[{date,data}]` range shape. |
| `health sleep [range]` | `health sleep` | supported | personal | `dailySleep` for one date; sleep-summaries range endpoint (31-day chunks) for ranges. |
| `health stress [range]` | `health stress` | supported | personal | Daily stress range endpoint (28-day chunks). |
| `health weight [range]` | `health weight` | supported | personal | Weight range endpoint (366-day chunks). Grams are converted to kg. Default range is now `-30d:today`. |
| `health hrv [range]` | `health hrv` | supported | personal | HRV summary + readings for one day, HRV summaries for a range. (The brief allowed a stub; the official Personal API includes HRV.) |
| `health body-battery [range]` | `health body-battery` | supported | personal | Body Battery daily reports (31-day chunks). Not a standard *Business* Health API summary type, but Garmin's Personal API exposes it. |
| `health weekly-steps [date] [--weeks N]` | `health weekly-steps` | supported | personal | Local weekly aggregation (Monday-start weeks) over official daily steps. Costs about one request per 4 weeks instead of one in total. |
| `health weekly-stress [date] [--weeks N]` | `health weekly-stress` | supported | personal | Local weekly aggregation over official daily stress. |

### stats

| Old command | New command | Status | Tier | Reason |
|---|---|---|---|---|
| `stats summary [date]` | `stats summary` | supported | personal | Personal API daily summaries (v2): steps, distance, floors, calories, HR, intensity minutes, stress, Body Battery, respiration, hydration. Avg SpO₂ is null unless Garmin includes it in the summary. |
| `stats weekly` | `stats weekly` | supported | personal | Local aggregation of official running activities: this week, previous week, prior-4-week average, longest run, run count (km and mi). |
| `stats progress <start> <end>` | `stats progress` | supported | personal | Local aggregation of official activities per type between two dates. |
| `stats records` | `stats records` (stub) | **unsupported** | none | Personal records are not an official data type. The Personal API gateway returns 404 for the Connect endpoint and no Business API offers it. |
| `stats training-status [range]` | `stats training-status` (stub) | **unsupported** | none | Garmin Connect proprietary derived metric (load, load ratio, focus). Not an official data type (404 on the Personal API). |
| `stats readiness [range]` | `stats readiness` (stub) | **unsupported** | none | Garmin Connect proprietary derived metric. Not an official data type (404 on the Personal API). |

### badge

| Old command | New command | Status | Tier | Reason |
|---|---|---|---|---|
| `badge earned` | `badge earned` (stub) | **unsupported** | none | No official badges/challenges API in any tier (404 on the Personal API). |
| `badge in-progress` | `badge in-progress` (stub) | **unsupported** | none | Same. |
| `badge available` | `badge available` (stub) | **unsupported** | none | Same. |
| `badge adhoc` | `badge adhoc` (stub) | **unsupported** | none | Same. |
| `badge challenges` | `badge challenges` (stub) | **unsupported** | none | Same. |

### workout

The official **Training API** is part of the **Starter Business** tier (application submitted 2026-10-21,
approval pending). It is **cloud-to-cloud**, authorized per user through Garmin's OAuth flow for a
registered app, and **publish-only**: it sends a structured workout to Garmin Connect for device sync. It
does not manage the user's workout library or calendar. The Personal API gateway returns 404 for
`workout-service` and `calendar-service`.

> Open question (to re-check once the Starter portal docs are reachable): Garmin's Training API reference
> may let an app retrieve, update or delete workouts and schedules **that the same app created**. If so,
> partial versions of `get`/`delete`/`schedule` become possible for workouts published by this CLI only.
> Workouts created in Garmin Connect or by other apps would still be out of reach.

| Old command | New command | Status | Tier | Reason |
|---|---|---|---|---|
| `workout validate` | `workout validate` | supported | local | Pure local validation plus translation to the Training API workout JSON. No network, no key needed. |
| `workout schema` | `workout schema` | supported | local | Local JSON Schema of the spec. |
| `workout create` | `workout publish` | **unsupported** (until Starter credentials exist) | starter | Implemented behind the credential boundary. Without `$GARMIN_TRAINING_API_TOKEN` it returns the unsupported envelope naming the blocker (Starter approval pending). With a token it posts each workout (and a schedule entry if `date` is set). The old name `workout create` is kept as a stub pointing to `publish`. |
| `workout list` | `workout list` (stub) | **unsupported** | none | No official way to list saved workouts. |
| `workout get <id>` | `workout get` (stub) | **unsupported** | none | No official way to read a saved workout from the user's library. |
| `workout delete <id>` | `workout delete` (stub) | **unsupported** | none | No official library management. |
| `workout schedule <id> <date>` | `workout schedule` (stub) | **unsupported** | none | Cannot schedule an *existing* library workout. Scheduling only happens as part of `publish` (Training API, Starter). |
| `workout unschedule <id>` | `workout unschedule` (stub) | **unsupported** | none | No official calendar management. |
| `workout scheduled <range>` | `workout scheduled` (stub) | **unsupported** | none | No official calendar read. |

### meta

| Old command | New command | Status | Tier | Reason |
|---|---|---|---|---|
| `capabilities` | `capabilities` | supported | local | Now lists every command with `status`, `tier`, `reason` and the old command it replaces, plus the workout schema and config env vars. |
| — | `api get` | supported | personal | New: raw GET passthrough to any Personal API path (hydration, SpO₂, fitness age, HR zones, food logs, profile settings and other endpoints without a dedicated command). |

## Exact list of unsupported features

1. `auth login`: password/MFA login (gone by design)
2. `activity download --format-file tcx`: TCX export
3. `activity download --format-file gpx`: GPX export
4. `stats records`: personal records
5. `stats training-status`: training status
6. `stats readiness`: training readiness
7. `badge earned`
8. `badge in-progress`
9. `badge available`
10. `badge adhoc`
11. `badge challenges`
12. `workout publish`: blocked on Starter approval (implemented; activates with `$GARMIN_TRAINING_API_TOKEN`)
13. `workout create`: old name, now `workout publish`
14. `workout list`
15. `workout get`
16. `workout delete`
17. `workout schedule`
18. `workout unschedule`
19. `workout scheduled`

Partial: `activity download` (FIT/original only) and `activity splits` (FIT laps, no Connect typed splits).

## What would change with other tiers

- **Starter (pending)** unlocks `workout publish` (push a workout, optionally scheduled on a date). It does
  **not** unlock list/get/delete/unschedule of library workouts. Its Health/Activity APIs are push-only
  (webhooks to a registered server) with no historical data, so they add nothing a local CLI can pull
  beyond what the Personal tier already gives.
- **Enterprise (not applied)** adds the Golf API, historical backfill and ping/pull delivery. It still lists
  no badges, records, training status or readiness.
