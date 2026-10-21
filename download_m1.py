"""
Objective:
    Download historical one-minute OHLCV candles from Dukascopy and save
    them as a CSV file for backtesting and market analysis.

Configuration:
    DAYS_TO_DOWNLOAD controls the number of completed UTC calendar days.
    SYMBOL selects the instrument.
    The timeframe is always one minute (M1).

Supported SYMBOL examples:
    "GOLDUSD"  - Gold/USD; resolved to Dukascopy's XAUUSD instrument (default).
    "XAUUSD"   - Gold/USD, using the provider's instrument symbol.
    "EURUSD"   - Euro/USD.
    "SP500USD" - S&P 500 CFD; resolved to Dukascopy's US500 instrument.
    "US500"    - S&P 500 CFD, using the provider's instrument symbol.
    "TSLAUSD"  - Tesla US stock CFD; resolved to Dukascopy's TSLA instrument.
    "TSLA"     - Tesla, using the provider's instrument symbol.
    "BTCUSD"   - Bitcoin/USD, if available in the installed instrument catalog.

Output:
    data/<SYMBOL>_M1_<DAYS>D.csv

    Columns: Date, Open, High, Low, Close, Volume

Notes:
    Timestamps are UTC.
    Dukascopy volume should not automatically be interpreted as exchange-traded
    volume. CFD volume may represent tick activity.
    The downloaded prices are from Dukascopy's BID feed.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import pandas as pd

try:
    import dukascopy_python as duka
    from dukascopy_python import instruments
except ImportError as exc:
    raise SystemExit(
        "Missing dependencies. Activate your virtual environment and run:\n"
        "python -m pip install dukascopy-python pandas"
    ) from exc


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DAYS_TO_DOWNLOAD = 365

# Change this value to select another instrument.
SYMBOL = "GOLDUSD"

# Always use one-minute candles.
TIMEFRAME = "m1"

MAX_RETRIES = 5
INITIAL_RETRY_DELAY_SECONDS = 2.0
PAUSE_BETWEEN_MONTHS_SECONDS = 1.0

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------------------
# Instrument resolution
# ---------------------------------------------------------------------------

SYMBOL_ALIASES = {
    "GOLDUSD": "XAUUSD",
    "SP500USD": "US500",
    "TSLAUSD": "TSLA",
}

EXPLICIT_INSTRUMENT_CONSTANTS = {
    "XAUUSD": "INSTRUMENT_FX_METALS_XAU_USD",
    "US500": "INSTRUMENT_IDX_AMERICA_E_SANDP_500",
}


def resolve_instrument(requested_symbol: str) -> tuple[str, str]:
    """Resolve a user-friendly symbol to a Dukascopy instrument."""
    requested = requested_symbol.strip().upper()
    symbol = SYMBOL_ALIASES.get(requested, requested)

    constant_name = EXPLICIT_INSTRUMENT_CONSTANTS.get(symbol)

    if constant_name:
        instrument = getattr(instruments, constant_name, None)

        if instrument is None:
            raise ValueError(
                f"Instrument constant {constant_name} is not available "
                "in the installed dukascopy-python package."
            )

        return symbol, instrument

    stock_match = None

    for name, value in vars(instruments).items():
        if not name.startswith("INSTRUMENT_"):
            continue

        if not isinstance(value, str):
            continue

        normalized_value = value.replace("/", "").upper()

        if normalized_value == symbol:
            return symbol, value

        # Dukascopy commonly represents US stock CFDs as TSLA.US/USD.
        if value.upper() == f"{symbol}.US/USD":
            stock_match = value

    if stock_match is not None:
        return symbol, stock_match

    raise ValueError(
        f"Could not resolve symbol {requested!r} in the installed "
        "Dukascopy instrument catalog. Try GOLDUSD, EURUSD, SP500USD, "
        "TSLAUSD, or BTCUSD. You can also inspect the instrument constants "
        "in the installed dukascopy_python.instruments module."
    )


def resolve_interval():
    """Find the library constant corresponding to one-minute candles."""
    candidates = (
        "INTERVAL_MIN_1",
        "INTERVAL_MINUTE_1",
        "INTERVAL_M1",
    )

    for name in candidates:
        value = getattr(duka, name, None)

        if value is not None:
            return value

    raise RuntimeError(
        "The installed dukascopy-python package does not expose "
        "a recognized one-minute interval constant."
    )


def resolve_bid_side():
    """Find the library constant for BID prices."""
    candidates = ("OFFER_SIDE_BID", "PRICE_TYPE_BID", "BID")

    for name in candidates:
        value = getattr(duka, name, None)

        if value is not None:
            return value

    raise RuntimeError(
        "The installed dukascopy-python package does not expose "
        "a recognized BID price-side constant."
    )


# ---------------------------------------------------------------------------
# Date and download helpers
# ---------------------------------------------------------------------------

def get_date_window() -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the requested window as naive UTC timestamps."""
    if DAYS_TO_DOWNLOAD <= 0:
        raise ValueError("DAYS_TO_DOWNLOAD must be greater than zero.")

    # Use midnight UTC so the download contains complete days only.
    end_utc = pd.Timestamp.now(tz="UTC").normalize()
    start_utc = end_utc - pd.Timedelta(days=DAYS_TO_DOWNLOAD)

    # The Dukascopy Python API examples use naive datetime values.
    # These timestamps represent UTC.
    return start_utc.tz_localize(None), end_utc.tz_localize(None)


