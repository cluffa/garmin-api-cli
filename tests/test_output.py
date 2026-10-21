import json
import math

from garmin_official_cli import output


def test_envelopes():
    assert output.success([1]) == {"ok": True, "data": [1]}
    assert output.failure({"type": "api", "message": "x"}) == {"ok": False, "error": {"type": "api", "message": "x"}}


def test_render_formats():
    payload = output.success([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])
    assert output.render(payload, "json") == '{"ok":true,"data":[{"a":1,"b":"x"},{"a":2,"b":"y"}]}'
    assert json.loads(output.render(payload, "json-pretty")) == payload
    assert "\n  " in output.render(payload, "json-pretty")
    toon = output.render(payload, "toon")
    assert "ok: true" in toon and "{a,b}" in toon and "2,y" in toon


def test_render_cleans_nan_and_inf():
    text = output.render({"a": math.nan, "b": [math.inf, 1.5]}, "json")
    assert json.loads(text) == {"a": None, "b": [None, 1.5]}


def test_redaction_applies_to_every_format():
    output.register_secret("GCDC_supersecret_value")
    output.register_secret("short")  # too short to register; avoids redacting common words
    for fmt in output.FORMATS:
        text = output.render({"msg": "bad key GCDC_supersecret_value", "w": "short"}, fmt)
        assert "supersecret" not in text
        assert output.REDACTED in text
        assert "short" in text


def test_projection_helpers():
    obj = {"a": {"b": {"c": 3}}, "x": None}
    assert output.dig(obj, "a.b.c") == 3
    assert output.dig(obj, "a.z.c", "d") == "d"
    assert output.pick(obj, {"c": "a.b.c", "missing": "q"}) == {"c": 3, "missing": None}
    assert output.pick(None, {"c": "a"}) == {"c": None}
    assert output.round_or_none("1.234") == 1.23
    assert output.round_or_none(True) is None
    assert output.round_or_none(math.nan) is None
    assert output.scalars({"a": 1, "b": [1], "c": {"d": 1}, "e": "s"}) == {"a": 1, "e": "s"}
