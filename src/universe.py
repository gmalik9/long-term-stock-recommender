"""Stock + ETF universe.

Tiers:
  - CURATED:   ~40 large-cap stocks across all 11 GICS sectors
  - WIDE_US:   ~300 stocks: large + mid caps + popular ADRs / foreign giants
  - ETFS:      Broad-market, sector, international, bond, and themed ETFs
"""
from __future__ import annotations

# ---------- Stocks ----------

CURATED: list[str] = [
    # Information Technology
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL",
    # Communication Services
    "GOOGL", "META", "DIS", "NFLX",
    # Consumer Discretionary
    "AMZN", "HD", "NKE", "MCD",
    # Consumer Staples
    "PG", "KO", "COST", "WMT",
    # Financials
    "JPM", "BAC", "V", "MA",
    # Health Care
    "JNJ", "UNH", "LLY", "PFE",
    # Industrials
    "CAT", "HON", "UNP", "RTX",
    # Energy
    "XOM", "CVX", "COP",
    # Materials
    "LIN", "FCX",
    # Utilities
    "NEE", "DUK",
    # Real Estate
    "AMT", "PLD",
]

# Wide US universe: large + mid caps across all sectors, plus popular ADRs.
_WIDE_EXTRA: list[str] = [
    # Tech (large + mid + semis + SaaS)
    "TSLA", "CRM", "ADBE", "INTC", "AMD", "QCOM", "TXN", "INTU", "IBM", "NOW",
    "ACN", "PANW", "SNOW", "DDOG", "CRWD", "ZS", "NET", "MDB", "TEAM", "SHOP",
    "WDAY", "ANET", "MU", "LRCX", "AMAT", "KLAC", "ADI", "MRVL", "ON", "MCHP",
    "PLTR", "FTNT", "DOCU", "OKTA", "TWLO", "SQ", "PYPL",
    # Communication Services
    "T", "VZ", "TMUS", "CMCSA", "CHTR", "EA", "TTWO", "WBD", "PINS", "SNAP",
    "ROKU", "SPOT", "UBER", "LYFT", "ABNB", "DASH",
    # Consumer Discretionary
    "LOW", "SBUX", "TGT", "BKNG", "TJX", "DPZ", "CMG", "MAR", "HLT", "F",
    "GM", "RIVN", "LCID", "BBY", "RCL", "CCL", "EBAY", "ETSY", "LULU", "YUM",
    "ROST", "ORLY", "AZO",
    # Consumer Staples
    "PEP", "MDLZ", "CL", "MO", "PM", "STZ", "KMB", "GIS", "K", "HSY",
    "SYY", "KR", "EL", "MNST", "KHC", "CHD",
    # Financials
    "BRK-B", "GS", "MS", "WFC", "C", "AXP", "BLK", "SCHW", "SPGI", "ICE",
    "CME", "MCO", "PNC", "USB", "TFC", "COF", "PYPL", "FIS", "AON", "MMC",
    "PGR", "ALL", "TRV", "MET", "PRU", "AIG",
    # Health Care
    "ABBV", "MRK", "TMO", "ABT", "DHR", "ISRG", "AMGN", "GILD", "BMY", "VRTX",
    "REGN", "MDT", "BSX", "SYK", "ZBH", "EW", "DXCM", "HUM", "CVS", "CI",
    "ELV", "MCK", "BDX", "BIIB", "MRNA", "ZTS",
    # Industrials
    "BA", "GE", "LMT", "DE", "MMM", "ETN", "EMR", "ITW", "PH", "GD",
    "NOC", "FDX", "UPS", "CSX", "NSC", "WM", "RSG", "PCAR", "CMI", "ROK",
    "DOV", "JCI", "OTIS", "URI",
    # Energy
    "SLB", "EOG", "PSX", "MPC", "OXY", "VLO", "PXD", "HES", "WMB", "KMI",
    "ENB", "EPD", "ET", "HAL", "DVN",
    # Materials
    "APD", "SHW", "ECL", "NEM", "DOW", "DD", "PPG", "NUE", "STLD", "VMC",
    "MLM", "CTVA",
    # Utilities
    "SO", "AEP", "D", "EXC", "SRE", "XEL", "PEG", "PCG", "ED", "EIX",
    "AWK", "WEC", "ES",
    # Real Estate
    "PSA", "CCI", "EQIX", "O", "SPG", "WELL", "DLR", "VICI", "AVB", "EQR",
    "EXR", "IRM", "SBAC",
    # Popular ADRs / foreign giants
    "TSM", "BABA", "ASML", "NVO", "TM", "SONY", "SHEL", "BP", "AZN", "SAP",
    "SNY", "RIO", "BHP", "VALE", "PDD", "JD", "BIDU", "NIO", "HSBC", "UL",
    "DEO", "BTI", "MUFG", "ING", "BCS",
    # More ADRs (Europe / Asia / LatAm)
    "NVS", "GSK", "RHHBY", "NSRGY", "LVMUY", "SIEGY", "DB", "ERIC", "NOK",
    "PHG", "STLA", "VWAGY", "BMWYY", "MBGYY", "E", "EQNR", "TOT", "TTE",
    "RACE", "SE", "GRAB", "CPNG", "MELI", "NU", "VIPS", "LI", "XPEV",
    "BILI", "TCOM", "NTES", "YMM", "TME", "YUMC", "WB", "BEKE", "FUTU",
    "TIGR", "INFY", "WIT", "HDB", "IBN", "RDY", "TAK", "HMC", "NMR",
    "MFG", "SMFG", "LYG", "NWG", "UBS", "CS", "BBVA", "SAN", "ITUB",
    "BSBR", "BBD", "PBR", "VRT", "YPF", "GGB", "SID", "CIG", "ABEV",
    "FMX", "AMX", "KB", "SHG", "WF", "PKX", "LPL", "CHL",
]

