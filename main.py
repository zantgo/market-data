#!/usr/bin/env python3
"""
Objective:
    Entry point of the market data command line interface.

    Run the tool with:

        python main.py

    The tool asks for an instrument, the amount of history, the candle
    timeframe and whether a candlestick chart should be generated. Every
    question can also be answered with a command line argument.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketdata.cli import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
