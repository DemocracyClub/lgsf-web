from pathlib import Path

WELSH_COUNCILS = [
    "AGY",
    "GWN",
    "CWY",
    "DEN",
    "FLN",
    "WRX",
    "CGN",
    "PEM",
    "CMN",
    "SWA",
    "NTL",
    "BGE",
    "VGL",
    "CRF",
    "RCT",
    "CAY",
    "BGW",
    "TOF",
    "MON",
    "NWP",
    "POW",
    "MTY",
]

GREATER_MANCHESTER_COUNCILS = [
    "BOL",
    "BUR",
    "MAN",
    "OLD",
    "RCH",
    "SLF",
    "SKP",
    "TAM",
    "TRF",
    "WGN",
]

ALL_COUNCILS = WELSH_COUNCILS + GREATER_MANCHESTER_COUNCILS


DATA_DIR = Path("lgsf_web/apps/councillors/temp_data/")
