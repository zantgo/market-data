"""
Objective:
    Plot historical one-minute OHLCV candles from a downloaded market-data CSV.
    Display candlesticks, volume bars, and moving averages, then save the chart
    as a PNG image.

Configuration:
    SYMBOL selects the market.
    DAYS_TO_DOWNLOAD selects the matching CSV file.
    CANDLE_COUNT controls how many recent one-minute candles are displayed.

Supported SYMBOL examples:
    "GOLDUSD"  - Gold/USD (default).
    "EURUSD"   - Euro/USD.
    "SP500USD" - S&P 500 CFD.
    "TSLAUSD"  - Tesla CFD.
    "BTCUSD"   - Bitcoin/USD.

Input:
    data/<SYMBOL>_M1_<DAYS_TO_DOWNLOAD>D.csv

Output:
    data/<SYMBOL>_M1_<CANDLE_COUNT>_candles.png
"""

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd


# Configuration
SYMBOL = "GOLDUSD"
DAYS_TO_DOWNLOAD = 365
CANDLE_COUNT = 1000

# Moving average periods, measured in candles.
MOVING_AVERAGES = (20, 50)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

CSV_PATH = DATA_DIR / f"{SYMBOL}_M1_{DAYS_TO_DOWNLOAD}D.csv"
OUTPUT_PATH = DATA_DIR / f"{SYMBOL}_M1_{CANDLE_COUNT}_candles.png"

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def load_ohlcv(csv_path: Path) -> pd.DataFrame:
    """Load and validate OHLCV data from a CSV file."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"Input CSV was not found: {csv_path}")

    df = pd.read_csv(csv_path)
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

    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    # Invalid prices cannot form a valid candlestick.
    df = df.dropna(subset=["date", "open", "high", "low", "close"])

    # Preserve candles even if the provider does not supply volume for a row.
    df["volume"] = df["volume"].fillna(0).clip(lower=0)

    # mplfinance works with a DatetimeIndex; use naive UTC timestamps.
    df = df.set_index("date").sort_index()
    df.index = df.index.tz_convert("UTC").tz_localize(None)
    df.index.name = "Date"

    # Remove duplicate timestamps, keeping the last occurrence.
    df = df.loc[~df.index.duplicated(keep="last")]

    if df.empty:
        raise ValueError("The CSV contains no valid OHLCV candles.")

    # Use the column names expected by mplfinance.
    df = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )

    return df[["Open", "High", "Low", "Close", "Volume"]]


def plot_candles(df: pd.DataFrame) -> None:
    """Plot recent candlesticks with volume and moving averages."""
    if CANDLE_COUNT <= 0:
        raise ValueError("CANDLE_COUNT must be greater than zero.")

    chart_data = df.tail(CANDLE_COUNT)

    start_time = chart_data.index[0].strftime("%Y-%m-%d %H:%M")
    end_time = chart_data.index[-1].strftime("%Y-%m-%d %H:%M")

    title = (
        f"{SYMBOL} | 1-Minute OHLCV Candles\n"
        f"{start_time} to {end_time} UTC"
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    figure, _ = mpf.plot(
        chart_data,
        type="candle",
        style="yahoo",
        volume=True,
        mav=MOVING_AVERAGES,
        title=title,
        ylabel="Price",
        ylabel_lower="Volume",
        datetime_format="%m-%d %H:%M",
        xrotation=15,
        figsize=(16, 9),
        panel_ratios=(3, 1),
        tight_layout=True,
        returnfig=True,
        warn_too_much_data=max(CANDLE_COUNT, 5000),
    )

    figure.savefig(
        OUTPUT_PATH,
        dpi=150,
        bbox_inches="tight",
    )

    print(f"Symbol:         {SYMBOL}")
    print("Timeframe:      1 minute")
    print(f"Candles plotted: {len(chart_data):,}")
    print(f"First candle:   {start_time} UTC")
    print(f"Last candle:    {end_time} UTC")
    print(f"Chart saved to: {OUTPUT_PATH}")

    plt.show()
    plt.close(figure)


def main() -> None:
    try:
        df = load_ohlcv(CSV_PATH)
        plot_candles(df)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
