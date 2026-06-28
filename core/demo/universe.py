"""Starter scanning universe + hard-coded float lookup for the demo.

Float data is NOT available from Alpaca's free tier, so Tier-B (Five Pillars)
requires a float number from this lookup. Symbols with no entry resolve to
``None`` → reported as "UNKNOWN" in the UI and EXCLUDED from Tier B (fail-safe,
spec §1 Pillar-2: no float = no trade).

Float values are approximate free-float share counts (shares, not millions) for
known historically-low-float momentum names. They are demo placeholders only —
production resolves float via ``core.scanner.float_resolver`` (EDGAR + vendor).
spec §1 / §13.1.
"""

from __future__ import annotations

# ~200 known low-float / small-cap momentum names (deduplicated, order preserved).
STARTER_UNIVERSE: list[str] = list(
    dict.fromkeys(
        [
            "CLOV", "MVIS", "WISH", "BBIG", "ATER", "PROG", "GFAI", "MULN", "IDEX",
            "NKLA", "SNDL", "CENN", "FFIE", "XELA", "GOVX", "WISA", "ILUS", "ZEST",
            "VERB", "INPX", "TNXP", "CYCC", "SIGA", "BTBT", "AGRI", "AULT", "GREE",
            "MRIN", "CODA", "AGTC", "NCTY", "KPLT", "OPAD", "ATXI", "TPVG", "MVST",
            "GMDA", "WKHS", "RIDE", "SOLO", "GOEV", "NXTP", "XBIO", "ITRM", "MFON",
            "EDTX", "PROP", "SPGX", "CPRX", "MDRX", "GURE", "BHAT", "MEIP", "ENTX",
            "ACST", "BIVI", "MDNA", "ATOS", "MMAT", "SEEL", "PALI", "PHVS", "CTRM",
            "BLNK", "SPCE", "IDAI", "LIQT", "MYSZ", "NAKD", "BLTM", "HYMC", "NTRB",
            "UAVS", "HCDI", "CUEN", "CANN", "DPLO", "ENVB", "LCTX", "MARA", "RIOT",
            "HIPO", "GOCO", "ANTE", "EZGO", "MOGO", "CGEN", "MOXC", "DRIO", "CETX",
            "BNMV", "AABB", "SXTC", "USAU", "ATNF", "BURG", "CLPS", "IMPP", "INDO",
            "ISIG", "KALI", "LIFW", "MICT", "NXRT", "OPHC", "PLRX", "QMCI", "RELI",
            "RVNC", "SCOA", "SFIO", "SHIP", "TAOP", "TPCS", "UONE", "UTME", "VCNX",
            "VNRX", "WTRH", "XTIA", "ZDGE", "ZIVO",
        ]
    )
)

# Approximate free-float (shares). Demo placeholder data; None elsewhere → UNKNOWN.
FLOAT_LOOKUP: dict[str, int] = {
    "CLOV": 410_000_000,   # large float — will FAIL Tier-B 20M ceiling (correct)
    "MVIS": 180_000_000,
    "ATER": 35_000_000,
    "PROG": 480_000_000,
    "GFAI": 6_500_000,
    "MULN": 75_000_000,
    "IDEX": 95_000_000,
    "NKLA": 90_000_000,
    "CENN": 12_000_000,
    "FFIE": 18_000_000,
    "XELA": 9_000_000,
    "GOVX": 14_000_000,
    "WISA": 4_500_000,
    "ILUS": 19_000_000,
    "TNXP": 7_500_000,
    "CYCC": 3_200_000,
    "SIGA": 38_000_000,
    "BTBT": 110_000_000,
    "AULT": 16_000_000,
    "GREE": 60_000_000,
    "MRIN": 11_000_000,
    "KPLT": 13_000_000,
    "MVST": 95_000_000,
    "GMDA": 8_000_000,
    "WKHS": 160_000_000,
    "RIDE": 70_000_000,
    "SOLO": 95_000_000,
    "GOEV": 40_000_000,
    "XBIO": 2_100_000,
    "ITRM": 6_800_000,
    "CPRX": 100_000_000,
    "BHAT": 5_000_000,
    "MEIP": 13_000_000,
    "ENTX": 9_500_000,
    "ACST": 4_000_000,
    "BIVI": 6_000_000,
    "MDNA": 12_000_000,
    "ATOS": 17_000_000,
    "MMAT": 320_000_000,
    "SEEL": 9_000_000,
    "PALI": 5_500_000,
    "PHVS": 8_500_000,
    "CTRM": 14_000_000,
    "BLNK": 60_000_000,
    "SPCE": 290_000_000,
    "MYSZ": 7_000_000,
    "NAKD": 19_500_000,
    "HYMC": 90_000_000,
    "NTRB": 3_500_000,
    "UAVS": 11_000_000,
    "HCDI": 6_000_000,
    "CUEN": 5_000_000,
    "ENVB": 7_500_000,
    "LCTX": 95_000_000,
    "MARA": 280_000_000,
    "RIOT": 230_000_000,
    "HIPO": 18_000_000,
    "MOGO": 70_000_000,
    "CGEN": 80_000_000,
    "MOXC": 8_000_000,
    "DRIO": 19_000_000,
    "CETX": 4_500_000,
    "SXTC": 6_500_000,
    "USAU": 11_000_000,
    "ATNF": 7_000_000,
    "CLPS": 9_000_000,
    "IMPP": 12_000_000,
    "INDO": 9_500_000,
    "ISIG": 2_800_000,
    "LIFW": 14_000_000,
    "MICT": 17_000_000,
    "OPHC": 13_000_000,
    "RELI": 8_000_000,
    "RVNC": 70_000_000,
    "SHIP": 16_000_000,
    "UONE": 4_000_000,
    "VCNX": 6_000_000,
    "VNRX": 10_000_000,
    "WTRH": 19_000_000,
    "XTIA": 3_000_000,
    "ZDGE": 13_000_000,
    "ZIVO": 8_500_000,
}


def float_for(symbol: str) -> int | None:
    """Return the demo float (shares) for a symbol, or None if UNKNOWN."""
    return FLOAT_LOOKUP.get(symbol.upper())
