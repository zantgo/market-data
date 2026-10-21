"""
Objective:
    Inspect downloaded candles before they are stored.

    Strategy research needs a dataset that can be trusted, but it also needs
    the data exactly as the provider published it. The checks in this module
    therefore never reshape the dataset: every candle the provider sent is
    kept, including flat candles, candles without volume and the gaps between
    them. The only rows that are ever dropped are duplicates of a timestamp
    and rows whose prices cannot be parsed at all.

    Everything that looks unusual is counted and reported, so it can be
    judged before it reaches a backtest.

Public API:
    QualityReport - summary of the checks performed on a dataset.
    validate_candles() - inspect a dataset and return it with its report.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import REQUIRED_COLUMNS
from .storage import format_timestamp
from .timeframes import Timeframe


@dataclass(frozen=True)
class Gap:
    """A period without candles inside the downloaded series."""

    start: pd.Timestamp
    end: pd.Timestamp
    missing: int

    def describe(self) -> str:
        """Return a one line description of the gap."""
        return (
            f"{self.start:%Y-%m-%d %H:%M} to {self.end:%Y-%m-%d %H:%M} "
            f"({self.missing} candles)"
        )


@dataclass(frozen=True)
class QualityReport:
    """Summary of the checks performed on a dataset."""

    rows: int
    first: pd.Timestamp | None
    last: pd.Timestamp | None
    duplicates_removed: int = 0
    unparseable_removed: int = 0
    non_positive_prices: int = 0
    inconsistent_candles: int = 0
    negative_volume: int = 0
    missing_candles: int = 0
    gaps: tuple[Gap, ...] = ()
    flat_candles: int = 0
    zero_volume_candles: int = 0

    @property
    def is_clean(self) -> bool:
        """Return ``True`` when the dataset holds no anomaly at all."""
        return not any(
            (
                self.duplicates_removed,
                self.unparseable_removed,
                self.non_positive_prices,
                self.inconsistent_candles,
                self.negative_volume,
            )
        )

    def summary_lines(self) -> list[str]:
        """Return the report as a list of printable lines."""
        if self.rows == 0:
            return ["No candles in the dataset."]

        lines = [
            f"Candles:       {self.rows:,}",
            f"First candle:  {format_timestamp(self.first)}",
            f"Last candle:   {format_timestamp(self.last)}",
        ]

        if self.duplicates_removed:
            lines.append(
                f"Removed {self.duplicates_removed} duplicate timestamps "
                "(the last one was kept)"
            )

        if self.unparseable_removed:
            lines.append(
                f"Removed {self.unparseable_removed} candles with unparseable prices"
            )

        if self.non_positive_prices:
            lines.append(
                f"Kept {self.non_positive_prices} candles with a non positive price"
            )

        if self.inconsistent_candles:
            lines.append(
                f"Kept {self.inconsistent_candles} candles whose high or low "
                "does not contain the open and the close"
            )

        if self.negative_volume:
            lines.append(f"Kept {self.negative_volume} candles with a negative volume")

        if self.flat_candles:
            lines.append(
                f"Flat candles without movement (kept): {self.flat_candles:,}"
            )

        if self.zero_volume_candles:
            lines.append(f"Candles without volume (kept): {self.zero_volume_candles:,}")

        if self.missing_candles:
            lines.append(f"Candles missing inside the series: {self.missing_candles:,}")

        return lines


def _count_gaps(
    index: pd.DatetimeIndex,
    timeframe: Timeframe,
) -> tuple[int, tuple[Gap, ...]]:
    """Count the candles that are missing between two consecutive candles."""
    minutes = timeframe.minutes

    if minutes is None or len(index) < 2:
        return 0, ()

    expected = pd.Timedelta(minutes=minutes)
    gaps = []

    for position in range(1, len(index)):
        delta = index[position] - index[position - 1]
        missing = int(delta / expected) - 1

        if missing > 0:
            gaps.append(
                Gap(
                    start=index[position - 1],
                    end=index[position],
                    missing=missing,
                )
            )

    total = sum(gap.missing for gap in gaps)
    largest = tuple(sorted(gaps, key=lambda gap: gap.missing, reverse=True)[:5])

    return total, largest


def validate_candles(
    df: pd.DataFrame,
    timeframe: Timeframe,
) -> tuple[pd.DataFrame, QualityReport]:
    """Inspect a dataset and return it unchanged together with its report."""
    if df is None or df.empty:
        return (
            pd.DataFrame(columns=REQUIRED_COLUMNS),
            QualityReport(rows=0, first=None, last=None),
        )

    frame = df.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]

    if "timestamp" in frame.columns:
        frame = frame.set_index("timestamp")

    frame.index = pd.to_datetime(frame.index, utc=True)
    frame.index.name = "Date"

    for column in REQUIRED_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    # A time series cannot hold the same timestamp twice, the last row wins.
    duplicates = int(frame.index.duplicated().sum())
    frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index()

    # Only rows whose prices cannot be read at all are removed.
    unparseable = int(frame[REQUIRED_COLUMNS].isna().any(axis=1).sum())
    frame = frame.dropna(subset=REQUIRED_COLUMNS)

    non_positive = int(
        (frame[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()
    )

    inconsistent = int(
        (
            (frame["high"] < frame[["open", "close"]].max(axis=1)) |
            (frame["low"] > frame[["open", "close"]].min(axis=1)) |
            (frame["high"] < frame["low"])
        ).sum()
    )

    negative_volume = int((frame["volume"] < 0).sum())
    flat = int((frame["high"] == frame["low"]).sum())
    no_volume = int((frame["volume"] == 0).sum())

    missing, gaps = _count_gaps(frame.index, timeframe)

    report = QualityReport(
        rows=len(frame),
        first=frame.index[0] if len(frame) else None,
        last=frame.index[-1] if len(frame) else None,
        duplicates_removed=duplicates,
        unparseable_removed=unparseable,
        non_positive_prices=non_positive,
        inconsistent_candles=inconsistent,
        negative_volume=negative_volume,
        missing_candles=missing,
        gaps=gaps,
        flat_candles=flat,
        zero_volume_candles=no_volume,
    )

    return frame[REQUIRED_COLUMNS], report
