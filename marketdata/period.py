"""
Objective:
    Represent the length of the historical window that has to be downloaded.

    A period is expressed in days, months and years so that the same value
    can be provided on the command line or typed at the interactive prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd


PERIOD_PATTERN = re.compile(r"(?P<amount>\d+)\s*(?P<unit>[a-z]*)", re.IGNORECASE)

UNIT_ALIASES = {
    "": "d",
    "d": "d",
    "day": "d",
    "days": "d",
    "m": "m",
    "mo": "m",
    "month": "m",
    "months": "m",
    "y": "y",
    "yr": "y",
    "year": "y",
    "years": "y",
}


@dataclass(frozen=True)
class Period:
    """A history window expressed in days, months and years."""

    days: int = 0
    months: int = 0
    years: int = 0

    @property
    def is_empty(self) -> bool:
        """Return ``True`` when the period covers no time at all."""
        return not (self.days or self.months or self.years)

    @property
    def file_label(self) -> str:
        """Return the label used inside file names, e.g. ``365D`` or ``1Y_6M``."""
        parts = []

        if self.years:
            parts.append(f"{self.years}Y")

        if self.months:
            parts.append(f"{self.months}M")

        if self.days:
            parts.append(f"{self.days}D")

        return "_".join(parts)

    def describe(self) -> str:
        """Return a human readable description of the period."""
        parts = []

        if self.years:
            parts.append(f"{self.years} year" + ("" if self.years == 1 else "s"))

        if self.months:
            parts.append(
                f"{self.months} month" + ("" if self.months == 1 else "s")
            )

        if self.days:
            parts.append(f"{self.days} day" + ("" if self.days == 1 else "s"))

        return ", ".join(parts) if parts else "0 days"

    def start_from(self, end: pd.Timestamp) -> pd.Timestamp:
        """Return the start timestamp that ends at ``end``."""
        start = end

        if self.years:
            start = start - pd.DateOffset(years=self.years)

        if self.months:
            start = start - pd.DateOffset(months=self.months)

        if self.days:
            start = start - pd.Timedelta(days=self.days)

        return start

    def total_days(self, end: pd.Timestamp) -> int:
        """Return the number of days covered by the period."""
        return int((end - self.start_from(end)).days)


def parse_period(text: str) -> Period:
    """Parse a period such as ``365``, ``30d``, ``6m`` or ``2y``."""
    cleaned = str(text).strip().lower()

    if not cleaned:
        raise ValueError("The period cannot be empty.")

    matches = PERIOD_PATTERN.findall(cleaned)

    if not matches:
        raise ValueError(
            f"Could not understand the period {text!r}. "
            "Use a number with an optional unit, e.g. 365, 30d, 6m or 2y."
        )

    days = months = years = 0

    for amount, unit in matches:
        amount = int(amount)
        unit_code = UNIT_ALIASES.get(unit)

        if unit_code is None:
            raise ValueError(
                f"Unknown period unit {unit!r}. Use d (days), m (months) or y (years)."
            )

        if unit_code == "d":
            days += amount
        elif unit_code == "m":
            months += amount
        else:
            years += amount

    period = Period(days=days, months=months, years=years)

    if period.is_empty:
        raise ValueError("The period must be greater than zero.")

    return period
