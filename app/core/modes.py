from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DigitalMode:
    id: str
    label: str
    family: str
    backend: str  # multimon | dsd | gnuradio | demo
    tools: tuple[str, ...]
    fields: tuple[str, ...]
    notes: str = ""


# Scanner-class digital modes. Encrypted traffic is flagged, not cracked.
MODES: tuple[DigitalMode, ...] = (
    DigitalMode("auto", "Auto", "meta", "auto", (), (), "Pick from band plan / peak hint"),
    DigitalMode("pocsag", "POCSAG", "paging", "multimon", ("multimon-ng", "rtl_fm"), ("text", "capcode"), "512/1200/2400 paging"),
    DigitalMode("flex", "FLEX", "paging", "multimon", ("multimon-ng", "rtl_fm"), ("text", "capcode"), "Motorola FLEX paging"),
    DigitalMode("eas", "EAS / SAME", "alert", "multimon", ("multimon-ng", "rtl_fm"), ("text",), "NOAA / EAS headers"),
    DigitalMode("afsk1200", "AFSK 1200", "packet", "multimon", ("multimon-ng", "rtl_fm"), ("text",), "AX.25 / APRS-ish"),
    DigitalMode("morse", "CW / Morse", "cw", "multimon", ("multimon-ng", "rtl_fm"), ("text",), "On-air CW"),
    DigitalMode("dtmf", "DTMF", "signaling", "multimon", ("multimon-ng", "rtl_fm"), ("text",), "Touch-tones"),
    DigitalMode("dmr", "DMR", "tdma", "dsd", ("dsd-fme", "dsd", "rtl_fm"), ("color_code", "timeslot", "talkgroup", "radio_id"), "TS + CC + TG"),
    DigitalMode("p25", "P25 Phase 1", "tdma", "dsd", ("dsd-fme", "dsd", "rtl_fm"), ("nac", "talkgroup", "radio_id"), "NAC / TG / RID"),
    DigitalMode("p25p2", "P25 Phase 2", "tdma", "dsd", ("dsd-fme", "op25", "rtl_fm"), ("nac", "talkgroup", "radio_id", "timeslot"), "TDMA P25"),
    DigitalMode("nxdn", "NXDN", "fdma", "dsd", ("dsd-fme", "dsd"), ("ran", "talkgroup", "radio_id"), "IDAS / NEXEDGE"),
    DigitalMode("dstar", "D-STAR", "fdma", "dsd", ("dsd-fme", "dsd"), ("callsign", "text"), "Icom amateur"),
    DigitalMode("ysf", "Yaesu System Fusion", "fdma", "dsd", ("dsd-fme", "dsd"), ("callsign", "dgid"), "C4FM / YSF"),
    DigitalMode("dpmr", "dPMR", "fdma", "dsd", ("dsd-fme", "dsd"), ("radio_id", "talkgroup"), "dPMR446 / business"),
    DigitalMode("m17", "M17", "fdma", "dsd", ("dsd-fme",), ("callsign",), "Open ham digital"),
    DigitalMode("tetra", "TETRA", "tdma", "dsd", ("telive", "osmo-tetra"), ("talkgroup", "timeslot", "color_code"), "Needs extra stack; demo metadata only unless tools exist"),
    DigitalMode("nxdn48", "NXDN 4800", "fdma", "dsd", ("dsd-fme",), ("ran", "talkgroup"), "Narrow NXDN"),
    DigitalMode("nxdn96", "NXDN 9600", "fdma", "dsd", ("dsd-fme",), ("ran", "talkgroup"), "Wide NXDN"),
)


MODE_BY_ID = {m.id: m for m in MODES}
SUPPORTED_MODES = tuple(m.id for m in MODES)

# Hint from spectrum/bandplan -> decode mode
HINT_TO_MODE = {
    "pocsag": "pocsag",
    "paging": "pocsag",
    "dmr": "dmr",
    "p25": "p25",
    "nxdn": "nxdn",
    "dstar": "dstar",
    "ysf": "ysf",
    "fusion": "ysf",
    "noaa_wx": "eas",
    "packet": "afsk1200",
    "m17": "m17",
    "tetra": "tetra",
}


def list_modes() -> list[dict]:
    return [asdict(m) for m in MODES]


def resolve_mode(mode: str, freq_mhz: float | None = None) -> str:
    mode = (mode or "auto").lower().strip()
    if mode != "auto":
        return mode if mode in MODE_BY_ID else "auto"
    if freq_mhz is None:
        return "dmr"
    if 929 <= freq_mhz <= 932:
        return "pocsag"
    if 162.4 <= freq_mhz <= 162.55:
        return "eas"
    if 144 <= freq_mhz <= 148 or 420 <= freq_mhz <= 450:
        return "dmr"
    if 760 <= freq_mhz <= 870:
        return "p25"
    return "dmr"


def hint_to_mode(mode_hint: str, freq_mhz: float) -> str | None:
    h = (mode_hint or "").lower()
    for key, mid in HINT_TO_MODE.items():
        if key in h:
            return mid
    if 929 <= freq_mhz <= 932:
        return "pocsag"
    analog = ("analog_fm", "analog_am", "noaa_apt", "marine", "ham_vhf", "ham_uhf", "unknown", "gmrs", "ism", "mil_air")
    if h in analog:
        return None
    return None
