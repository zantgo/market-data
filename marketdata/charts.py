"""
Objective:
    Render a candlestick chart with a volume panel and moving averages.

    The chart is built with mplfinance and stored as a PNG image so it can be
    shared without a running Python session.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib

if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402

from .config import CHART_DPI, CHART_FIGSIZE, DEFAULT_MOVING_AVERAGES  # noqa: E402


def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a frame with the column names and index that mplfinance expects."""
    frame = df.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame.index = frame.index.tz_convert("UTC").tz_localize(None)
    frame.index.name = "Date"

    frame = frame.loc[~frame.index.duplicated(keep="last")]
    frame["volume"] = frame["volume"].fillna(0).clip(lower=0)

    return frame.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )[["Open", "High", "Low", "Close", "Volume"]]


def render_candlestick_chart(
    df: pd.DataFrame,
    output_path: Path,
    title: str,
    candle_count: int = 1000,
    moving_averages: tuple[int, ...] = DEFAULT_MOVING_AVERAGES,
) -> Path:
    """Render the most recent candles into a PNG file."""
    if candle_count <= 0:
        raise ValueError("The chart candle count must be greater than zero.")

    if df is None or df.empty:
        raise ValueError("There is no data to plot.")

    chart_data = prepare_frame(df).tail(candle_count)

    if chart_data.empty:
        raise ValueError("There is no data to plot.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    figure, _ = mpf.plot(
        chart_data,
        type="candle",
        style="yahoo",
        volume=True,
        mav=list(moving_averages) or None,
        title=title,
        ylabel="Price",
        ylabel_lower="Volume",
        datetime_format="%m-%d %H:%M",
        xrotation=15,
        figsize=CHART_FIGSIZE,
        panel_ratios=(3, 1),
        tight_layout=True,
        returnfig=True,
        warn_too_much_data=max(candle_count, 5000),
    )

    figure.savefig(output_path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(figure)

    return output_path


def show_chart(output_path: Path) -> bool:
    """Open the rendered chart in the default image viewer."""
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return False

    try:
        import subprocess

        if sys.platform.startswith("darwin"):
            command = ["open", str(output_path)]
        elif os.name == "nt":
            command = ["start", str(output_path)]
        else:
            command = ["xdg-open", str(output_path)]

        subprocess.Popen(command)
    except Exception:
        return False

    return True