WIDE_US: list[str] = sorted(set(CURATED + _WIDE_EXTRA))

# ---------- ETFs ----------

ETFS: list[str] = [
    # Broad market / index
    "SPY", "VOO", "IVV", "VTI", "ITOT", "QQQ", "QQQM", "DIA", "IWM", "IJH",
    # Sector ETFs (SPDR)
    "XLK", "XLF", "XLV", "XLE", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC",
    # International
    "VXUS", "VEA", "VWO", "EFA", "EEM", "IEFA", "IEMG", "ACWI",
    # Themed / popular
    "ARKK", "SMH", "SOXX", "QUAL", "MTUM", "VUG", "VTV", "SCHD", "DGRO",
    # Bonds (for balance)
    "BND", "AGG", "TLT", "IEF", "LQD", "HYG",
    # Commodities
    "GLD", "IAU", "SLV", "USO", "UNG", "DBC", "PDBC",
    # Leveraged long (2x / 3x) -- high risk, short-term tactical only
    "TQQQ", "SQQQ", "UPRO", "SPXL", "SPXU", "UDOW", "SDOW", "TNA", "TZA",
    "SOXL", "SOXS", "TECL", "TECS", "FAS", "FAZ", "LABU", "LABD", "CURE",
    "ERX", "ERY", "NUGT", "DUST", "JNUG", "JDST", "BOIL", "KOLD", "UCO",
    "SCO", "UVXY", "SVXY", "TMF", "TMV",
    # Single-stock leveraged (popular)
    "TSLL", "TSLZ", "NVDL", "NVDS", "AAPU", "AAPD", "MSFU", "MSFD",
    "AMZU", "AMZD", "GOOL", "METU", "BRKU", "COIL", "CONL",
]

# Fast lookup
ETF_SET = set(ETFS)


# ---------- Sector fallback ----------

