"""
Objective:
    Download historical OHLCV candles from Dukascopy.

    The downloader reuses a monthly chunk strategy so that interrupted
    downloads can be resumed from the local pickle cache. Every chunk is
    stored under ``cache/`` and reused on the next run.

Public API:
    download_candles() - fetch a date range for a native interval.
    month_chunks()     - split a date range into calendar month chunks.
"""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Callable

import pandas as pd

try:
    import dukascopy_python as duka
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit(
        "Missing dependencies. Activate your virtual environment and run:\n"
        "python -m pip install -r requirements.txt"
    ) from exc

from .config import (
    INITIAL_RETRY_DELAY_SECONDS,
    MAX_EMPTY_RETRIES,
    MAX_RETRIES,
    MAX_RETRY_DELAY_SECONDS,
    PAUSE_BETWEEN_CHUNKS_SECONDS,
    REQUIRED_COLUMNS,
)


ProgressCallback = Callable[[str], None]

logger = logging.getLogger("marketdata.downloader")


# ---------------------------------------------------------------------------
# Library constants
# ---------------------------------------------------------------------------

def resolve_bid_side() -> str:
    """Return the library constant describing BID prices."""
    for name in ("OFFER_SIDE_BID", "PRICE_TYPE_BID", "BID"):
        value = getattr(duka, name, None)

        if value is not None:
            return value

    raise RuntimeError(
        "The installed dukascopy-python package does not expose "
        "a recognized BID price-side constant."
    )


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def as_utc(value: pd.Timestamp) -> pd.Timestamp:
    """Return a timezone aware UTC timestamp."""
    timestamp = pd.Timestamp(value)

    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")

    return timestamp.tz_convert("UTC")


