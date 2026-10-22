"""
Objective:
    Command line interface of the market data toolkit.

    The CLI asks for an instrument, a history window, a candle timeframe and
    whether a chart should be generated. Every question can be answered in
    advance with a command line argument so the tool can run unattended.

Public API:
    main() - entry point used by ``main.py``.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd

from . import charts
from .config import (
    CACHE_DIR,
    DATA_DIR,
    DEFAULT_CHART_CANDLES,
    DEFAULT_DAYS,
    DEFAULT_MOVING_AVERAGES,
    DEFAULT_TIMEFRAME,
)
from .downloader import download_candles
from .instruments import Instrument, load_catalogue, resolve_instrument
from .period import Period
from .prompts import (
    prompt_instrument,
    prompt_period,
    prompt_timeframe,
    prompt_yes_no,
)
from .quality import validate_candles
from .storage import write_csv
from .timeframes import Timeframe, load_timeframes, resolve_timeframe


EXAMPLES = """
Examples:
  python main.py
  python main.py --symbol gold --days 365 --timeframe 1h --chart
  python main.py --symbol EURUSD --months 6 --timeframe 15m --no-chart
  python main.py --symbol BTC --years 2 --timeframe 1d --chart --candles 500
  python main.py --symbol gold --start 2025-01-01 --end 2025-12-31 --timeframe 1m --chart
  python main.py --list-instruments
  python main.py --list-timeframes
"""

DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the command line interface."""
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description=(
            "Download OHLCV candles from Dukascopy and optionally render "
            "a candlestick chart with volume and moving averages."
        ),
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-s",
        "--symbol",
        help="Instrument to download, e.g. gold, EURUSD, XAU/USD, AAPL.",
    )
    parser.add_argument(
        "-d",
        "--days",
        type=int,
        help="Number of days of history to download.",
    )
    parser.add_argument(
        "-M",
        "--months",
        type=int,
        help="Number of months of history to download.",
    )
    parser.add_argument(
        "-Y",
        "--years",
        type=int,
        help="Number of years of history to download.",
    )
    parser.add_argument(
        "--start",
        help=(
            "First UTC date of an explicit window, e.g. 2025-01-01. "
            "Use together with --end instead of --days/--months/--years."
        ),
    )
    parser.add_argument(
        "--end",
        help=(
            "Last UTC date of an explicit window, e.g. 2025-12-31. "
            "A date without a time covers the whole day."
        ),
    )
    parser.add_argument(
        "-t",
        "--timeframe",
        help="Candle timeframe, e.g. 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w.",
    )
    parser.add_argument(
        "--chart",
        dest="chart",
        action="store_true",
        default=None,
        help="Render a candlestick chart.",
    )
    parser.add_argument(
        "--no-chart",
        dest="chart",
        action="store_false",
        help="Skip the chart.",
    )
    parser.add_argument(
        "--candles",
        type=int,
        default=DEFAULT_CHART_CANDLES,
        help=f"Number of candles to plot (default: {DEFAULT_CHART_CANDLES}).",
    )
    parser.add_argument(
        "--mas",
        default=",".join(str(value) for value in DEFAULT_MOVING_AVERAGES),
        help="Moving average periods separated by commas (default: 20,50).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help=f"Directory for CSV and PNG files (default: {DATA_DIR}).",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=CACHE_DIR,
        help=f"Directory for the download cache (default: {CACHE_DIR}).",
    )
    parser.add_argument(
        "--list-instruments",
        action="store_true",
        help="Print every instrument published by Dukascopy and exit.",
    )
    parser.add_argument(
        "--list-timeframes",
        action="store_true",
        help="Print every supported timeframe and exit.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Never ask questions; fail when a value is missing.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Open the rendered chart in the default image viewer.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only print the final result.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show the log output of the Dukascopy library.",
    )

    return parser


def parse_moving_averages(text: str) -> tuple[int, ...]:
    """Parse a comma separated list of moving average periods."""
    periods = []

    for part in str(text).split(","):
        part = part.strip()

        if not part:
            continue

        value = int(part)

        if value <= 0:
            raise ValueError("Moving average periods must be greater than zero.")

        periods.append(value)

    return tuple(periods)


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------