SECTOR_MAP: dict[str, str] = {
    # Tech
    **dict.fromkeys(
        ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "INTC", "AMD",
         "QCOM", "TXN", "INTU", "IBM", "NOW", "ACN", "PANW", "SNOW", "DDOG",
         "CRWD", "ZS", "NET", "MDB", "TEAM", "SHOP", "WDAY", "ANET", "MU",
         "LRCX", "AMAT", "KLAC", "ADI", "MRVL", "ON", "MCHP", "PLTR", "FTNT",
         "DOCU", "OKTA", "TWLO", "SQ", "PYPL", "TSM", "ASML", "SAP", "FIS"],
        "Information Technology",
    ),
    # Comm services
    **dict.fromkeys(
        ["GOOGL", "META", "DIS", "NFLX", "T", "VZ", "TMUS", "CMCSA", "CHTR",
         "EA", "TTWO", "WBD", "PINS", "SNAP", "ROKU", "SPOT", "BIDU"],
        "Communication Services",
    ),
    # Consumer discretionary
    **dict.fromkeys(
        ["AMZN", "HD", "NKE", "MCD", "TSLA", "LOW", "SBUX", "TGT", "BKNG",
         "TJX", "DPZ", "CMG", "MAR", "HLT", "F", "GM", "RIVN", "LCID", "BBY",
         "RCL", "CCL", "EBAY", "ETSY", "LULU", "YUM", "ROST", "ORLY", "AZO",
         "UBER", "LYFT", "ABNB", "DASH", "TM", "SONY", "BABA", "PDD", "JD",
         "NIO"],
        "Consumer Discretionary",
    ),
    # Consumer staples
    **dict.fromkeys(
        ["PG", "KO", "COST", "WMT", "PEP", "MDLZ", "CL", "MO", "PM", "STZ",
         "KMB", "GIS", "K", "HSY", "SYY", "KR", "EL", "MNST", "KHC", "CHD",
         "UL", "DEO", "BTI"],
        "Consumer Staples",
    ),
    # Financials
    **dict.fromkeys(
        ["JPM", "BAC", "V", "MA", "BRK-B", "GS", "MS", "WFC", "C", "AXP",
         "BLK", "SCHW", "SPGI", "ICE", "CME", "MCO", "PNC", "USB", "TFC",
         "COF", "AON", "MMC", "PGR", "ALL", "TRV", "MET", "PRU", "AIG",
         "HSBC", "MUFG", "ING", "BCS"],
        "Financials",
    ),
    # Health care
    **dict.fromkeys(
        ["JNJ", "UNH", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR",
         "ISRG", "AMGN", "GILD", "BMY", "VRTX", "REGN", "MDT", "BSX", "SYK",
         "ZBH", "EW", "DXCM", "HUM", "CVS", "CI", "ELV", "MCK", "BDX", "BIIB",
         "MRNA", "ZTS", "NVO", "AZN", "SNY"],
        "Health Care",
    ),
    # Industrials
    **dict.fromkeys(
        ["CAT", "HON", "UNP", "RTX", "BA", "GE", "LMT", "DE", "MMM", "ETN",
         "EMR", "ITW", "PH", "GD", "NOC", "FDX", "UPS", "CSX", "NSC", "WM",
         "RSG", "PCAR", "CMI", "ROK", "DOV", "JCI", "OTIS", "URI"],
        "Industrials",
    ),
    # Energy
    **dict.fromkeys(
        ["XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "OXY", "VLO", "PXD",
         "HES", "WMB", "KMI", "ENB", "EPD", "ET", "HAL", "DVN", "SHEL", "BP"],
        "Energy",
    ),
    # Materials
    **dict.fromkeys(
        ["LIN", "FCX", "APD", "SHW", "ECL", "NEM", "DOW", "DD", "PPG", "NUE",
         "STLD", "VMC", "MLM", "CTVA", "RIO", "BHP", "VALE"],
        "Materials",
    ),
    # Utilities
    **dict.fromkeys(
        ["NEE", "DUK", "SO", "AEP", "D", "EXC", "SRE", "XEL", "PEG", "PCG",
         "ED", "EIX", "AWK", "WEC", "ES"],
        "Utilities",
    ),
    # Real estate
    **dict.fromkeys(
        ["AMT", "PLD", "PSA", "CCI", "EQIX", "O", "SPG", "WELL", "DLR", "VICI",
         "AVB", "EQR", "EXR", "IRM", "SBAC"],
        "Real Estate",
    ),
}


def get_universe(mode: str = "Curated") -> list[str]:
    """Return tickers for the selected universe mode.

    Modes:
      "Curated"          -> ~40 large-cap stocks
      "Wide US"          -> ~300 stocks (large + mid caps + ADRs)
      "Wide US + ETFs"   -> Wide US + broad/sector/international/bond ETFs
      "ETFs only"        -> Index, sector, international and bond ETFs only
    """
    if mode == "Wide US":
        return WIDE_US
    if mode == "Wide US + ETFs":
        return sorted(set(WIDE_US + ETFS))
    if mode == "ETFs only":
        return ETFS
    return CURATED
