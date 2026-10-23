"""
Objective:
    Discover every instrument offered by Dukascopy and make them searchable.

    The catalogue is built dynamically from the ``dukascopy_python.instruments``
    module, so no instrument list is hardcoded in this project. Friendly
    display names and alternative spellings are only a presentation layer on
    top of the provider data.

Public API:
    Instrument         - description of a single Dukascopy instrument.
    load_catalogue()   - every instrument exposed by the installed library.
    search_instruments() - ranked search over the catalogue.
    resolve_instrument()  - resolve a user query into a single instrument.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from dukascopy_python import instruments as dukascopy_instruments


# ---------------------------------------------------------------------------
# Catalogue structure
# ---------------------------------------------------------------------------

CATEGORY_LABELS = {
    "FX_CROSSES": "FX Crosses",
    "FX_MAJORS": "FX Majors",
    "FX_METALS": "FX Metals",
    "VCCY": "Cryptocurrencies",
    "CMD_AGRICULTURAL": "Agricultural Commodities",
    "CMD_ENERGY": "Energy Commodities",
    "CMD_METALS": "Industrial Metals",
    "ETF_CFD": "ETFs",
    "BND_CFD": "Bonds",
    "IDX": "Indices",
}

CATEGORY_PREFIXES = (
    "FX_CROSSES",
    "FX_MAJORS",
    "FX_METALS",
    "VCCY",
    "CMD_AGRICULTURAL",
    "CMD_ENERGY",
    "CMD_METALS",
    "ETF_CFD",
    "BND_CFD",
    "IDX",
)

STOCK_MARKETS = {
    "AUSTRIA": "Austria",
    "BELGIUM": "Belgium",
    "DENMARK": "Denmark",
    "FINLAND": "Finland",
    "FRANCE": "France",
    "GERMANY": "Germany",
    "HONG_KONG": "Hong Kong",
    "IRELAND": "Ireland",
    "ITALY": "Italy",
    "JAPAN": "Japan",
    "MEXICO": "Mexico",
    "NETHERLANDS": "Netherlands",
    "NORWAY": "Norway",
    "PORTUGAL": "Portugal",
    "SPAIN": "Spain",
    "SWEDEN": "Sweden",
    "SWITZERLAND": "Switzerland",
    "UK": "United Kingdom",
    "US": "United States",
}


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------

CURRENCY_NAMES = {
    "AUD": "Australian Dollar",
    "BRL": "Brazilian Real",
    "CAD": "Canadian Dollar",
    "CHF": "Swiss Franc",
    "CNH": "Chinese Yuan",
    "CZK": "Czech Koruna",
    "DKK": "Danish Krone",
    "EUR": "Euro",
    "GBP": "Pound Sterling",
    "HKD": "Hong Kong Dollar",
    "HUF": "Hungarian Forint",
    "ILS": "Israeli Shekel",
    "JPY": "Yen",
    "MXN": "Mexican Peso",
    "NOK": "Norwegian Krone",
    "NZD": "New Zealand Dollar",
    "PLN": "Polish Zloty",
    "RON": "Romanian Leu",
    "RUB": "Russian Ruble",
    "SEK": "Swedish Krona",
    "SGD": "Singapore Dollar",
    "THB": "Thai Baht",
    "TRY": "Turkish Lira",
    "USD": "US Dollar",
    "ZAR": "South African Rand",
}

ASSET_NAMES = {
    "ADA": "Cardano",
    "AVAX": "Avalanche",
    "BCH": "Bitcoin Cash",
    "BTC": "Bitcoin",
    "DOT": "Polkadot",
    "DSH": "Dash",
    "EOS": "EOS",
    "ETH": "Ethereum",
    "LINK": "Chainlink",
    "LTC": "Litecoin",
    "MAT": "Polkast",
    "MKR": "Maker",
    "TRX": "TRON",
    "UNI": "Uniswap",
    "XLM": "Stellar",
    "XMR": "Monero",
    "XRP": "Ripple",
    "YFI": "yearn.finance",
}

METAL_NAMES = {
    "XAG": "Silver",
    "XAU": "Gold",
    "XPD": "Palladium",
    "XPT": "Platinum",
}

PROVIDER_ALIASES = {
    "E_Brent": "Brent Crude Oil",
    "E_Light": "Crude Oil WTI",
    "E_NQ-100": "Nasdaq 100 Index",
    "E_SandP-500": "S&P 500 Index",
    "E_Futsee-100": "Euro Stoxx 50 Index",
    "USSC2000.IDX/USD": "US Small Cap 2000 Index",
    "DOLLAR.IDX/USD": "US Dollar Index",
    "RUSSELL.IDX/USD": "Russell 2000 Index",
    "VOL.IDX/USD": "CBOE Volatility Index",
}

# Alternative spellings that map onto a provider symbol. They only widen the
# search, every published instrument stays selectable.
SYMBOL_ALIASES = {
    "GOLDUSD": "XAU/USD",
    "SILVERUSD": "XAG/USD",
    "PLATINUMUSD": "XPT.CMD/USD",
    "SP500USD": "E_SandP-500",
    "SP500": "E_SandP-500",
    "US500": "E_SandP-500",
    "US500USD": "E_SandP-500",
    "NASDAQ100": "E_NQ-100",
    "BTCUSD": "BTC/USD",
    "ETHUSD": "ETH/USD",
    "OILUSD": "E_Light",
    "WTIUSD": "E_Light",
    "CRUDEOILUSD": "E_Light",
}

_COMPACT = re.compile(r"[^0-9A-Z]+")
_READABLE = re.compile(r"[\s_]+")
_TOKENS = re.compile(r"[\s/\-_&.]+")


def weighted_variants(text: str) -> list[tuple[str, float]]:
    """Return the query forms with their weight.

    The readable form is more specific than the compact one, so it is
    weighted higher. This keeps a query such as ``s&p`` from matching every
    symbol starting with ``SP``.
    """
    upper = str(text).upper()

    compact = _COMPACT.sub("", upper)
    readable = _READABLE.sub("", upper)

    weighted: list[tuple[str, float]] = []

    if readable:
        weighted.append((readable, 1.0))

    if compact and compact != readable:
        weighted.append((compact, 0.9))

    return weighted


def word_tokens(text: str) -> set[str]:
    """Return the individual words of a text, used for multi word queries."""
    return {
        token.upper()
        for token in _TOKENS.split(str(text))
        if token
    }


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Instrument:
    """A single Dukascopy instrument."""

    constant: str
    provider_symbol: str
    category: str
    category_label: str
    ticker: str
    display_name: str
    slug: str
    search_keys: tuple[str, ...] = field(default_factory=tuple)
    context_keys: tuple[str, ...] = field(default_factory=tuple)

    def describe(self) -> str:
        """Return a one line description used in prompts and listings."""
        if self.display_name == self.provider_symbol:
            return self.display_name

        return f"{self.display_name} ({self.provider_symbol})"


# ---------------------------------------------------------------------------
# Catalogue construction
# ---------------------------------------------------------------------------

def _split_constant(constant: str) -> tuple[str, str]:
    """Split a constant name into its category key and its symbol hint."""
    name = constant[len("INSTRUMENT_"):]

    for prefix in CATEGORY_PREFIXES:
        if name.startswith(prefix + "_"):
            return prefix, name[len(prefix) + 1:]

    for market in STOCK_MARKETS:
        if name.startswith(market + "_"):
            return market, name[len(market) + 1:]

    return name.split("_", 1)[0], name.split("_", 1)[-1]


def _build_labels(
    provider_symbol: str,
    category: str,
    symbol_hint: str,
) -> tuple[str, str, str, str]:
    """Return base ticker, base label, quote and display name."""
    base, _, quote = provider_symbol.partition("/")

    base_ticker = base.split(".", 1)[0]

    if provider_symbol in PROVIDER_ALIASES:
        display_name = PROVIDER_ALIASES[provider_symbol]
        return base_ticker, display_name, quote, display_name

    if base_ticker in METAL_NAMES:
        base_label = METAL_NAMES[base_ticker]

    elif category == "VCCY" and base_ticker in ASSET_NAMES:
        base_label = ASSET_NAMES[base_ticker]

    elif category in ("FX_CROSSES", "FX_MAJORS"):
        base_label = CURRENCY_NAMES.get(base_ticker, base_ticker)

    else:
        base_label = base_ticker or symbol_hint.replace("_", ".")

    if not quote:
        return base_ticker, base_label, "", base_label

    if category in STOCK_MARKETS:
        return base_ticker, base_label, quote, base or base_label

    if category in ("FX_CROSSES", "FX_MAJORS"):
        quote_label = CURRENCY_NAMES.get(quote, quote)
    else:
        quote_label = quote

    return base_ticker, base_label, quote, f"{base_label}/{quote_label}"


def _build_instrument(constant: str, provider_symbol: str) -> Instrument:
    """Build an :class:`Instrument` from a catalogue entry."""
    category, symbol_hint = _split_constant(constant)

    base_ticker, base_label, quote, display_name = _build_labels(
        provider_symbol, category, symbol_hint
    )

    if category in CATEGORY_LABELS:
        category_label = CATEGORY_LABELS[category]
    elif category in STOCK_MARKETS:
        category_label = f"{STOCK_MARKETS[category]} Stocks"
    else:
        category_label = category.replace("_", " ").title()

    slug = _COMPACT.sub("", provider_symbol.upper()) or _COMPACT.sub(
        "", symbol_hint.upper()
    )

    keys = {
        provider_symbol,
        base_ticker,
        base_label,
        display_name,
        symbol_hint.replace("_", "."),
    }

    if quote:
        keys.add(f"{base_ticker}{quote}")

    for alias, target in SYMBOL_ALIASES.items():
        if target == provider_symbol:
            keys.add(alias)

    search_keys = tuple(sorted({key for key in keys if key}))
    context_keys = (category_label,)

    return Instrument(
        constant=constant,
        provider_symbol=provider_symbol,
        category=category,
        category_label=category_label,
        ticker=base_ticker,
        display_name=display_name,
        slug=slug,
        search_keys=search_keys,
        context_keys=context_keys,
    )


@lru_cache(maxsize=1)
def load_catalogue() -> tuple[Instrument, ...]:
    """Return every instrument exposed by the installed Dukascopy library."""
    entries = []

    for name, value in vars(dukascopy_instruments).items():
        if not name.startswith("INSTRUMENT_"):
            continue

        if not isinstance(value, str) or not value:
            continue

        entries.append(_build_instrument(name, value))

    entries.sort(key=lambda item: (item.category_label, item.display_name))

    return tuple(entries)


# ---------------------------------------------------------------------------
# Search and resolution
# ---------------------------------------------------------------------------

def _match_score(key: str, query_variants: list[tuple[str, float]]) -> int:
    """Score a single key against the weighted query variants."""
    upper = str(key).upper()
    key_compact = _COMPACT.sub("", upper)
    key_readable = _READABLE.sub("", upper)

    best = 0.0

    for query_variant, weight in query_variants:
        score = 0

        if query_variant == key_compact or query_variant == key_readable:
            score = 100

        elif len(query_variant) >= 2:
            if key_readable.startswith(query_variant):
                score = 95

            elif key_compact.startswith(query_variant):
                score = 85

            elif query_variant in key_readable:
                score = 70

            elif query_variant in key_compact:
                score = 60

        best = max(best, score * weight)

    return int(best)


def _score(instrument: Instrument, query: str) -> int:
    """Score how well an instrument matches a query."""
    query_variants = weighted_variants(query)
    best = 0

    for key in instrument.search_keys:
        best = max(best, _match_score(key, query_variants))

    # The category is only a hint, so it never outranks a real match.
    for key in instrument.context_keys:
        best = max(best, min(_match_score(key, query_variants), 70))

    tokens = [token.upper() for token in _TOKENS.split(str(query)) if token]

    if len(tokens) > 1:
        key_tokens = set()

        for key in instrument.search_keys:
            key_tokens |= word_tokens(key)

        if all(token in key_tokens for token in tokens):
            best = max(best, 55)

    return best


def _result_order(instrument: Instrument) -> tuple:
    """Order equally scored instruments, US dollar quotes come first."""
    base, _, quote = instrument.provider_symbol.partition("/")

    return (quote not in ("", "USD"), len(instrument.display_name), instrument.display_name)


def search_instruments(query: str, limit: int = 20) -> list[Instrument]:
    """Return the instruments that best match a free form query."""
    scored = [
        (score, instrument)
        for instrument in load_catalogue()
        if (score := _score(instrument, query)) > 0
    ]

    scored.sort(key=lambda item: (-item[0], _result_order(item[1])))

    return [instrument for _, instrument in scored[:limit]]


def resolve_instrument(query: str) -> Instrument:
    """Resolve a free form query into a single Dukascopy instrument."""
    matches = search_instruments(query, limit=1)

    if not matches:
        raise LookupError(
            f"No Dukascopy instrument matches {query!r}. "
            "Use --list-instruments to browse the catalogue."
        )

    return matches[0]
