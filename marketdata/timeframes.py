"""
Objective:
    Discover the candle intervals supported by the installed Dukascopy library.

    The intervals are read dynamically from the ``dukascopy_python`` package,
    so the program always offers exactly what the provider publishes. No
    candle is ever aggregated or synthesised: every timeframe maps onto a
    single native interval that is downloaded as published.

Public API:
    NativeInterval - a candle interval published by Dukascopy.
    Timeframe      - a user facing timeframe backed by a native interval.
    load_timeframes() - every timeframe supported by the CLI.
    resolve_timeframe() - resolve a user query into a timeframe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

import dukascopy_python as duka


# ---------------------------------------------------------------------------
# Native intervals
# ---------------------------------------------------------------------------

UNIT_MINUTES = {
    duka.TIME_UNIT_SEC: 1 / 60,
    duka.TIME_UNIT_MIN: 1,
    duka.TIME_UNIT_HOUR: 60,
    duka.TIME_UNIT_DAY: 1440,
    duka.TIME_UNIT_WEEK: 10080,
}

UNIT_CODES = {
    duka.TIME_UNIT_SEC: "S",
    duka.TIME_UNIT_MIN: "M",
    duka.TIME_UNIT_HOUR: "H",
    duka.TIME_UNIT_DAY: "D",
    duka.TIME_UNIT_WEEK: "W",
    duka.TIME_UNIT_MONTH: "MO",
    duka.TIME_UNIT_TICK: "TICK",
}

INTERVAL_PATTERN = re.compile(r"^(?P<count>\d+)?(?P<unit>[A-Z]+)$")
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


@dataclass(frozen=True)
class NativeInterval:
    """A candle interval published directly by Dukascopy."""

    constant: str
    provider_value: str
    unit: str
    count: int
    minutes: float | None

    @property
    def code(self) -> str:
        """Return the short code used for file names, e.g. ``M1`` or ``H4``."""
        unit_code = UNIT_CODES.get(self.unit, self.unit)

        if self.unit == duka.TIME_UNIT_TICK:
            return "TICK"

        if self.minutes is None:
            return f"{unit_code}{self.count}"

        if self.minutes < 1:
            return f"S{int(round(self.minutes * 60))}"

        if self.minutes < 60:
            return f"M{int(self.minutes)}"

        if self.minutes < 1440:
            return f"H{int(self.minutes // 60)}"

        if self.minutes < 10080:
            return f"D{int(self.minutes // 1440)}"

        if self.minutes < 43200:
            return f"W{int(self.minutes // 10080)}"

        return f"MO{self.count}"

    @property
    def label(self) -> str:
        """Return a human readable label, e.g. ``1 hour``."""
        if self.unit == duka.TIME_UNIT_TICK:
            return "tick"

        if self.minutes is None:
            return f"{self.count} {self.unit.lower()}"

        if self.minutes < 60:
            return f"{int(self.minutes)} minute" + ("" if self.minutes == 1 else "s")

        if self.minutes < 1440:
            hours = int(self.minutes // 60)
            return f"{hours} hour" + ("" if hours == 1 else "s")

        if self.minutes < 10080:
            days = int(self.minutes // 1440)
            return f"{days} day" + ("" if days == 1 else "s")

        if self.minutes < 43200:
            weeks = int(self.minutes // 10080)
            return f"{weeks} week" + ("" if weeks == 1 else "s")

        return f"{self.count} month" + ("" if self.count == 1 else "s")


@lru_cache(maxsize=1)
def load_native_intervals() -> tuple[NativeInterval, ...]:
    """Return every interval exposed by the installed Dukascopy library."""
    intervals = []

    for name, value in vars(duka).items():
        if not name.startswith("INTERVAL_"):
            continue

        if not isinstance(value, str):
            continue

        match = INTERVAL_PATTERN.match(value)

        if match is None:
            continue

        unit = match.group("unit")
        count = int(match.group("count") or 1)
        unit_minutes = UNIT_MINUTES.get(unit)
        minutes = unit_minutes * count if unit_minutes is not None else None

        intervals.append(
            NativeInterval(
                constant=name,
                provider_value=value,
                unit=unit,
                count=count,
                minutes=minutes,
            )
        )

    intervals.sort(key=lambda item: (item.minutes is None, item.minutes or 0))

    return tuple(intervals)


# ---------------------------------------------------------------------------
# User facing timeframes
# ---------------------------------------------------------------------------

TIMEFRAME_ALIASES = {
    "min": "m",
    "mins": "m",
    "minute": "m",
    "minutes": "m",
    "h": "h",
    "hour": "h",
    "hours": "h",
    "d": "d",
    "day": "d",
    "days": "d",
    "daily": "d",
    "w": "w",
    "week": "w",
    "weeks": "w",
    "weekly": "w",
    "mo": "mo",
    "month": "mo",
    "months": "mo",
    "monthly": "mo",
}


@dataclass(frozen=True)
class Timeframe:
    """A user facing timeframe backed by a native Dukascopy interval."""

    code: str
    file_code: str
    native: NativeInterval

    @property
    def minutes(self) -> int | None:
        """Return the length of the candle in minutes, ``None`` for months."""
        if self.native.minutes is None:
            return None

        return int(self.native.minutes)

    @property
    def label(self) -> str:
        """Return a human readable label, e.g. ``1 hour``."""
        return self.native.label

    @property
    def source_note(self) -> str:
        """Return a note explaining how the candles are produced."""
        return f"native ({self.native.provider_value})"

    def floor(self, timestamp: pd.Timestamp) -> pd.Timestamp:
        """Return the start of the candle bucket that contains the timestamp.

        The grid is aligned to the UTC epoch, which is the alignment the
        provider uses for its own candles.
        """
        timestamp = pd.Timestamp(timestamp)

        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")

        if self.native.unit == duka.TIME_UNIT_MONTH:
            return timestamp.normalize().replace(day=1)

        if self.native.unit == duka.TIME_UNIT_WEEK:
            return timestamp.normalize() - pd.Timedelta(days=timestamp.weekday())

        minutes = self.minutes

        if minutes is None:
            return timestamp.normalize()

        if minutes >= 1440:
            return timestamp.normalize()

        elapsed = (timestamp - EPOCH).total_seconds()
        buckets = int(elapsed // (minutes * 60))

        return EPOCH + pd.Timedelta(minutes=minutes * buckets)


def _format_code(native: NativeInterval) -> str:
    """Return the short timeframe code used in prompts."""
    minutes = native.minutes

    if minutes is None:
        return "1mo" if native.count == 1 else f"{native.count}mo"

    if minutes < 60:
        return f"{int(minutes)}m"

    if minutes < 1440:
        return f"{int(minutes // 60)}h"

    if minutes < 10080:
        return f"{int(minutes // 1440)}d"

    return f"{int(minutes // 10080)}w"


def _format_file_code(native: NativeInterval) -> str:
    """Return the uppercase timeframe code used in file names."""
    return native.code


@lru_cache(maxsize=1)
def load_timeframes() -> tuple[Timeframe, ...]:
    """Return every timeframe the program can download natively."""
    timeframes = []

    for native in load_native_intervals():
        # Sub minute intervals are published as well, but they are not
        # practical for market analysis, so they stay out of the program.
        if native.minutes is None:
            if native.unit != duka.TIME_UNIT_MONTH:
                continue
        elif native.minutes < 1:
            continue

        timeframes.append(
            Timeframe(
                code=_format_code(native),
                file_code=_format_file_code(native),
                native=native,
            )
        )

    return tuple(timeframes)


def _normalize_query(query: str) -> str:
    """Normalize a timeframe query into a canonical code."""
    text = str(query).strip().lower().replace(" ", "")

    if text in TIMEFRAME_ALIASES:
        text = TIMEFRAME_ALIASES[text]

    match = re.fullmatch(r"(?:(\d+)([mhdw])|([mhdw])(\d+))", text)

    if match is None:
        return text

    if match.group(1) is not None:
        amount, unit = match.group(1), match.group(2)
    else:
        unit, amount = match.group(3), match.group(4)

    if unit == "m":
        return f"{amount}m"

    if unit == "h":
        return f"{amount}h"

    if unit == "d":
        return f"{amount}d"

    if unit == "w":
        return f"{amount}w"

    return f"{amount}mo"


def resolve_timeframe(query: str) -> Timeframe:
    """Resolve a free form query into a supported timeframe."""
    normalized = _normalize_query(query)

    for timeframe in load_timeframes():
        if timeframe.code == normalized:
            return timeframe

    for timeframe in load_timeframes():
        if timeframe.file_code.lower() == normalized:
            return timeframe

    supported = ", ".join(timeframe.code for timeframe in load_timeframes())

    raise LookupError(
        f"Unknown timeframe {query!r}. Supported timeframes: {supported}."
    )
