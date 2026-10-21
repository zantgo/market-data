"""
Objective:
    Interactive prompts used by the command line interface.

    The prompts ask for the instrument, the length of the history window,
    the candle timeframe and whether a chart should be rendered. Every prompt
    can be skipped by providing the matching command line argument.
"""

from __future__ import annotations

from .instruments import Instrument, search_instruments
from .period import Period, parse_period
from .timeframes import Timeframe, load_timeframes


MAX_SEARCH_RESULTS = 15

EXIT_COMMANDS = {"q", "quit", "exit"}


def prompt_instrument() -> Instrument:
    """Ask the user for an instrument and return the selected one."""
    print(
        "Instruments are read from the Dukascopy library, "
        f"so every published market is available."
    )
    print("Example searches: gold, EURUSD, AAPL, BTC, S&P, oil.\n")

    query = ""

    while True:
        label = f"Search [{query}]" if query else "Instrument"
        raw = input(f"{label} (e.g. gold, EURUSD, AAPL): ").strip()

        if raw.lower() in EXIT_COMMANDS:
            raise SystemExit(0)

        if raw:
            query = raw

        if not query:
            print("Please type a search term.\n")
            continue

        matches = search_instruments(query, limit=MAX_SEARCH_RESULTS)

        if not matches:
            print(f"No instrument matched {query!r}. Try a broader search.\n")
            query = ""
            continue

        if len(matches) == 1:
            print(f"Selected: {matches[0].describe()}\n")
            return matches[0]

        print()

        for index, instrument in enumerate(matches, start=1):
            print(
                f"  {index:2d}. {instrument.describe()}"
                f"  [{instrument.category_label}]"
            )

        print()

        selection = input(
            f"Select 1-{len(matches)} or type another search: "
        ).strip()

        if selection.isdigit():
            index = int(selection)

            if 1 <= index <= len(matches):
                return matches[index - 1]

            print("The selection is out of range.\n")
            continue

        if selection.lower() in EXIT_COMMANDS:
            raise SystemExit(0)

        if selection:
            query = selection


def prompt_period(default: Period) -> Period:
    """Ask the user for the length of the history window."""
    print()
    print("Enter the amount of history as a number with an optional unit.")
    print("Units: d = days, m = months, y = years.\n")

    while True:
        raw = input(f"Period [{default.file_label}]: ").strip()

        if not raw:
            return default

        if raw.lower() in EXIT_COMMANDS:
            raise SystemExit(0)

        try:
            return parse_period(raw)
        except ValueError as error:
            print(f"{error}\n")


def prompt_timeframe(default_code: str) -> Timeframe:
    """Ask the user for the candle timeframe."""
    timeframes = load_timeframes()
    default = next(
        (timeframe for timeframe in timeframes if timeframe.code == default_code),
        timeframes[0],
    )

    print()
    print("Available timeframes (downloaded natively, never aggregated):")

    for index, timeframe in enumerate(timeframes, start=1):
        print(f"  {index:2d}. {timeframe.code:<4} {timeframe.label}")

    print()

    while True:
        raw = input(
            f"Timeframe [{default.code}]: "
        ).strip()

        if not raw:
            return default

        if raw.lower() in EXIT_COMMANDS:
            raise SystemExit(0)

        if raw.isdigit():
            index = int(raw)

            if 1 <= index <= len(timeframes):
                return timeframes[index - 1]

            print("The selection is out of range.\n")
            continue

        from .timeframes import resolve_timeframe

        try:
            return resolve_timeframe(raw)
        except LookupError as error:
            print(f"{error}\n")


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Ask the user a yes or no question."""
    suffix = "[Y/n]" if default else "[y/N]"

    while True:
        raw = input(f"{question} {suffix}: ").strip()

        if not raw:
            return default

        if raw.lower() in EXIT_COMMANDS:
            raise SystemExit(0)

        if raw.lower() in ("y", "yes"):
            return True

        if raw.lower() in ("n", "no"):
            return False

        print("Please answer with y or n.\n")
