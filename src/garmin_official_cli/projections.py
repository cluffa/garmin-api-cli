"""Slim projections of official payloads. ``--full`` bypasses all of these.

Shapes follow the live Personal API responses observed 2026-10-21 (see
docs/API_NOTES.md). Missing fields project to null rather than failing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .output import as_list, dig, pick, round_or_none

M_PER_MI = 1609.344
FEEL = {0: "very_weak", 25: "weak", 50: "normal", 75: "strong", 100: "very_strong"}


def distance(meters: Any, miles: bool) -> float | None:
    m = round_or_none(meters, 3)
    if m is None:
        return None
    return round(m / M_PER_MI, 2) if miles else round(m / 1000, 2)


def pace(speed_mps: Any, miles: bool) -> str | None:
    """m/s -> ``"m:ss/km"`` or ``"m:ss/mi"``."""
    v = round_or_none(speed_mps, 6)
    if not v or v <= 0:
        return None
    secs = round((M_PER_MI if miles else 1000) / v)
    return f"{secs // 60}:{secs % 60:02d}/{'mi' if miles else 'km'}"


def ms_to_iso(ms: Any) -> str | None:
    """Epoch milliseconds -> ISO string (UTC wall-clock; Garmin "Local" stamps are pre-shifted)."""
    if not isinstance(ms, (int, float)) or isinstance(ms, bool):
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def rpe(value: Any) -> float | None:
    """Garmin stores self-reported RPE as 10-100; the athlete picked 1-10."""
    v = round_or_none(value, 1)
    return round(v / 10, 1) if v is not None else None


def feel(value: Any) -> str | None:
    """Self-reported workout feel, stored as 0/25/50/75/100."""
    v = round_or_none(value, 0)
    return FEEL.get(int(v), str(int(v))) if v is not None else None


def lower(value: Any) -> str | None:
    return value.lower() if isinstance(value, str) else None


def hr_zone_seconds(a: dict[str, Any]) -> list[float] | None:
    """Activity-search time in HR zones 1-5, in seconds."""
    zones = [round_or_none(a.get(f"hrTimeInZone_{i}"), 0) for i in range(1, 6)]
    return [z or 0 for z in zones] if any(z is not None for z in zones) else None


# --- activities ---------------------------------------------------------------


def activity_summary(a: dict[str, Any], *, miles: bool = False) -> dict[str, Any]:
    unit = "mi" if miles else "km"
    return {
        "id": a.get("activityId"),
        "name": a.get("activityName"),
        "type": dig(a, "activityType.typeKey"),
        "start_local": a.get("startTimeLocal"),
        "duration_s": round_or_none(a.get("duration"), 1),
        "moving_s": round_or_none(a.get("movingDuration"), 1),
        f"distance_{unit}": distance(a.get("distance"), miles),
        "pace": pace(a.get("averageSpeed"), miles),
        "avg_hr": round_or_none(a.get("averageHR"), 0),
        "max_hr": round_or_none(a.get("maxHR"), 0),
        "calories": round_or_none(a.get("calories"), 0),
        "elevation_gain_m": round_or_none(a.get("elevationGain"), 1),
        "training_load": round_or_none(a.get("activityTrainingLoad"), 1),
        "aerobic_te": round_or_none(a.get("aerobicTrainingEffect"), 1),
        "te_label": lower(a.get("trainingEffectLabel")),
        "avg_cadence_spm": round_or_none(a.get("averageRunningCadenceInStepsPerMinute"), 0),
        "hr_zones_s": hr_zone_seconds(a),
    }


def split_summaries(rows: Any) -> list[dict[str, Any]]:
    return [
        {
            "type": lower(r.get("splitType")),
            "count": r.get("noOfSplits"),
            "distance_m": round_or_none(r.get("distance"), 1),
            "duration_s": round_or_none(r.get("duration"), 1),
        }
        for r in as_list(rows)
        if isinstance(r, dict)
    ]


def activity_detail(a: dict[str, Any], *, miles: bool = False) -> dict[str, Any]:
    s = a.get("summaryDTO") or {}
    unit = "mi" if miles else "km"
    return {
        "id": a.get("activityId"),
        "name": a.get("activityName"),
        "type": dig(a, "activityTypeDTO.typeKey"),
        "location": a.get("locationName"),
        "start_local": s.get("startTimeLocal"),
        "start_gmt": s.get("startTimeGMT"),
        "duration_s": round_or_none(s.get("duration"), 1),
        "moving_s": round_or_none(s.get("movingDuration"), 1),
        "elapsed_s": round_or_none(s.get("elapsedDuration"), 1),
        f"distance_{unit}": distance(s.get("distance"), miles),
        "pace": pace(s.get("averageSpeed"), miles),
        "avg_speed_mps": round_or_none(s.get("averageSpeed"), 3),
        "avg_hr": round_or_none(s.get("averageHR"), 0),
        "max_hr": round_or_none(s.get("maxHR"), 0),
        "avg_power": round_or_none(s.get("averagePower"), 0),
        "normalized_power": round_or_none(s.get("normalizedPower"), 0),
        "calories": round_or_none(s.get("calories"), 0),
        "elevation_gain_m": round_or_none(s.get("elevationGain"), 1),
        "elevation_loss_m": round_or_none(s.get("elevationLoss"), 1),
        "aerobic_te": round_or_none(s.get("trainingEffect"), 1),
        "anaerobic_te": round_or_none(s.get("anaerobicTrainingEffect"), 1),
        "te_label": lower(s.get("trainingEffectLabel")),
        "aerobic_te_message": lower(s.get("aerobicTrainingEffectMessage")),
        "anaerobic_te_message": lower(s.get("anaerobicTrainingEffectMessage")),
        "training_load": round_or_none(s.get("activityTrainingLoad"), 1),
        "rpe": rpe(s.get("directWorkoutRpe")),
        "feel": feel(s.get("directWorkoutFeel")),
        "compliance_score": s.get("directWorkoutComplianceScore"),
        "gap_pace": pace(s.get("avgGradeAdjustedSpeed"), miles),
        "avg_cadence_spm": round_or_none(s.get("averageRunCadence"), 0),
        "stride_length_m": round(v / 100, 2) if (v := round_or_none(s.get("strideLength"), 2)) is not None else None,
        "gct_ms": round_or_none(s.get("groundContactTime"), 0),
        "vertical_oscillation_cm": round_or_none(s.get("verticalOscillation"), 1),
        "vertical_ratio_pct": round_or_none(s.get("verticalRatio"), 1),
        "intensity_min": {"moderate": s.get("moderateIntensityMinutes"), "vigorous": s.get("vigorousIntensityMinutes")},
        "body_battery_change": s.get("differenceBodyBattery"),
        "stamina_start_pct": round_or_none(s.get("beginPotentialStamina"), 0),
        "stamina_end_pct": round_or_none(s.get("endPotentialStamina"), 0),
        "split_summaries": split_summaries(a.get("splitSummaries")),
        "lap_count": dig(a, "metadataDTO.lapCount"),
        "file_format": dig(a, "metadataDTO.fileFormat.formatKey"),
        "device_manufacturer": dig(a, "metadataDTO.manufacturer"),
    }


def activity_samples(details: dict[str, Any]) -> dict[str, Any]:
    """Turn the details payload's index-addressed metric rows into named columns."""
    keys = [d.get("key") for d in sorted(as_list(details.get("metricDescriptors")), key=lambda d: d.get("metricsIndex", 0))]
    rows = []
    for row in as_list(details.get("activityDetailMetrics")):
        values = row.get("metrics") or []
        rows.append({k: (values[i] if i < len(values) else None) for i, k in enumerate(keys)})
    return {"metrics": keys, "count": len(rows), "samples": rows}


