# Market Data

A lightweight Python utility for downloading historical one-minute OHLCV
candles from Dukascopy for market analysis and backtesting.

## Features

- One-minute (M1) OHLCV candles.
- Configurable historical period in days.
- Configurable market symbol.
- CSV output.
- Monthly cache to help resume interrupted downloads.
- UTC timestamps.

## Supported Symbol Examples

Configure the `SYMBOL` constant in `download_m1.py`:

- `GOLDUSD` — Gold/USD (default).
- `EURUSD` — Euro/USD.
- `SP500USD` — S&P 500 CFD.
- `TSLAUSD` — Tesla CFD.
- `BTCUSD` — Bitcoin/USD, subject to provider availability.

The `DAYS_TO_DOWNLOAD` constant controls the historical period.
The default is 365 days.

## Requirements

- Python 3
- pip
- Internet access

## Installation

On Ubuntu or WSL, install virtual environment support if necessary:

sudo apt update
sudo apt install -y python3-venv

