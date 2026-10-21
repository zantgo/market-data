# Market Data

A small Python command line tool that downloads historical OHLCV candles from
Dukascopy and optionally renders a candlestick chart with volume and moving
averages.

Everything is driven by `python main.py`: the tool asks for the instrument,
the amount of history, the candle timeframe and whether a chart should be
generated. Every question can also be answered up front with a command line
argument so the tool can run unattended.

## Features

- Interactive selection of any instrument published by Dukascopy.
- Instruments and candle intervals are discovered dynamically from the
  installed `dukascopy-python` package, nothing is hardcoded.
- **Only natively published candles are downloaded.** No candle is ever
  aggregated, resampled or synthesised, so every row in the CSV is exactly
  what Dukascopy published for that interval.
- History window expressed in days, months or years (365 days by default).
- Strict UTC: every timestamp is stored with an explicit `+00:00` offset and
  the download window ends on a closed candle boundary, so no partial candle
  is ever stored.
- Automatic quality checks on the downloaded data (unique and sorted index,
  parseable prices) plus a report of everything unusual that was found and
  deliberately kept: flat candles, candles without volume and the gaps
  between sessions.
- Monthly download cache, so interrupted downloads resume automatically.
- CSV output with UTC timestamps and optional PNG candlestick chart.
- Fully automated mode through command line arguments.

## Requirements

- Python 3.10 or newer
- pip
- Internet access

## Installation

On Ubuntu or WSL, install virtual environment support if necessary:

```bash
sudo apt update
sudo apt install -y python3-venv
```

Create the environment and install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Usage

Run the interactive assistant:

```bash
python main.py
```

The prompts are:

1. **Instrument** — search the catalogue, for example `gold`, `EURUSD`,
   `AAPL`, `bitcoin`, `s&p` or `oil`. Type another search to refine the
   list, or pick one of the numbered matches.
2. **Period** — the amount of history as a number with an optional unit:
   `365` (days), `30d`, `6m` or `2y`. The default is 365 days.
3. **Timeframe** — pick one of the natively published candle sizes.
4. **Chart** — answer `y` to render a candlestick chart with volume and
   moving averages.

### Command line arguments

Every prompt can be skipped, which is useful for scripts and cron jobs:

```bash
python main.py --symbol gold --days 365 --timeframe 1h --chart
python main.py --symbol EURUSD --months 6 --timeframe 15m --no-chart
python main.py --symbol BTC --years 2 --timeframe 1d --chart --candles 500
```

| Argument | Description |
| --- | --- |
| `-s`, `--symbol` | Instrument to download, e.g. `gold`, `EURUSD`, `XAU/USD`. |
| `-d`, `--days` | Number of days of history. |
| `-M`, `--months` | Number of months of history. |
| `-Y`, `--years` | Number of years of history. |
| `-t`, `--timeframe` | Candle timeframe, e.g. `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `1w`. |
| `--chart` / `--no-chart` | Force the chart on or off. |
| `--candles` | Number of candles to plot (default `1000`). |
| `--mas` | Moving average periods, comma separated (default `20,50`). |
| `--data-dir` | Directory for the CSV and PNG files (default `data`). |
| `--cache-dir` | Directory for the download cache (default `cache`). |
| `--list-instruments` | Print every instrument published by Dukascopy. |
| `--list-timeframes` | Print every supported timeframe. |
| `--non-interactive` | Never ask questions, fail when a value is missing. |
| `--show` | Open the rendered chart in the default image viewer. |
| `-q`, `--quiet` | Only print the resulting file path. |
| `-v`, `--verbose` | Show the log output of the Dukascopy library. |

## Instruments

The catalogue is read from the installed `dukascopy-python` package, so all
published markets are available: FX majors and crosses, metals,
cryptocurrencies, indices, ETFs, bonds, commodities and single stocks.

```bash
python main.py --list-instruments
```

## Timeframes

The list is built from the intervals the provider actually publishes. Every
one of them is downloaded as published, nothing is aggregated.

| Timeframe | Provider interval |
| --- | --- |
| `1m` | `1MIN` |
| `5m` | `5MIN` |
| `10m` | `10MIN` |
| `15m` | `15MIN` |
| `30m` | `30MIN` |
| `1h` | `1HOUR` |
| `4h` | `4HOUR` |
| `1d` | `1DAY` |
| `1w` | `1WEEK` |
| `1mo` | `1MONTH` |

Intervals that Dukascopy does not publish, such as 3 minutes, 8 hours or
12 hours, are not offered at all. Downloading them would require
aggregating smaller candles, which is intentionally not done.

```bash
python main.py --list-timeframes
```

## Data quality

The dataset is the data the provider published. Nothing is reshaped,
smoothed or filled: flat candles, candles without volume, weekend candles
and the gaps between sessions stay exactly as they were sent, because that
is what a realistic backtest needs.

The downloaded candles are inspected and the result is reported:

- the index is converted to UTC and sorted;
- duplicate timestamps are counted, the last row wins;
- rows whose prices cannot be parsed at all are removed;
- candles with a non positive price, an inconsistent high or low, a negative
  volume, no price movement or no volume are counted and **kept**;
- candles missing inside the series are counted and the largest gaps are
  listed. Missing candles are market closures and daily breaks, they are
  never filled with invented candles.

```text
Candles:       31,556
First candle:  2026-09-21T20:13:00+00:00
Last candle:   2026-10-21T20:11:00+00:00
Flat candles without movement (kept): 271
Candles missing inside the series: 11,644
```

## Output

Files are written to `data/`:

- `data/<SYMBOL>_<TIMEFRAME>_<PERIOD>.csv` — OHLCV candles with a UTC
  `Date` column in ISO 8601 format and `Open`, `High`, `Low`, `Close`,
  `Volume` columns.
- `data/<SYMBOL>_<TIMEFRAME>_<CANDLES>_candles.png` — candlestick chart with
  a volume panel and moving averages.

Downloads are cached per month in `cache/`, so a repeated run only fetches
what is missing. Every cached chunk stores the range it covers. When the
running month gains new candles, the stale chunk is detected and downloaded
again, so the dataset never silently misses the newest candles.

## Notes

- Timestamps are UTC and the prices come from the BID feed.
- The download stops at the last closed candle, so the newest row is always
  complete. Use `--days`/`--months`/`--years` to control the history length.
- Dukascopy volume should not be read as exchange traded volume. For CFDs it
  can represent tick activity.
- Daily and higher timeframes contain candles for days without trading, as
  published by the provider. They are reported as flat candles.

## Project structure

```
main.py                    entry point
marketdata/
    cli.py                 arguments and workflow
    prompts.py             interactive questions
    instruments.py         dynamic instrument catalogue and search
    timeframes.py          dynamic interval discovery
    downloader.py          Dukascopy download with retries and cache
    quality.py             validation and quality report
    storage.py             CSV reading and writing
    charts.py              candlestick chart rendering
    period.py              history window handling
    config.py              shared configuration
```
