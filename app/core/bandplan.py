from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Band:
    name: str
    start_mhz: float
    end_mhz: float
    mode_hint: str
    notes: str = ""


# Starter US-centric band hints for classification UI / future scanners
BANDS: list[Band] = [
    Band("FM Broadcast", 88.0, 108.0, "analog_fm", "Broadcast FM"),
    Band("Aircraft AM", 118.0, 137.0, "analog_am", "Airband"),
    Band("NOAA APT", 137.0, 138.0, "noaa_apt", "Weather satellites"),
    Band("2m Ham", 144.0, 148.0, "ham_vhf", "Amateur VHF"),
    Band("NOAA Weather Radio", 162.4, 162.55, "noaa_wx", "SAME / voice"),
    Band("Marine VHF", 156.0, 162.025, "marine", "Maritime"),
    Band("Military air (approx)", 225.0, 400.0, "mil_air", "Wide UHF air"),
    Band("70cm Ham", 420.0, 450.0, "ham_uhf", "Amateur UHF"),
    Band("GMRS / FRS", 462.0, 467.0, "gmrs", "Personal radio"),
    Band("2m DMR / YSF / D-STAR (hint)", 144.0, 148.0, "dmr", "Often analog + digital mix"),
    Band("70cm DMR / YSF / D-STAR (hint)", 420.0, 450.0, "dmr", "Digital voice common"),
    Band("UHF business NXDN/DMR (hint)", 450.0, 470.0, "nxdn", "Business digital"),
    Band("700/800 P25 (hint)", 760.0, 870.0, "p25", "Public safety P25"),
    Band("Paging POCSAG/FLEX", 929.0, 932.0, "pocsag", "Digital paging"),
    Band("ISM 915", 902.0, 928.0, "ism", "Unlicensed / IoT"),
]


def classify_mhz(freq_mhz: float) -> dict:
    hits = [b for b in BANDS if b.start_mhz <= freq_mhz <= b.end_mhz]
    if not hits:
        return {
            "freq_mhz": freq_mhz,
            "bands": [],
            "mode_hint": "unknown",
            "label": "Unknown / outside loaded band plan",
        }
    primary = hits[0]
    return {
        "freq_mhz": freq_mhz,
        "bands": [asdict(b) for b in hits],
        "mode_hint": primary.mode_hint,
        "label": primary.name,
    }


def list_bands() -> list[dict]:
    return [asdict(b) for b in BANDS]