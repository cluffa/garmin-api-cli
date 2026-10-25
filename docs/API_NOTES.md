# API notes: endpoints, auth and their sources

Every endpoint the CLI calls is defined in `src/garmin_official_cli/endpoints.py`. This document records
where each fact comes from and separates **documented facts**, **observed facts** (live probes) and
**assumptions**. Research date: 2026-10-21, the day the Personal tier launched.

## Sources

| ID | Source | Notes |
|---|---|---|
| S1 | <https://developer.garmin.com/gc-developer-program/overview/> | Public tier overview (Personal / Starter / Enterprise). No URLs or endpoints. |
| S2 | PyPI `garmin-connect-personal-api-python` **1.0.0**, released 2026-10-21, author "Garmin Ltd. or its subsidiaries", Apache-2.0, repo `github.com/garmin/connect-personal-api-python` | **Garmin's own reference client for the Personal API.** Its `constants.py`, `auth.py`, `client.py` and README define the base URL, the token exchange and 24 GET endpoints. This is the closest thing to official Personal API documentation that is publicly reachable. Its code was read to learn the API, not vendored. |
| S3 | Live read-only probes with Alex's Personal API key, 2026-10-21 | Only GET requests plus the token exchange. Response *shapes* were inspected. No personal data is stored in this repo (fixtures are synthetic). |
| S4 | <https://developerportal.garmin.com/developer-programs/connect-api> | Returns HTTP 403 to unauthenticated fetches. Not readable. |
| S5 | Garmin developer forum thread "POST request to training API create workout endpoint returns an undescriptive 500 error" (forums.garmin.com, Connect IQ section) | Third-party report: Training API workout create is `POST https://apis.garmin.com/training-api/workout`, with body fields `workoutName`, `description`, `sport`, `steps[]` (`durationType`, `targetType`, `intensity`). |
| S6 | `developerportal.garmin.com/sites/default/files/OAuth2PKCE_1.pdf` (search result title "Garmin Connect Developer Program OAuth2.0 PKCE Specification") | Shows the Business tiers use OAuth 2.0 + PKCE and `Authorization: Bearer`. The PDF itself was not fetched in full. |
| S8 | <https://developer.garmin.com/gc-developer-program/personal/swagger-docs/> | **Garmin's published Personal API spec.** The page renders an OpenAPI 3.0.1 document (title "Garmin Connect Personal API", server `https://personal.connectapi.garmin.com`) embedded in its JavaScript bundle: 26 GET paths, 109 schemas. Read 2026-10-25. It supersedes S2 as the endpoint reference. |
| S7 | Training API reference PDF (developer portal, also mirrored on Scribd) | Not reachable: fetch timed out / login-gated. Field details below marked *assumption* come from general knowledge of this document, not a fresh read. |

## Personal tier (the one this CLI uses)

### Documented (S1, S2)

- Personal tier: single user, own data, **pull only**. Includes Activity (JSON & .FIT), Health (JSON) and
  Women's Health (JSON). (S1)
- Base URL: `https://personal.connectapi.garmin.com`. Garmin's client lets `$GARMIN_PERSONAL_API_BASE_URL`
  override it. (S2 `constants.py`)
- **Auth is two-step** (S2 `auth.py`):
  1. `POST /personalapitoken-service/personal-api/personal-api-key/token` with headers
     `Accept: */*` and `Authorization: ApiKey <personal API key>`. The response body is a bare JWT
     (text/plain) whose `exp` claim gives its lifetime.
  2. Every data request sends `Authorization: Bearer <jwt>` and `Accept: application/json`.
  - Garmin's client caches the token and reuses it only for the same key + base URL (SHA-256 fingerprint)
    while more than one hour remains. A token revoked early gives 401 and is not retried. (S2)
- Key discovery in Garmin's client: explicit key → explicit file → `$GARMIN_PERSONAL_API_KEY` → raw-key
  file `~/.config/garmin/connect-personal-api-key`. (S2 `api_keys.py`)
- GET endpoints (S2 `client.py` / README), all relative to the base URL:

