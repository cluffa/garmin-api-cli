"""Build tiny synthetic FIT files for tests (no real recordings in the repo)."""

from __future__ import annotations

import struct
from datetime import UTC, datetime

FIT_EPOCH = 631065600  # 1989-12-31T00:00:00Z
_CRC_TABLE = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
              0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]


def crc16(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = _CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[byte & 0xF]
        tmp = _CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc


# (field number, size, base type, struct code)
_FILE_ID = [(0, 1, 0x00, "B"), (4, 4, 0x86, "I")]
_LAP = [
    (254, 2, 0x84, "H"),  # message_index
    (2, 4, 0x86, "I"),  # start_time
    (7, 4, 0x86, "I"),  # total_elapsed_time (s * 1000)
    (8, 4, 0x86, "I"),  # total_timer_time (s * 1000)
    (9, 4, 0x86, "I"),  # total_distance (m * 100)
    (13, 2, 0x84, "H"),  # avg_speed (m/s * 1000)
    (15, 1, 0x02, "B"),  # avg_heart_rate
    (16, 1, 0x02, "B"),  # max_heart_rate
    (23, 1, 0x00, "B"),  # intensity (0 active, 1 rest, 2 warmup, 3 cooldown)
    (24, 1, 0x00, "B"),  # lap_trigger (0 manual, 1 time, 2 distance, 7 session_end)
]


def _definition(local: int, global_num: int, fields) -> bytes:
    out = struct.pack("<BBBHB", 0x40 | local, 0, 0, global_num, len(fields))
    for num, size, base, _ in fields:
        out += struct.pack("<BBB", num, size, base)
    return out


def _data(local: int, fields, values) -> bytes:
    return bytes([local]) + b"".join(struct.pack("<" + code, v) for (_, _, _, code), v in zip(fields, values))


def _frame(body: bytes) -> bytes:
    header = struct.pack("<BBHI4s", 14, 0x20, 2132, len(body), b".FIT")
    header += struct.pack("<H", crc16(header))
    content = header + body
    return content + struct.pack("<H", crc16(content))


def build_fit(laps: list[dict]) -> bytes:
    """laps: dicts with start (datetime), elapsed_s, timer_s, distance_m, speed_mps, avg_hr, max_hr, intensity, trigger."""
    start0 = laps[0]["start"] if laps else datetime(2026, 10, 1, tzinfo=UTC)
    body = _definition(0, 0, _FILE_ID) + _data(0, _FILE_ID, [4, int(start0.timestamp()) - FIT_EPOCH])
    body += _definition(1, 19, _LAP)
    for i, lap in enumerate(laps):
        body += _data(1, _LAP, [
            i,
            int(lap["start"].timestamp()) - FIT_EPOCH,
            round(lap["elapsed_s"] * 1000),
            round(lap["timer_s"] * 1000),
            round(lap["distance_m"] * 100),
            round(lap["speed_mps"] * 1000),
            lap["avg_hr"],
            lap["max_hr"],
            lap.get("intensity", 0),
            lap.get("trigger", 2),
        ])
    return _frame(body)


# --- generic messages ---------------------------------------------------------

# base type -> (FIT base type byte, struct code, size)
BASE = {"enum": (0x00, "B", 1), "u8": (0x02, "B", 1), "u16": (0x84, "H", 2), "u32": (0x86, "I", 4), "s32": (0x85, "i", 4)}
MESG = {"file_id": 0, "session": 18, "lap": 19, "record": 20, "event": 21, "workout": 26, "workout_step": 27,
        "time_in_zone": 216}


def ts(dt: datetime) -> int:
    return int(dt.timestamp()) - FIT_EPOCH


def message(local: int, name: str, fields: list[tuple[int, str, object]]) -> bytes:
    """One definition + data record. fields: (field number, base type or "str", value or list of values)."""
    defs, payload = [], b""
    for num, kind, value in fields:
        if kind == "str":
            raw = str(value).encode() + b"\x00"
            defs.append((num, len(raw), 0x07, None))
            payload += raw
            continue
        base, code, size = BASE[kind]
        values = value if isinstance(value, list) else [value]
        defs.append((num, size * len(values), base, None))
        payload += struct.pack("<" + code * len(values), *values)
    out = struct.pack("<BBBHB", 0x40 | local, 0, 0, MESG[name], len(defs))
    for num, size, base, _ in defs:
        out += struct.pack("<BBB", num, size, base)
    return out + bytes([local]) + payload


def build_messages(start: datetime, records: list[bytes]) -> bytes:
    """A FIT file from pre-encoded message records (see ``message``), led by a file_id."""
    body = message(0, "file_id", [(0, "enum", 4), (4, "u32", ts(start))])
    return _frame(body + b"".join(records))
