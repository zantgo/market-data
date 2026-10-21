"""
Objective:
    Persist OHLCV candles as CSV files and read them back.

    Every CSV holds a ``Date`` column with UTC timestamps followed by the
    Open, High, Low, Close and Volume columns.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import CSV_COLUMN_NAMES, REQUIRED_COLUMNS


def format_timestamp(timestamp: pd.Timestamp) -> str:
    """Return an ISO 8601 timestamp with an explicit UTC offset."""
    stamp = pd.Timestamp(timestamp)

    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")

    text = stamp.strftime("%Y-%m-%dT%H:%M:%S%z")

    return f"{text[:-2]}:{text[-2:]}"


def write_csv(df: pd.DataFrame, path: Path) -> Path:
    """Save OHLCV candles as a CSV file and return the written path."""
    path.parent.mkdir(parents=True, exist_ok=True)

    output = df.copy()
    output.columns = CSV_COLUMN_NAMES
    output.index = pd.DatetimeIndex(
        [format_timestamp(stamp) for stamp in output.index],
        name="Date",
    )

    output.to_csv(path)

    return path


def load_csv(path: Path) -> pd.DataFrame:
    """Load and validate OHLCV candles from a CSV file."""
    if not path.is_file():
        raise FileNotFoundError(f"Input CSV was not found: {path}")

    df = pd.read_csv(path)
    df.columns = [str(column).strip().lower() for column in df.columns]

    if "date" not in df.columns:
        raise ValueError("The CSV must contain a Date column.")

    missing_columns = [
        column for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"The CSV is missing required columns: {missing_columns}"
        )

    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")

    for column in REQUIRED_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    # Invalid prices cannot form a valid candlestick.
    df = df.dropna(subset=["date", "open", "high", "low", "close"])

    # Preserve candles even if the provider does not supply volume for a row.
    df["volume"] = df["volume"].fillna(0).clip(lower=0)

    df = df.set_index("date").sort_index()
    df.index = df.index.tz_convert("UTC").tz_localize(None)
    df.index.name = "Date"

    df = df.loc[~df.index.duplicated(keep="last")]

    if df.empty:
        raise ValueError("The CSV contains no valid OHLCV candles.")

    return df[
        ["open", "high", "low", "close", "volume"]
    ]