def print_instruments() -> None:
    """Print the full instrument catalogue."""
    catalogue = load_catalogue()

    print(f"Dukascopy instruments available in the installed library: {len(catalogue)}")
    print()

    for instrument in catalogue:
        print(f"{instrument.provider_symbol:<22} {instrument.describe()}")


def print_timeframes() -> None:
    """Print every supported timeframe."""
    timeframes = load_timeframes()

    print("Supported timeframes (all downloaded natively, never aggregated):")
    print()

    for timeframe in timeframes:
        print(
            f"  {timeframe.code:<4} {timeframe.label:<12}"
            f" source: {timeframe.source_note}"
        )


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

def _period_from_arguments(args: argparse.Namespace) -> Period | None:
    """Return the period built from the command line arguments."""
    values = (args.days, args.months, args.years)

    if all(value is None for value in values):
        return None

    for value in values:
        if value is not None and value < 0:
            raise ValueError("Period values cannot be negative.")

    if all(not value for value in values):
        raise ValueError("The period must be greater than zero.")

    return Period(
        days=args.days or 0,
        months=args.months or 0,
        years=args.years or 0,
    )


def _resolve_instrument(args: argparse.Namespace) -> Instrument:
    """Return the instrument selected by the user."""
    if args.symbol:
        return resolve_instrument(args.symbol)

    if args.non_interactive:
        raise ValueError(
            "No instrument given. Use --symbol, for example "
            "--symbol gold, or drop --non-interactive to pick one interactively."
        )

    return prompt_instrument()


def _resolve_period(args: argparse.Namespace) -> Period:
    """Return the history window selected by the user."""
    period = _period_from_arguments(args)

    if period is not None:
        return period

    if args.non_interactive:
        raise ValueError(
            "No period given. Use --days, --months or --years."
        )

    return prompt_period(Period(days=DEFAULT_DAYS))


def _resolve_timeframe(args: argparse.Namespace) -> Timeframe:
    """Return the candle timeframe selected by the user."""
    if args.timeframe:
        return resolve_timeframe(args.timeframe)

    if args.non_interactive:
        raise ValueError(
            "No timeframe given. Use --timeframe, for example --timeframe 1h."
        )

    return prompt_timeframe(DEFAULT_TIMEFRAME)


def _resolve_chart_flag(args: argparse.Namespace) -> bool:
    """Return whether a chart should be rendered."""
    if args.chart is not None:
        return args.chart

    if args.non_interactive:
        return False

    return prompt_yes_no("Generate a candlestick chart?")


def _parse_window_boundary(value: str, option: str) -> tuple[pd.Timestamp, bool]:
    """Parse a ``--start`` or ``--end`` value into a UTC timestamp."""
    text = str(value).strip()

    try:
        stamp = pd.Timestamp(text)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"Could not parse {option} value {value!r}. "
            "Use an ISO date such as 2025-01-01."
        ) from error

    if pd.isna(stamp):
        raise ValueError(
            f"Could not parse {option} value {value!r}. "
            "Use an ISO date such as 2025-01-01."
        )

    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")

    return stamp, bool(DATE_ONLY_PATTERN.fullmatch(text))


def _explicit_window(
    args: argparse.Namespace,
    timeframe: Timeframe,
) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    """Return an explicit start/end window and the label for file names."""
    if not args.start or not args.end:
        raise ValueError("Use --start and --end together.")

    if any(value is not None for value in (args.days, args.months, args.years)):
        raise ValueError(
            "--start/--end cannot be combined with --days, --months or --years."
        )

    start, _ = _parse_window_boundary(args.start, "--start")
    end, end_is_date = _parse_window_boundary(args.end, "--end")

    # A date without a time covers the whole day, so the window ends at the
    # midnight that follows it. The download end is always exclusive.
    if end_is_date:
        end += pd.Timedelta(days=1)

    start = timeframe.floor(start)
    end = timeframe.floor(end)

    if start >= end:
        raise ValueError("The end of the window must be after its start.")

    last_candle_day = end - pd.Timedelta(microseconds=1)
    label = f"{start:%Y-%m-%d}_{last_candle_day:%Y-%m-%d}"

    return start, end, label


def _last_closed_candle(timeframe: Timeframe) -> pd.Timestamp:
    """Return the start of the most recent closed candle.

    The download stops at a candle boundary, so every candle in the dataset
    is complete. Nothing is synthesised and no partial candle is stored.
    """
    return timeframe.floor(pd.Timestamp.now(tz="UTC"))