| Endpoint | CLI use |
|---|---|
| `/usersummary-service/stats/steps/daily/{start}/{end}` | `health steps`, `health weekly-steps` |
| `/usersummary-service/stats/stress/daily/{start}/{end}` | `health stress`, `health weekly-stress` |
| `/sleep-service/sleep/dailySleep?date=` | `health sleep` (single date) |
| `/sleep-service/sleep/dailySleepSummariesByDate?startDate=&endDate=` | `health sleep` (range) |
| `/wellness-service/wellness/bodyBattery/reports/daily?startDate=&endDate=[&chunks=]` | `health body-battery` |
| `/wellness-service/wellness/dailyHeartRate?date=` | `health heart-rate` |
| `/hrv-service/hrv/{date}` | `health hrv` (single date) |
| `/hrv-service/hrv/daily/{start}/{end}` | `health hrv` (range) |
| `/weight-service/weight/range/{start}/{end}?includeAll=true` | `health weight` |
| `/usersummary-service/v2/dailysummaries?startDate=&endDate=` | `stats summary` |
| `/activitylist-service/activities/search/activities?start=&limit=[&startDate=&endDate=&activityType=]` | `activity list`, `stats weekly`, `stats progress` |
| `/activity-service/activity/{id}` | `activity get` |
| `/activity-service/activity/{id}/workouts` | (defined, not used by a command) |
| `/download-service/files/activity/{id}` (ZIP bytes) | `activity download`, `activity splits` |
| `/usersummary-service/stats/hydration/daily/{start}/{end}` | via `api get` |
| `/goal-service/goal/user/effective/weightgoal/{start}/{end}` | via `api get` |
| `/nutrition-service/food/logs/{date}` | via `api get` |
| `/userprofile-service/userprofile/settings` | via `api get` |
| `/biometric-service/heartRateZones/v2` | via `api get` |
| `/fitnessage-service/fitnessage/v2/{date}` | via `api get` |
| `/wellness-service/wellness/daily/spo2acclimation/{date}` | via `api get` |
| `/wellnessactivity-service/activity/summary/range/{start}/{end}` | via `api get` |
| `/periodichealth-service/menstrualcycle/summary/{date}` | via `api get` |
| `/periodichealth-service/menstrualcycle/dayview/{date}?todayDate=` | via `api get` |

  Garmin's README says its wrappers "may lag behind new endpoints available through Personal API". Its
  generic `get()` exists for that, and `api get` mirrors it.

### Observed (S3, live probes 2026-10-21)

- The token exchange works as documented. A token obtained on the afternoon of 2026-10-21 had `exp`
  2026-10-22 19:00 UTC, so its lifetime is roughly a day. Garmin does not document the lifetime.
- All endpoints above returned 200 with the expected JSON, except where the shape was empty (no
  hydration data).
- **Extra endpoint that works**: `/activity-service/activity/{id}/details` (metric descriptors plus sample
  rows). Used by `activity get --samples`. It is **not** in Garmin's published spec (S8), so it may change
  without notice.

### Published spec (S8, read 2026-10-25)

- Every path the CLI calls is in the spec except `/activity-service/activity/{id}/details` (above).
- Spec paths with no dedicated command (reach them with `api get`): `/usersummary-service/usersummary/daily`,
  `/weight-service/weight/all/{startDate}/{endDate}`, plus the hydration, weight goal, nutrition, fitness age,
  SpO2, menstrual cycle and wellness activity paths already listed above.
- `/activity-service/activity/{id}/workouts` returns `ActivityWorkoutDTO[]` (`workoutName`, `sport`,
  `timeCreated`, `steps[]` of `WorkoutStepDTO`). Verified live 2026-10-25: it returns the structured workout a
  run was recorded with, and `[]` for free runs. Used by `activity workout`.
- `WorkoutStepDTO` target encoding (spec text): `targetValue` 0 means a custom range in
  `targetValueLow`/`targetValueHigh`, nonzero selects a zone. Speed is m/s. Heart rate is % of max HR, or
  bpm + 100 (250 = 150 bpm). Power is % of FTP, or watts + 1000. Running cadence is steps/min. Repeat steps
  use `durationType` `REPEAT_UNTIL_STEPS_CMPLT` with `durationValue` = first repeated step index and
  `targetValue` = repeat count.
