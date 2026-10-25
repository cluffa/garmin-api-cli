# Coaching with `garmin`: what a review needs and where it comes from

This maps a running coach's review checklist to the command and field that answers each item.
It was checked against real recordings (a Forerunner-class watch running structured workouts, Oct 2026)
and against Garmin's published Personal API spec (see `docs/API_NOTES.md`, S8). An agent can follow it
top to bottom.

Pass `--miles` everywhere if the athlete thinks in miles. `activity analyze` reports the watch's own
setting as `activity.device_units` (`statute` = miles).

## Recipe: review the last month

1. `garmin stats weekly`: volume per week, longest run, and per week `hr_zones_s` (running time in HR
   zones 1-5), `z1_z2_pct` (the easy share, for an 80/20 check) and summed `training_load`.
2. `garmin activity list --range -30d:today --limit 200`: every activity with `aerobic_te`, `te_label`,
   `training_load`, `avg_cadence_spm` and `hr_zones_s`. Pick the key sessions from here.
3. `garmin health hrv -30d:today`, `garmin health sleep -30d:today`, `garmin health heart-rate -30d:today`:
   the recovery trend (HRV status and baseline, sleep score, resting HR). Heart rate costs one request per day.
4. For each key run: `garmin activity analyze <id>`. This is one download and holds everything per run
   below. `garmin activity get <id>` adds the server-side fields (compliance score, stamina,
   Body Battery change, typed split summaries).
5. Zones, if needed outside an activity: `garmin api get /biometric-service/heartRateZones/v2`.

## The checklist, item by item

### Before the runs (context)

| Need | Source | Notes |
|---|---|---|
| What the run was meant to be | `activity analyze` → `workout` (name, description, one-line `summary`, `steps`); `activity workout <id>` from the API | Present whenever the run was a structured workout. Descriptions often carry the coach's intent ("leave the race in the legs"). |
| How it felt | `activity analyze` → `activity.rpe` (1-10), `activity.feel`; `activity get` → `rpe`, `feel`, `compliance_score` | Only when the athlete answered the post-run prompt. |
| Goal race, injuries, life stress | Not in any official API | Ask the athlete. `health stress` and `health sleep` show the physiological side only. |

### The month as a whole

| Need | Source |
|---|---|
| Weekly volume trend, spikes | `stats weekly` → `weeks[].km`/`mi`; `stats progress START END` for totals by type |
| Intensity mix (80/20) | `stats weekly` → `weeks[].hr_zones_s`, `z1_z2_pct`; per run `activity list` → `hr_zones_s` |
| Long run vs. week | `stats weekly` → `longest_run`, plus `activity list` distances |
| Consistency, hard days back-to-back | `activity list` dates with `te_label` / `aerobic_te` / `training_load` |
| Recovery trend | `health hrv`, `health sleep`, `health heart-rate` (resting HR), `health body-battery` |
| Specificity (hills, terrain) | `activity list` → `elevation_gain_m`, `type` (`trail_running`, `treadmill_running`) |
| Load | `activity list` → `training_load`; `stats weekly` → `weeks[].training_load` (runs only) |

### Every run (`activity analyze <id>`)

| Need | Field | Notes |
|---|---|---|
| Purpose, and did the run match it | `segments[].role` (`warmup`, `work`, `rep`, `recovery`, `cooldown`, `unplanned`), `segments[].planned`, `pct_of_planned` | Without a structured workout, segments are the recorded laps and `role` is the lap intensity. |
| HR vs. zones | `zones.hr` (session time and % per zone, with the boundaries the watch used), `segments[].hr_zones_s` (order in `zones.hr.segment_bucket_order`) | Zones are the watch's own (here % of LTHR). |
| Pace vs. HR | `segments[].pace`, `gap_pace`, `avg_hr`; compare across runs over weeks | `gap_pace` is the watch's grade-adjusted pace. |
| HR drift | `drift` (whole run, first 5 min skipped) and `segments[].decoupling` (steady segments of 15 min or more) | Pa:HR decoupling in %; under ~5% on a steady run is a solid base. Skipped for interval sessions and warmups. Grade is not corrected. |
| Splits | `splits.rows` (even km or mile from the per-second record, with `roles` showing which workout parts each split contains); `segments` (one per executed step) | Auto-lap laps and workout steps never mix: a 2 mi warmup auto-lapped into two miles is one segment. |
| Interval quality | `intervals[]`: `pace_by_rep`, `time_s_by_rep` / `distance_m_by_rep`, `in_target_reps`, `time_in_target_pct_by_rep`, `spread_pct`, `fade_pct`, `max_hr_by_rep`, `recovery_hr_end_by_rep`, `recovery_hr_drop_by_rep` | `fade_pct` is last rep vs. first (negative = slowed). Time in a pace target uses speed smoothed over 10 s. |
| Did the rep hit the target | `segments[].target`, `in_target` (segment average), `time_in_target_pct` | Pace, HR (bpm or % max), power (W or % FTP) and cadence targets are decoded. |
| Cadence and form | `segments[].avg_cadence` (steps/min for running), `step_length_m`, `gct_ms`, `vertical_ratio_pct`, `avg_power` | The FIT file stores one-foot cadence; every command reports steps/min (`cadence_unit`). |
| Elevation | `segments[].ascent_m`/`descent_m`, `splits.rows[].ascent_m`/`descent_m`, `gap_pace` | |
| Training load | `activity.training_load`, `aerobic_te`, `anaerobic_te`; `activity get` → `te_label`, `aerobic_te_message` | |
| Stops | `activity.paused_s`, `pauses[]` (timer offset and length), `segments[].elapsed_s` when it differs from `timer_s` | |
| Conditions | Not available | The Personal API exposes no weather, and these recordings carry no temperature. |
| The next day | `health hrv <date>`, `health sleep <date>`, `health heart-rate <date>` | |

## What is not available

- Weather and temperature (the Connect weather endpoint returns 404 on the Personal API).
- The athlete's saved workout library and calendar (`workout list` / `scheduled` are unsupported), so
  "what was planned but skipped" is not visible. Only workouts that were actually run come back.
- Training status, readiness and personal records (proprietary, no official API).