def run(args: argparse.Namespace) -> int:
    """Run the download and chart workflow."""
    instrument = _resolve_instrument(args)
    timeframe = _resolve_timeframe(args)
    chart_requested = _resolve_chart_flag(args)

    if args.start or args.end:
        start, end, file_label = _explicit_window(args, timeframe)
        period_description = (
            f"explicit window ({start:%Y-%m-%d} to "
            f"{(end - pd.Timedelta(microseconds=1)):%Y-%m-%d})"
        )
    else:
        period = _resolve_period(args)
        end = _last_closed_candle(timeframe)

        # The window starts on a candle boundary, so the first candle is the
        # one that contains the requested start. Without this the weekly and
        # monthly timeframes could end up without a single complete candle.
        start = timeframe.floor(period.start_from(end))

        if start >= end:
            raise ValueError("The period must be greater than zero.")

        file_label = period.file_label
        period_description = period.describe()

    moving_averages = parse_moving_averages(args.mas)

    if not args.quiet:
        print("=" * 60)
        print("Dukascopy market data")
        print("=" * 60)
        print(f"Instrument:      {instrument.describe()}")
        print(f"Category:        {instrument.category_label}")
        print(f"Timeframe:       {timeframe.code} ({timeframe.source_note})")
        print(f"Period:          {period_description}")
        print(f"Start:           {start:%Y-%m-%d %H:%M} UTC")
        print(f"End (exclusive): {end:%Y-%m-%d %H:%M} UTC")
        print("Price side:      BID")
        print("Timezone:        UTC")
        print()

    def report(message: str) -> None:
        if not args.quiet:
            print(message, flush=True)

    report("Downloading candles...")

    frame = download_candles(
        instrument=instrument.provider_symbol,
        provider_interval=timeframe.native.provider_value,
        symbol_slug=instrument.slug,
        native_code=timeframe.native.code.lower(),
        start=start,
        end=end,
        cache_dir=args.cache_dir,
        on_progress=report,
    )

    if frame.empty:
        raise RuntimeError("No candles were produced for the requested window.")

    frame, quality = validate_candles(frame, timeframe)

    if frame.empty:
        raise RuntimeError(
            "Every candle of the requested window was rejected by the "
            "quality checks."
        )

    csv_path = write_csv(
        frame,
        args.data_dir / f"{instrument.slug}_{timeframe.file_code}_{file_label}.csv",
    )

    chart_path = None

    if chart_requested:
        plotted = frame.tail(args.candles)

        chart_path = charts.render_candlestick_chart(
            frame,
            output_path=(
                args.data_dir
                / f"{instrument.slug}_{timeframe.file_code}_{args.candles}_candles.png"
            ),
            title=(
                f"{instrument.display_name} | {timeframe.code} candles "
                f"(last {len(plotted):,})\n"
                f"{plotted.index[0]:%Y-%m-%d %H:%M} to "
                f"{plotted.index[-1]:%Y-%m-%d %H:%M} UTC"
            ),
            candle_count=args.candles,
            moving_averages=moving_averages,
        )

    if args.quiet:
        print(csv_path)

    else:
        print()
        print("=" * 60)
        print("Done")
        print("=" * 60)
        for line in quality.summary_lines():
            print(line)

        print(f"CSV file:      {csv_path}")

        if chart_path is not None:
            print(f"Chart file:    {chart_path}")

        if quality.gaps:
            print()
            print("Largest gaps inside the series:")
            for gap in quality.gaps:
                print(f"  {gap.describe()}")
    if chart_path is not None and args.show:
        charts.show_chart(chart_path)

    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING,
        format="%(message)s",
    )

    # The Dukascopy library logs one line per request, which is noise for
    # the default output. It is re-enabled with the verbose flag.
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
        logging.disable(logging.NOTSET)
    else:
        logging.disable(logging.INFO)

    try:
        if args.list_instruments:
            print_instruments()
            return 0

        if args.list_timeframes:
            print_timeframes()
            return 0

        return run(args)

    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130

    except EOFError:
        print(
            "\nNo input available. Provide the missing values on the command "
            "line, for example: python main.py --symbol gold --days 365 "
            "--timeframe 1h --chart",
            file=sys.stderr,
        )
        return 1

    except Exception as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        return 1
