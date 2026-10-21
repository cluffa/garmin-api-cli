# Brief: Rewrite garmin-connect-cli from scratch on the official Garmin Connect API

You are Claude Code, working autonomously in this directory:
`/home/hatch/workspace/garmin-connect-official-cli`

Alex (the owner) asked for his existing CLI (`cluffa/garmin-connect-cli`, an
agent-first CLI built on Garmin's *unofficial* internal Connect APIs) to be
rewritten from scratch using only the **official Garmin Connect Developer
Program APIs**. Build a brand-new codebase here. Do NOT modify the old repo
at `~/workspace/garmin-connect-cli`, and do NOT reuse its unofficial-API
client code — the interface conventions (below) should be re-implemented
fresh, informed by its README (read it for the UX contract only).

Work autonomously to completion. Do not stop to ask questions — where a
choice is needed, pick the sensible default, document it in REPORT.md, and
keep going. When done, write REPORT.md (see Deliverables).

## Background facts (verified 2026-10-21 by the parent agent)

### The official program has 3 tiers
Source: https://developer.garmin.com/gc-developer-program/overview/

- **Personal** (free, instant, ACTIVE for Alex): single user, own data only.
  Includes: Activity Data (JSON & .FIT), Health Data (JSON), Women's Health
  Data (JSON). Delivery: **Pull only**.
  Auth: a Personal API key (prefix `GCDC_`), created at
  connect.garmin.com/app/settings/personalApiToken. The key IS the
  credential — there is no separate token step in the settings flow, and
  Garmin's page lists no named scopes. Alex's key is stored at
  `~/.config/garmin/personal-api-key.env` (mode 600) as
  `GARMIN_PERSONAL_API_KEY=...`. **Never print, log, commit, or hardcode
  this key.** Read it from `$GARMIN_PERSONAL_API_KEY` or that env file.
  Expires Oct 21, 2027. Only ONE personal key may exist at a time.
- **Starter Business** (free, application SUBMITTED 2026-10-21, approval
  PENDING — no credentials exist yet): Activity API, Courses API, Health
  API, Training API, Women's Health API. Delivery: **Push only**.
  Historical data: NOT included. Limited user capacity.
- **Enterprise** (paid, not applied for): adds Golf API, historical backfill
  (1 month+), push or ping/pull, support.

### Key architectural constraints
- The official Business APIs are **cloud-to-cloud**: Health/Activity data is
  delivered by **push** (webhooks to a registered server endpoint) after a
  user OAuth flow (historically OAuth 1.0a for the wellness APIs; newer
  docs describe OAuth 2.0/PKCE in places — treat auth details as
  to-be-confirmed from Garmin's official docs/PDFs in the developer
  portal). A local CLI cannot pull Business-API data ad hoc the way the
  unofficial API allowed. Design for this honestly: Personal (pull) is the
  only tier a local CLI can use today.
- The official API reference PDFs live in Garmin's developer portal
  (e.g. Activity API / Health API documents under
  developerportal.garmin.com). Research them as far as they are publicly
  reachable. The Personal tier's exact base URL / auth header / endpoint
  paths were NOT publicly documented on launch day (2026-10-21) — so:
  - Make base URL and auth-header name **configurable** via environment
    (`GARMIN_API_BASE_URL`, `GARMIN_API_KEY_HEADER`), with defaults set to
    your best-documented official choice, and every assumption recorded in
    `docs/API_NOTES.md` with its source.
  - Build the HTTP layer against an interface so endpoint paths live in ONE
    module (`endpoints.py`) and can be corrected in one place.
  - All tests must pass WITHOUT network access or the real key (fixtures /
  recorded sample payloads based on the official Health/Activity summary
    shapes, plus a fake transport).

### Old CLI feature inventory (from its README) and the gap analysis
Old command groups: `auth`, `workout`, `activity`, `health`, `stats`,
`badge`, `capabilities`. UX contract to preserve in the rewrite:
- JSON envelope `{"ok":true,"data":...}` / `{"ok":false,"error":{...}}`
- Exit codes: 0 success, 1 internal, 2 usage, 3 auth, 4 API
- `--format json|json-pretty|toon`, `--full` for raw payloads
- Unified date specs: `today`, `yesterday`, `-7d`, `+7d`, `YYYY-MM-DD`,
  ranges `start:end` (cap 366 days unless `--max-days`)
- `capabilities` one-call discovery
- Slim projections by default

Gap analysis (implement / stub-as-unsupported accordingly):
- `activity list|get` — SUPPORTED (Activity API: summaries + details, JSON).
- `activity download` — PARTIAL: official gives .FIT only. TCX/GPX export
  NOT supported. Implement FIT download; make tcx/gpx return the
  unsupported envelope (below).
- `activity splits` — SUPPORTED via activity details (laps/samples), as far
  as the official detail payload provides it; otherwise a local projection.
- `health steps|heart-rate|sleep|stress|weight` — SUPPORTED (Health API:
  dailies, sleeps, body-composition and related summaries).
- `health hrv` — implement if the official Health summaries you find in
  the docs include HRV; otherwise unsupported-stub it and say why.
- `health body-battery` — NOT in the standard official Health data types;
  unsupported-stub unless the docs you find say otherwise.
- `health weekly-steps|weekly-stress` — SUPPORTED as local aggregation over
  dailies (or range summaries where available).
- `stats summary` — SUPPORTED (≈ Health dailies).
- `stats weekly`, `stats progress` — SUPPORTED as local aggregation over
  official activity/health data.
- `stats records` — NOT supported (personal records are not an official
  API data type). Stub.
- `stats training-status`, `stats readiness` — NOT supported (Garmin
  Connect proprietary derived metrics; not official API data types). Stub.
- `badge *` (earned / in-progress / available / adhoc / challenges) — NOT
  supported (no official badges API). Stub the whole group.
- `workout *` (validate / create / list / get / delete / schedule /
  unschedule / scheduled / schema) — Training API is **publish-only** and
  **Starter-tier, approval pending, push/cloud model**: it can publish a
  structured workout/plan to Garmin Connect for device sync, but the
  official API has NO workout-library or calendar management (no list/get
  saved workouts, no delete, no schedule-existing-workout-to-date, no
  unschedule, no list-scheduled). Therefore:
  - `workout validate` + `workout schema`: implement LOCALLY (pure spec
    validation + translation toward the official Training API workout
    format — this is local logic, no network, same as the old CLI).
  - `workout publish` (new command name, replaces `create`): implement the
    client call behind the Starter-credentials boundary; while Starter
    credentials do not exist, it must return the unsupported envelope
    naming the blocker (Starter approval pending) rather than faking it.
  - list/get/delete/schedule/unschedule/scheduled: unsupported-stubs.
- `auth login` (email/password + MFA) — GONE by design in the official
  model. Replace with `auth status` (is a Personal key configured? does
  the env file exist? expiry note) and `auth set-key` guidance. No
  password handling anywhere.
- `capabilities` — implement, and it MUST include each command's support
  status (`supported` / `partial` / `unsupported` + reason + tier).

### Unsupported-command behavior (important, uniform)
Every unsupported feature must exist as a command that returns:
`{"ok":false,"error":{"type":"unsupported","message":"...","reason":"...","tier_required":"..."}}`
on stderr with exit code 4, and be listed in `GAP_ANALYSIS.md`. No silent
omissions, no fake data.

## What to build
- Python 3.12+ `uv` project, package `garmin_official_cli`, console script
  name **`garmin-official`** (must not shadow the installed old `garmin`).
- Clean layers: `client.py` (HTTP + auth from env), `endpoints.py`,
  `dates.py`, `output.py` (envelope/formats/projections), `commands/`
  (auth, activity, health, stats, workout, badge, meta/capabilities),
  `models.py` as needed.
- Tests with `pytest`: envelope/exit-code behavior, date-spec parsing,
  projections, unsupported-stub behavior, activity/health parsing against
  fixture payloads, workout spec validation/translation. Suite must pass
  offline.
- `.gitignore` that excludes `.env` and any key material; a test or lint
  check that the real key string never appears in the repo.
- Init a git repo here and make one clean initial commit (author: use the
  repo's existing global git identity; do not push anywhere).

## Deliverables
1. The working codebase with passing tests (`uv run pytest` green).
2. `README.md` — setup (key configuration), command reference with support
   status per command.
3. `GAP_ANALYSIS.md` — every old-CLI command mapped to
   supported / partial / unsupported, with tier and reason. This is the
   document Alex will read to learn what the official API cannot do.
4. `docs/API_NOTES.md` — endpoint/auth assumptions and their sources,
   clearly separating documented facts from assumptions.
5. `REPORT.md` — what you built, test results, design decisions, open
   questions/assumptions, and the exact list of unsupported features.

Go.