- `ActivitySummaryDTO.summaryDTO` carries `directWorkoutRpe` (10-100, the athlete's 1-10 RPE times ten),
  `directWorkoutFeel` (0/25/50/75/100), `directWorkoutComplianceScore`, `trainingEffectLabel`, running
  dynamics (`strideLength` cm, `groundContactTime` ms, `verticalOscillation` cm, `verticalRatio`),
  `avgGradeAdjustedSpeed`, stamina and Body Battery change. The search results carry `hrTimeInZone_1..5`
  (seconds). `activity get`/`activity list` project these.

### FIT file facts (observed in real recordings, 2026-10-25)

- A run recorded as a structured workout embeds `workout` (name, description) and `workout_step` messages
  (raw units: time ms, distance cm, speed target m/s × 1000). Each lap carries `wkt_step_index`.
- Auto-lap still fires inside long workout steps (a 2 mi warmup is two 1 mi laps with the same
  `wkt_step_index`). The watch also writes one `split` message of type `interval_*` per executed step with
  `first_lap_index`/`num_laps`; `activity analyze` groups laps with those, and falls back to merging
  consecutive laps of the same step when a split is missing (seen for some warmups).
- `time_in_zone` messages give session and per-lap time in HR zones with the boundaries used
  (`hr_zone_high_boundary`, `hr_calc_type`), plus FTP and power buckets.
- `session.workout_rpe` / `workout_feel` match the API's `directWorkoutRpe` / `directWorkoutFeel`.
- Running cadence fields count one foot; steps/min = 2 × (`cadence` + `fractional_cadence`).
- String fields can come back from the SDK as a list split on NUL bytes, followed by garbage from a reused
  device buffer (e.g. `['Easy 10', '', '20', '', 'des']`). The first non-empty item is the real text.
- Timer pauses are `event` messages (`timer` / `stop_all`, then `start`); records are not written while
  paused.
- **Range limits** (a longer span returns HTTP 400, or 500 for daily summaries):

  | Endpoint | Max days per call (measured) | `max_days` in `endpoints.py` |
  |---|---|---|
  | steps daily, stress daily | 28 (29 → 400) | 28 |
  | sleep summaries, Body Battery | ≥ 31 (60 → 400) | 31 |
  | daily summaries v2 | ≥ 60 (90 → 500) | 31 (safety margin) |
  | HRV summaries | ≥ 366 | 366 |
  | weight range | ≥ 366 | 366 |

- **The Personal API gateway is an allowlist.** These Connect paths return `404 {"error":"NOT_FOUND"}`:
  `/workout-service/workouts`, `/calendar-service/year/{y}/month/{m}`,
  `/personalrecord-service/personalrecord/prs/me`,
  `/metrics-service/metrics/trainingstatus/aggregated/{date}`,
  `/metrics-service/metrics/trainingreadiness/{date}`, `/badge-service/badge/earned`,
  `/activity-service/activity/{id}/splits`, `/activity-service/activity/{id}/typedsplits`,
  `/activity-service/activity/{id}/split_summaries`, `/activity-service/activity/{id}/laps`,
  `/activity-service/activity/{id}/hrTimeInZones`, `/activity-service/activity/{id}/weather`,
  `/download-service/export/tcx/activity/{id}`, `/download-service/export/gpx/activity/{id}`,
  `/usersummary-service/stats/steps/weekly/...`, `/usersummary-service/stats/stress/weekly/...`,
  `/wellness-service/wellness/dailyStress/{date}`. These 404s are the evidence for the unsupported rows
  in GAP_ANALYSIS.md.
- The download is a ZIP with one entry `<id>_ACTIVITY.fit`. The Garmin FIT SDK decodes its `lap_mesgs`.
- Payload facts the projections rely on:
  - Distances are meters, durations seconds, speeds m/s.
  - Weight values (`weight`, `muscleMass`, `boneMass`) are **grams**.
  - Sleep timestamps are epoch **milliseconds**. The `*Local` variants are pre-shifted to local wall-clock
    time, so the CLI renders them as naive ISO strings.
  - `dailySleep` returns a flat object, not the Connect web app's `dailySleepDTO` wrapper. The projection
    accepts both.
  - Stress `overallStressLevel` is negative when there is not enough data. It projects to null.
  - Body Battery `bodyBatteryValuesArray` is `[[timestamp_ms, level], ...]`. Levels can be null.
  - Activity search items include `splitSummaries`, which was empty for the probed activity.

### Assumptions (CLI choices)

| Assumption | Why | Where to change |
|---|---|---|
| `GARMIN_API_BASE_URL` (the brief's name) and `GARMIN_PERSONAL_API_BASE_URL` (Garmin's name) both set the base URL | Satisfy the brief while staying compatible with Garmin's client | `client.Settings.from_env` |
| `GARMIN_API_KEY_HEADER` (default `Authorization`) and `GARMIN_API_KEY_SCHEME` (default `ApiKey`) configure the key header | The brief required configurability. The defaults are Garmin's documented choice | same |
| The key may live in an env file (`GARMIN_PERSONAL_API_KEY=...`, Alex's existing format) **or** a raw-key file | Alex's file is env-format, Garmin's default file is raw | `client.parse_key_text` |
| The token cache is separate from Garmin's (`~/.config/garmin-official-cli/bearer-token.json`) | Avoid coupling to another tool's file format | `GARMIN_BEARER_TOKEN_CACHE` |
| A single 401 on a data call triggers one forced re-exchange and retry | Garmin's client does not retry. One retry recovers from early revocation without loops | `PersonalApiClient.get_response` |
| `activityType=running` in the activity search includes subtypes (trail, treadmill...) | Connect behavior. The aggregation also filters on `"running" in typeKey` | `aggregate.is_running` |
| Activity search page size 100 | Not documented. Small enough to be safe | `commands/activity.PAGE_SIZE` |
| Daily-summaries chunk 31 days, although 60 worked | Margin below the observed 500 at 90 days | `endpoints.DAILY_SUMMARIES.max_days` |
| Weekly aggregations use Monday-start weeks | ISO convention. `stats weekly` has `--week-start sunday` | `dates.week_start` |

## Starter Business tier: Training API (not usable yet)

### Documented

- Starter includes the Activity, Courses, Health, Training and Women's Health APIs. **Push-only**, no
  historical data, limited user capacity. (S1)
- Business tiers authenticate per user through an OAuth flow for a registered app. Newer docs describe
  **OAuth 2.0 with PKCE** and `Authorization: Bearer <access token>`. (S6; historically OAuth 1.0a for
  the wellness APIs)

### Third-party report (S5)

- Workout create: `POST https://apis.garmin.com/training-api/workout`, JSON body with `workoutName`,
  `description`, `sport`, `steps[]`, each step with `durationType` (`TIME`, `DISTANCE`), `targetType`
  (`SPEED`, `HEART_RATE`, ...) and `intensity` (`WARMUP`, `ACTIVE`, `COOLDOWN`, ...).

### Assumptions (unverified until Starter docs and credentials exist)

| Assumption | Used in |
|---|---|
| Base URL `https://apis.garmin.com` (override `GARMIN_TRAINING_API_BASE_URL`) | `endpoints.TRAINING_DEFAULT_BASE_URL` |
| Schedule create: `POST /training-api/schedule` with `{"workoutId": <id>, "date": "YYYY-MM-DD"}` | `endpoints.TRAINING_SCHEDULE_CREATE`, `workout publish` |
| Create response is JSON containing `workoutId`. Schedule response is a schedule id (bare number or `{"scheduleId":...}`) | `workout publish` |
| Step wire format: `type` = `WorkoutStep` / `WorkoutRepeatStep`; `stepOrder` numbered globally depth-first; `intensity` ∈ `WARMUP, INTERVAL, ACTIVE, RECOVERY, REST, COOLDOWN`; `durationType` ∈ `TIME, DISTANCE, OPEN` (`durationValue` seconds / meters, `durationValueType: "METER"` for distance); `targetType` ∈ `OPEN, PACE, SPEED, HEART_RATE, POWER` with `targetValueLow/High` in m/s (pace and speed), bpm, or watts; repeat steps use `repeatType: "REPEAT_UNTIL_STEPS_CMPLT"` + `repeatValue` | `workouts/spec.py` |
| Sports map: running→`RUNNING`, cycling→`CYCLING`, swimming→`LAP_SWIMMING`, strength→`STRENGTH_TRAINING`, cardio→`CARDIO_TRAINING`, generic→`GENERIC` | `workouts/spec.SPORTS` |
| `workoutProvider` / `workoutSourceId` set to `garmin-official-cli` | `workouts/spec.PROVIDER` |
| The user access token is supplied out of band as `$GARMIN_TRAINING_API_TOKEN`. The CLI does not run the OAuth/PKCE flow, which needs a registered app and redirect URI that don't exist yet | `client.TrainingApiClient` |

**To do once Starter is approved:** fetch the Training API PDF from the portal, check every row above,
fix `workouts/spec.py` and `endpoints.py`, and add an OAuth 2.0 PKCE helper if a local flow is allowed.

## Enterprise tier

Not applied for. Adds the Golf API, historical backfill (1 month+) and push or ping/pull delivery (S1).
Nothing in this CLI depends on it.
