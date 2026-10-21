"""
Objective:
    Shared configuration values for the market data toolkit.

Configuration:
    BASE_DIR points at the project root, so every path is resolved relative
    to the repository and not to the current working directory.
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"


# ---------------------------------------------------------------------------
# Data contract
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]
CSV_COLUMN_NAMES = ["Open", "High", "Low", "Close", "Volume"]


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_DAYS = 365
DEFAULT_TIMEFRAME = "1h"

DEFAULT_MOVING_AVERAGES = (20, 50)
DEFAULT_CHART_CANDLES = 1000
CHART_FIGSIZE = (16, 9)
CHART_DPI = 150


# ---------------------------------------------------------------------------
# Download tuning
# ---------------------------------------------------------------------------

MAX_RETRIES = 5
MAX_EMPTY_RETRIES = 4
INITIAL_RETRY_DELAY_SECONDS = 2.0
PAUSE_BETWEEN_CHUNKS_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 60.0