def month_chunks(
    start: pd.Timestamp,
    end: pd.Timestamp,
):
    """Yield non-overlapping chunks aligned to calendar month boundaries."""
    start = as_utc(start)
    end = as_utc(end)

    current = pd.Timestamp(
        year=start.year,
        month=start.month,
        day=1,
        tz="UTC",
    )

    while current < end:
        next_month = current + pd.DateOffset(months=1)

        yield max(current, start), min(next_month, end)

        current = next_month


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names and ensure the index contains UTC timestamps."""
    if df is None or df.empty:
        return pd.DataFrame()

    if "timestamp" in df.columns:
        df = df.set_index("timestamp")

    df = df.copy()
    df.columns = [str(column).lower() for column in df.columns]
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "Date"

    return df


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def fetch_chunk(
    instrument: str,
    interval: str,
    bid_side: str,
    chunk_start: pd.Timestamp,
    chunk_end: pd.Timestamp,
    label: str,
) -> pd.DataFrame:
    """Fetch one chunk, retrying temporary failures with exponential backoff."""
    empty_attempts = 0

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = duka.fetch(
                instrument,
                interval,
                bid_side,
                chunk_start.to_pydatetime(),
                chunk_end.to_pydatetime(),
            )

            frame = normalize_frame(df)

        except Exception as exc:
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"{label} failed after {MAX_RETRIES} attempts: {exc}"
                ) from exc

            delay = min(
                INITIAL_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)),
                MAX_RETRY_DELAY_SECONDS,
            )
            delay += random.uniform(0, 1)

            logger.warning(
                "%s: attempt %s failed: %s. Retrying in %.1f seconds",
                label,
                attempt,
                exc,
                delay,
            )
            time.sleep(delay)
            continue

        if not frame.empty:
            return frame

        # The provider sometimes answers with an empty page. That is worth a
        # retry, but a period without candles stays empty.
        empty_attempts += 1

        if empty_attempts >= MAX_EMPTY_RETRIES or attempt == MAX_RETRIES:
            logger.warning("%s: the provider returned no candles", label)
            return frame

        logger.warning("%s: empty response, retrying", label)
        time.sleep(INITIAL_RETRY_DELAY_SECONDS)

    return pd.DataFrame()


def _cache_path(
    cache_dir: Path,
    symbol_slug: str,
    native_code: str,
    chunk_start: pd.Timestamp,
    chunk_end: pd.Timestamp,
) -> Path:
    """Return the cache file used for a chunk."""
    name = (
        f"{symbol_slug}_{native_code}_"
        f"{chunk_start:%Y%m%d}_{chunk_end:%Y%m%d}.pkl"
    )

    return cache_dir / name


def _read_cache(
    cache_path: Path,
    chunk_start: pd.Timestamp,
    chunk_end: pd.Timestamp,
) -> pd.DataFrame:
    """Read a cached chunk and make sure it covers the requested range.

    The chunk of the running month grows over time. A cached chunk that was
    fetched with an older end is stale and has to be downloaded again,
    otherwise the newest candles would silently be missing.
    """
    frame = normalize_frame(pd.read_pickle(cache_path))

    if frame.empty:
        raise ValueError("the cached chunk is empty")

    covered_start = frame.attrs.get("covered_start")
    covered_end = frame.attrs.get("covered_end")

    if covered_start is None or covered_end is None:
        # Cached by an older version, the range cannot be verified.
        raise ValueError("the cached chunk has no range information")

    if pd.Timestamp(covered_start) > chunk_start:
        raise ValueError("the cached chunk starts too late")

    if pd.Timestamp(covered_end) < chunk_end:
        raise ValueError("the cached chunk does not reach the end of the range")

    return frame


def download_candles(
    instrument: str,
    provider_interval: str,
    symbol_slug: str,
    native_code: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_dir: Path,
    on_progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    """Download a date range and return normalized OHLCV candles."""
    def report(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    bid_side = resolve_bid_side()
    cache_dir.mkdir(parents=True, exist_ok=True)
    start = as_utc(start)
    end = as_utc(end)
    frames = []

    for chunk_start, chunk_end in month_chunks(start, end):
        cache_path = _cache_path(
            cache_dir, symbol_slug, native_code, chunk_start, chunk_end
        )
        label = f"{symbol_slug} {chunk_start:%Y-%m}"

        if cache_path.is_file():
            try:
                df = _read_cache(cache_path, chunk_start, chunk_end)

                report(f"  {label}: {len(df):,} candles (cache)")
            except Exception as exc:
                report(f"  {label}: cache unusable ({exc}); refetching")
                cache_path.unlink(missing_ok=True)
                df = fetch_chunk(
                    instrument,
                    provider_interval,
                    bid_side,
                    chunk_start,
                    chunk_end,
                    label,
                )
        else:
            df = fetch_chunk(
                instrument,
                provider_interval,
                bid_side,
                chunk_start,
                chunk_end,
                label,
            )

        # Empty chunks are not cached, so a temporary empty answer never
        # poisons a later run.
        if not cache_path.exists() and not df.empty:
            df.attrs["covered_start"] = chunk_start.isoformat()
            df.attrs["covered_end"] = chunk_end.isoformat()

            temporary_cache = cache_path.with_suffix(".tmp.pkl")
            df.to_pickle(temporary_cache)
            temporary_cache.replace(cache_path)

        report(f"  {label}: {len(df):,} candles")
        frames.append(df)

        time.sleep(PAUSE_BETWEEN_CHUNKS_SECONDS)

    nonempty_frames = [frame for frame in frames if not frame.empty]

    if not nonempty_frames:
        raise RuntimeError(
            "The provider returned no candles for the requested period."
        )

    result = pd.concat(nonempty_frames)
    result = result[~result.index.duplicated(keep="last")].sort_index()

    start_utc = as_utc(start)
    end_utc = as_utc(end)

    # Enforce the exact requested interval and exclude the end timestamp.
    result = result[
        (result.index >= start_utc) &
        (result.index < end_utc)
    ]

    missing_columns = [
        column for column in REQUIRED_COLUMNS
        if column not in result.columns
    ]

    if missing_columns:
        raise RuntimeError(
            f"Missing OHLCV columns: {missing_columns}. "
            f"Received: {list(result.columns)}"
        )

    return result[REQUIRED_COLUMNS]