# --- health -------------------------------------------------------------------


def steps_day(d: dict[str, Any]) -> dict[str, Any]:
    return pick(d, {"date": "calendarDate", "steps": "totalSteps", "goal": "stepGoal", "distance_m": "totalDistance"})


def stress_day(d: dict[str, Any]) -> dict[str, Any]:
    out = pick(
        d,
        {
            "date": "calendarDate",
            "avg_stress": "values.overallStressLevel",
            "rest_s": "values.restStressDuration",
            "low_s": "values.lowStressDuration",
            "medium_s": "values.mediumStressDuration",
            "high_s": "values.highStressDuration",
        },
    )
    # Garmin uses negative levels for "not enough data".
    if isinstance(out["avg_stress"], (int, float)) and out["avg_stress"] < 0:
        out["avg_stress"] = None
    return out


def sleep_day(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d:
        return None
    d = d.get("dailySleepDTO", d)  # tolerate the wrapped Connect shape
    if not d.get("calendarDate") and not d.get("sleepTimeSeconds"):
        return None
    return {
        "date": d.get("calendarDate"),
        "sleep_s": d.get("sleepTimeSeconds"),
        "deep_s": d.get("deepSleepSeconds"),
        "light_s": d.get("lightSleepSeconds"),
        "rem_s": d.get("remSleepSeconds"),
        "awake_s": d.get("awakeSleepSeconds"),
        "nap_s": d.get("napTimeSeconds"),
        "start_local": ms_to_iso(d.get("sleepStartTimestampLocal")),
        "end_local": ms_to_iso(d.get("sleepEndTimestampLocal")),
        "score": dig(d, "sleepScores.overall.value"),
        "score_qualifier": dig(d, "sleepScores.overall.qualifierKey"),
        "avg_hr": round_or_none(d.get("avgHeartRate"), 0),
        "avg_respiration": round_or_none(d.get("averageRespirationValue"), 1),
        "avg_sleep_stress": round_or_none(d.get("avgSleepStress"), 1),
        "awake_count": d.get("awakeCount"),
        "feedback": d.get("sleepScoreFeedback"),
    }


def heart_rate_day(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d:
        return None
    return {
        **pick(
            d,
            {
                "date": "calendarDate",
                "resting_hr": "restingHeartRate",
                "min_hr": "minHeartRate",
                "max_hr": "maxHeartRate",
                "resting_hr_7d_avg": "lastSevenDaysAvgRestingHeartRate",
            },
        ),
        "samples": len(as_list(d.get("heartRateValues"))),
    }


def hrv_summary(s: dict[str, Any] | None) -> dict[str, Any] | None:
    if not s:
        return None
    return pick(
        s,
        {
            "date": "calendarDate",
            "last_night_avg": "lastNightAvg",
            "last_night_5min_high": "lastNight5MinHigh",
            "weekly_avg": "weeklyAvg",
            "status": "status",
            "baseline_low": "baseline.balancedLow",
            "baseline_high": "baseline.balancedUpper",
            "feedback": "feedbackPhrase",
        },
    )


def hrv_day(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d:
        return None
    out = hrv_summary(d.get("hrvSummary"))
    if out is None:
        return None
    out["readings"] = len(as_list(d.get("hrvReadings")))
    return out


def body_battery_day(d: dict[str, Any]) -> dict[str, Any]:
    levels = [v[1] for v in as_list(d.get("bodyBatteryValuesArray")) if isinstance(v, list) and len(v) > 1 and v[1] is not None]
    return {
        "date": d.get("date"),
        "charged": d.get("charged"),
        "drained": d.get("drained"),
        "highest": max(levels) if levels else None,
        "lowest": min(levels) if levels else None,
        "end_of_day_level": dig(d, "endOfDayBodyBatteryDynamicFeedbackEvent.bodyBatteryLevel"),
        "end_of_day_feedback": dig(d, "endOfDayBodyBatteryDynamicFeedbackEvent.feedbackShortType"),
    }


def _grams_to_kg(value: Any) -> float | None:
    v = round_or_none(value, 1)
    return round(v / 1000, 2) if v is not None else None


def weight_day(d: dict[str, Any]) -> dict[str, Any]:
    latest = d.get("latestWeight") or {}
    return {
        "date": d.get("summaryDate") or latest.get("calendarDate"),
        "weight_kg": _grams_to_kg(latest.get("weight")),
        "bmi": round_or_none(latest.get("bmi"), 1),
        "body_fat_pct": round_or_none(latest.get("bodyFat"), 1),
        "body_water_pct": round_or_none(latest.get("bodyWater"), 1),
        "muscle_mass_kg": _grams_to_kg(latest.get("muscleMass")),
        "bone_mass_kg": _grams_to_kg(latest.get("boneMass")),
        "entries": d.get("numOfWeightEntries"),
        "source": latest.get("sourceType"),
    }


def hydration_day(d: dict[str, Any]) -> dict[str, Any]:
    """Daily hydration record (fields per Garmin's API description, S8 ecosystem clients).

    Live-verified only as an empty list on 2026-11-23: this account logs no hydration
    in Garmin Connect, so every field projects to null until a recorded day exists.
    """
    return pick(
        d,
        {
            "date": "calendarDate",
            "hydration_ml": "valueInML",
            "goal_ml": "goalInML",
            "sweat_loss_ml": "sweatLossInML",
            "activity_intake_ml": "activityIntakeInML",
            "last_entry_local": "lastEntryTimestampLocal",
        },
    )


def weight_goal(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Effective weight goal(s) from the goal-service payload (goalValue is grams)."""
    out = []
    for g in as_list((payload or {}).get("userGoals")):
        if not isinstance(g, dict):
            continue
        out.append(
            {
                **pick(
                    g,
                    {
                        "category": "userGoalCategory",
                        "type": "userGoalType",
                        "name": "goalName",
                        "start_date": "startDate",
                        "end_date": "endDate",
                        "tracking_period": "trackingPeriodType",
                        "created": "createDate",
                        "updated": "updateDate",
                    },
                ),
                "goal_kg": _grams_to_kg(g.get("goalValue")) if g.get("userGoalType") == "WEIGHT_GRAMS" else None,
                "goal_value": g.get("goalValue"),
            }
        )
    return out


def weight_entry(e: dict[str, Any]) -> dict[str, Any]:
    """One weigh-in from weight/all (per-entry, unlike weight/range's daily summaries)."""
    return {
        "date": e.get("calendarDate"),
        "timestamp_gmt": ms_to_iso(e.get("timestampGMT")),
        "weight_kg": _grams_to_kg(e.get("weight")),
        "bmi": round_or_none(e.get("bmi"), 1),
        "body_fat_pct": round_or_none(e.get("bodyFat"), 1),
        "body_water_pct": round_or_none(e.get("bodyWater"), 1),
        "muscle_mass_kg": _grams_to_kg(e.get("muscleMass")),
        "bone_mass_kg": _grams_to_kg(e.get("boneMass")),
        "visceral_fat": round_or_none(e.get("visceralFat"), 1),
        "metabolic_age": round_or_none(e.get("metabolicAge"), 0),
        "physique_rating": round_or_none(e.get("physiqueRating"), 0),
        "weight_delta_kg": _grams_to_kg(e.get("weightDelta")),
    }


def _macro_block(b: dict[str, Any] | None) -> dict[str, Any]:
    return pick(
        b or {},
        {
            "calories": "calories",
            "calories_adjusted": "adjustedCalories",
            "carbs_g": "carbs",
            "carbs_adjusted_g": "adjustedCarbs",
            "fat_g": "fat",
            "fat_adjusted_g": "adjustedFat",
            "protein_g": "protein",
            "protein_adjusted_g": "adjustedProtein",
        },
    )


def _food_entry(f: dict[str, Any]) -> dict[str, Any]:
    return {
        **pick(
            f,
            {
                "food_id": "foodId",
                "name": "foodName",
                "brand": "brandName",
                "amount": "amountInGrams",
                "unit": "unitName",
                "serving_size_g": "servingSizeInGrams",
                "servings": "numberOfServings",
            },
        ),
        **{
            k: round_or_none(f.get(src), 1)
            for k, src in (
                ("calories", "calories"),
                ("carbs_g", "carbs"),
                ("fat_g", "fat"),
                ("protein_g", "protein"),
                ("sugar_g", "sugar"),
                ("sodium_mg", "sodium"),
                ("fiber_g", "fiber"),
            )
        },
    }


def food_log_day(d: dict[str, Any] | None) -> dict[str, Any] | None:
    """One day of Garmin nutrition logs: goals plus per-meal logged foods."""
    if not d:
        return None
    meals = []
    for m in as_list(d.get("mealDetails")):
        if not isinstance(m, dict):
            continue
        meal = m.get("meal") or {}
        meals.append(
            {
                "meal_id": meal.get("mealId"),
                "meal_name": meal.get("mealName"),
                "goals": _macro_block(m.get("mealNutritionGoals")),
                "foods": [_food_entry(f) for f in as_list(m.get("loggedFoods")) if isinstance(f, dict)],
            }
        )
    return {
        "date": d.get("mealDate"),
        "day_start": d.get("dayStartTime"),
        "day_end": d.get("dayEndTime"),
        "goals": _macro_block(d.get("dailyNutritionGoals")),
        "meals": meals,
        "foods": [_food_entry(f) for f in as_list(d.get("loggedFoodsWithServingSizes")) if isinstance(f, dict)],
    }


def user_settings(s: dict[str, Any] | None) -> dict[str, Any] | None:
    """Profile display/format preferences. The raw payload's displayName (an opaque
    account UUID on this account) is deliberately not projected."""
    if not s:
        return None
    return {
        **pick(
            s,
            {
                "locale": "preferredLocale",
                "measurement_system": "measurementSystem",
                "number_format": "numberFormat",
                "time_zone": "timeZone",
                "hydration_unit": "hydrationMeasurementUnit",
                "golf_distance_unit": "golfDistanceUnit",
                "golf_elevation_unit": "golfElevationUnit",
                "golf_speed_unit": "golfSpeedUnit",
            },
        ),
        "first_day_of_week": dig(s, "firstDayOfWeek.dayName"),
        "time_format": dig(s, "timeFormat.formatKey"),
        "date_format": dig(s, "dateFormat.formatKey"),
        "power_format": dig(s, "powerFormat.formatKey"),
        "heart_rate_format": dig(s, "heartRateFormat.formatKey"),
        "hydration_containers": [
            pick(c, {"name": "name", "volume": "volume", "unit": "unit"})
            for c in as_list(s.get("hydrationContainers"))
            if isinstance(c, dict)
        ],
    }


def hr_zones(rows: Any) -> list[dict[str, Any]]:
    """Heart-rate zone definitions per sport: floors expanded into [low, high] ranges.

    Zone i spans floor_i .. floor_{i+1} - 1; zone 5 tops out at maxHeartRateUsed.
    """
    out = []
    for r in as_list(rows):
        if not isinstance(r, dict):
            continue
        floors = [round_or_none(r.get(f"zone{i}Floor"), 0) for i in range(1, 6)]
        max_hr = round_or_none(r.get("maxHeartRateUsed"), 0)
        zones = []
        for i, low in enumerate(floors):
            high = (floors[i + 1] - 1) if i + 1 < len(floors) and floors[i + 1] is not None else max_hr
            zones.append({"zone": i + 1, "low": low, "high": high})
        out.append(
            {
                "sport": r.get("sport"),
                "method": r.get("trainingMethod"),
                "max_hr_used": max_hr,
                "lactate_threshold_hr_used": round_or_none(r.get("lactateThresholdHeartRateUsed"), 0),
                "resting_hr_used": round_or_none(r.get("restingHeartRateUsed"), 0),
                "resting_hr_auto_update": r.get("restingHrAutoUpdateUsed"),
                "zones": zones,
            }
        )
    return out


def fitness_age(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d:
        return None
    out = pick(
        d,
        {
            "chronological_age": "chronologicalAge",
            "fitness_age": "fitnessAge",
            "achievable_fitness_age": "achievableFitnessAge",
            "previous_fitness_age": "previousFitnessAge",
            "last_updated": "lastUpdated",
        },
    )
    for key in ("fitness_age", "achievable_fitness_age", "previous_fitness_age"):
        out[key] = round_or_none(out[key], 1)
    components = {}
    for name, c in ((d.get("components") or {}).items() if isinstance(d.get("components"), dict) else []):
        if isinstance(c, dict):
            components[name] = pick(
                c,
                {
                    "value": "value",
                    "target_value": "targetValue",
                    "improvement_value": "improvementValue",
                    "potential_age": "potentialAge",
                    "priority": "priority",
                    "stale": "stale",
                    "last_measurement_date": "lastMeasurementDate",
                },
            )
    out["components"] = components
    return out


def spo2_day(d: dict[str, Any] | None) -> dict[str, Any] | None:
    """SpO2 + altitude-acclimation day. The hourly series are reduced to counts:
    Garmin fills the level column with altitude (meters) even when SpO2 is null."""
    if not d:
        return None
    hourly = [v for v in as_list(d.get("spO2HourlyAverages")) if isinstance(v, list)]
    readings = [v[1] for v in hourly if len(v) > 1 and v[1] is not None]
    env_levels = [v[2] for v in hourly if len(v) > 2 and v[2] is not None]
    return {
        **pick(
            d,
            {
                "date": "calendarDate",
                "avg_spo2": "averageSpO2",
                "lowest_spo2": "lowestSpO2",
                "latest_spo2": "latestSpO2",
                "avg_7d_spo2": "lastSevenDaysAvgSpO2",
                "avg_sleep_spo2": "avgSleepSpO2",
                "latest_spo2_local": "latestSpO2TimestampLocal",
                "sleep_start_local": "sleepStartTimestampLocal",
                "sleep_end_local": "sleepEndTimestampLocal",
            },
        ),
        "hourly_readings": len(readings),
        "altitude_acclimation_m": round_or_none(env_levels[-1], 0) if env_levels else None,
    }


def user_summary_day(d: dict[str, Any] | None) -> dict[str, Any] | None:
    """The v1 per-day user summary (usersummary/daily?calendarDate=).

    Distinct from `stats summary` (v2 dailysummaries): this one carries calorie
    consumed/remaining against the net goal, floors in meters, stress durations
    and Body Battery during sleep. Account ids and the day UUID are not projected.
    """
    if not d:
        return None
    return pick(
        d,
        {
            "date": "calendarDate",
            "steps": "totalSteps",
            "step_goal": "dailyStepGoal",
            "distance_m": "totalDistanceMeters",
            "wellness_distance_m": "wellnessDistanceMeters",
            "calories_total": "totalKilocalories",
            "calories_active": "activeKilocalories",
            "calories_bmr": "bmrKilocalories",
            "calories_consumed": "consumedKilocalories",
            "calories_remaining": "remainingKilocalories",
            "net_calorie_goal": "netCalorieGoal",
            "floors_up": "floorsAscended",
            "floors_down": "floorsDescended",
            "floors_up_m": "floorsAscendedInMeters",
            "floors_goal": "userFloorsAscendedGoal",
            "intensity_moderate_min": "moderateIntensityMinutes",
            "intensity_vigorous_min": "vigorousIntensityMinutes",
            "intensity_goal_min": "intensityMinutesGoal",
            "highly_active_s": "highlyActiveSeconds",
            "active_s": "activeSeconds",
            "sedentary_s": "sedentarySeconds",
            "sleeping_s": "sleepingSeconds",
            "min_hr": "minHeartRate",
            "max_hr": "maxHeartRate",
            "resting_hr": "restingHeartRate",
            "resting_hr_7d_avg": "lastSevenDaysAvgRestingHeartRate",
            "stress_avg": "averageStressLevel",
            "stress_max": "maxStressLevel",
            "stress_qualifier": "stressQualifier",
            "stress_s": "stressDuration",
            "rest_stress_s": "restStressDuration",
            "low_stress_s": "lowStressDuration",
            "medium_stress_s": "mediumStressDuration",
            "high_stress_s": "highStressDuration",
            "body_battery_charged": "bodyBatteryChargedValue",
            "body_battery_drained": "bodyBatteryDrainedValue",
            "body_battery_high": "bodyBatteryHighestValue",
            "body_battery_low": "bodyBatteryLowestValue",
            "body_battery_latest": "bodyBatteryMostRecentValue",
            "body_battery_sleep": "bodyBatteryDuringSleep",
            "body_battery_wake": "bodyBatteryAtWakeTime",
            "spo2_avg": "averageSpo2",
            "spo2_lowest": "lowestSpo2",
            "spo2_latest": "latestSpo2",
            "source": "source",
            "includes_wellness": "includesWellnessData",
            "includes_activity": "includesActivityData",
            "includes_calories_consumed": "includesCalorieConsumedData",
        },
    )


def daily_summary(d: dict[str, Any]) -> dict[str, Any]:
    return pick(
        d,
        {
            "date": "calendarDate",
            "steps": "movement.steps.value",
            "step_goal": "movement.steps.goal",
            "distance_m": "movement.steps.distanceInMeters",
            "floors_up": "movement.floorsAscended.value",
            "calories_total": "calories.burnedTotal",
            "calories_active": "calories.burnedActive",
            "calories_resting": "calories.burnedResting",
            "resting_hr": "heartRate.restingValue",
            "min_hr": "heartRate.minValue",
            "max_hr": "heartRate.maxValue",
            "intensity_moderate_min": "intensityMinutes.moderate",
            "intensity_vigorous_min": "intensityMinutes.vigorous",
            "intensity_goal_min": "intensityMinutes.goal",
            "stress_avg": "stress.avgLevel",
            "stress_max": "stress.maxLevel",
            "stress_qualifier": "stress.qualifier",
            "body_battery_min": "bodyBattery.minValue",
            "body_battery_max": "bodyBattery.maxValue",
            "body_battery_charged": "bodyBattery.chargedValue",
            "body_battery_drained": "bodyBattery.drainedValue",
            "body_battery_latest": "bodyBattery.latestValue",
            "respiration_avg": "respiration.avgValue",
            "spo2_avg": "pulseOx.avgValue",
            "hydration_ml": "hydration.consumedInMl",
        },
    )