def month_chunks(
    start: pd.Timestamp,
    end: pd.Timestamp,
):
    """Yield non-overlapping chunks aligned to calendar-month boundaries."""
    current = pd.Timestamp(year=start.year, month=start.month, day=1)

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


def fetch_chunk(
    instrument: str,
    interval,
    bid_side,
    chunk_start: pd.Timestamp,
    chunk_end: pd.Timestamp,
    label: str,
) -> pd.DataFrame:
    """Fetch one chunk, retrying temporary failures with exponential backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = duka.fetch(
                instrument,
                interval,
                bid_side,
                chunk_start.to_pydatetime(),
                chunk_end.to_pydatetime(),
            )

            return normalize_frame(df)

        except Exception as exc:
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"{label} failed after {MAX_RETRIES} attempts: {exc}"
                ) from exc

            delay = min(
                INITIAL_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)),
                60.0,
            )
            delay += random.uniform(0, 1)

            print(
                f"  {label}: attempt {attempt} failed: {exc}\n"
                f"  Retrying in {delay:.1f} seconds..."
            )
            time.sleep(delay)

    return pd.DataFrame()


def download_symbol(
    provider_symbol: str,
    instrument: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Download monthly chunks and reuse cached results when available."""
    interval = resolve_interval()
    bid_side = resolve_bid_side()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    frames = []

    for chunk_start, chunk_end in month_chunks(start, end):
        cache_name = (
            f"{provider_symbol}_{TIMEFRAME}_"
            f"{chunk_start:%Y%m%d}_{chunk_end:%Y%m%d}.pkl"
        )
        cache_path = CACHE_DIR / cache_name
        label = f"{provider_symbol} {chunk_start:%Y-%m}"

        if cache_path.is_file():
            try:
                df = normalize_frame(pd.read_pickle(cache_path))
                print(f"  {label}: loaded {len(df):,} cached candles")
            except Exception as exc:
                print(f"  {label}: cache could not be read ({exc}); refetching")
                cache_path.unlink(missing_ok=True)
                df = fetch_chunk(
                    instrument, interval, bid_side,
                    chunk_start, chunk_end, label,
                )
        else:
            df = fetch_chunk(
                instrument, interval, bid_side,
                chunk_start, chunk_end, label,
            )

        if not cache_path.exists():
            temporary_cache = cache_path.with_suffix(".tmp.pkl")
            df.to_pickle(temporary_cache)
            temporary_cache.replace(cache_path)

        print(f"  {label}: {len(df):,} candles")
        frames.append(df)

        time.sleep(PAUSE_BETWEEN_MONTHS_SECONDS)

    nonempty_frames = [frame for frame in frames if not frame.empty]

    if not nonempty_frames:
        raise RuntimeError(
            "The provider returned no candles for the requested period."
        )

    result = pd.concat(nonempty_frames)
    result = result[~result.index.duplicated(keep="last")].sort_index()

    start_utc = start.tz_localize("UTC")
    end_utc = end.tz_localize("UTC")

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


def write_csv(
    requested_symbol: str,
    df: pd.DataFrame,
) -> Path:
    """Save normalized one-minute OHLCV candles as a CSV file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    output_path = DATA_DIR / (
        f"{requested_symbol}_M1_{DAYS_TO_DOWNLOAD}D.csv"
    )

    output = df.copy()
    output.columns = ["Open", "High", "Low", "Close", "Volume"]
    output.index.name = "Date"

    output.to_csv(
        output_path,
        date_format="%Y-%m-%dT%H:%M:%S%z",
    )

    return output_path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    requested_symbol = SYMBOL.strip().upper()

    start, end = get_date_window()
    provider_symbol, instrument = resolve_instrument(requested_symbol)

    print("=" * 60)
    print("One-Minute OHLCV Historical Data Downloader")
    print("=" * 60)
    print(f"Requested symbol: {requested_symbol}")
    print(f"Provider symbol:  {provider_symbol}")
    print(f"Instrument:       {instrument}")
    print("Timeframe:        M1 (one minute)")
    print("Price side:       BID")
    print("Timezone:         UTC")
    print(f"Start:            {start:%Y-%m-%d}")
    print(f"End (exclusive):  {end:%Y-%m-%d}")
    print()

    df = download_symbol(
        provider_symbol,
        instrument,
        start,
        end,
    )

    output_path = write_csv(requested_symbol, df)

    print()
    print("Download completed.")
    print(f"Candles: {len(df):,}")
    print(f"First candle: {df.index.min()}")
    print(f"Last candle:  {df.index.max()}")
    print(f"CSV file:     {output_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
