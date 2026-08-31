"""Guards for the install scripts.

These break only on Linux, which CI cannot exercise directly (no SDR hardware,
no root, and installing packages in the runner is not the point), so the checks
here are static: line endings, referenced files, and the placeholders the
installer substitutes with sed.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"

SHELL_FILES = [
    "install.sh",
    "run.sh",
    "scripts/pi-spy-rf.openrc",
    "scripts/pi-spy-rf.service",
    "scripts/60-pi-spy-rf-sdr.rules",
    "scripts/usbip-attach.sh",
    "scripts/usbip-detach.sh",
    "scripts/pi-spy-rf-usbip.service",
]


@pytest.mark.parametrize("name", SHELL_FILES)
def test_unix_line_endings(name):
    """A CR in a shebang line makes Linux report 'bad interpreter'."""
    raw = (ROOT / name).read_bytes()
    assert b"\r\n" not in raw, f"{name} has CRLF line endings"


@pytest.mark.parametrize(
    "name",
    [
        "install.sh",
        "run.sh",
        "scripts/pi-spy-rf.openrc",
        "scripts/usbip-attach.sh",
        "scripts/usbip-detach.sh",
    ],
)
def test_has_shebang(name):
    assert (ROOT / name).read_bytes().startswith(b"#!"), f"{name} lacks a shebang"


def test_usbip_unit_runs_the_shipped_scripts():
    """The unit calls the scripts by path; a rename would break it silently."""
    unit = (ROOT / "scripts/pi-spy-rf-usbip.service").read_text(encoding="utf-8")
    for action, script in (("ExecStart", "usbip-attach.sh"), ("ExecStop", "usbip-detach.sh")):
        assert f"{action}=" in unit, f"the unit has no {action}"
        assert script in unit, f"{action} no longer points at {script}"
        assert (ROOT / "scripts" / script).exists(), f"scripts/{script} is missing"


def test_referenced_script_files_exist():
    """install.sh builds paths as $INSTALL_DIR/scripts/... - catch renames."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    for rel in re.findall(r"\$INSTALL_DIR/(scripts/[\w.\-]+)", text):
        assert (ROOT / rel).exists(), f"install.sh references missing {rel}"


def test_every_detected_package_manager_has_an_install_branch():
    """Adding a manager to the detect loop without a case would silently no-op."""
    text = INSTALL_SH.read_text(encoding="utf-8")

    loop = re.search(r"for pm in ([^;]+); do", text)
    assert loop, "could not find the package manager detection loop"
    managers = loop.group(1).split()

    body = text.split("install_system_packages()", 1)[1]
    branches = set(re.findall(r"^\s{4}([\w|\-]+)\)", body, re.MULTILINE))
    handled = {alt for branch in branches for alt in branch.split("|")}

    missing = [m for m in managers if m not in handled]
    assert not missing, f"no install branch for {missing}"


def test_optional_installer_handles_every_manager():
    """install_optional must cover each manager or packages are skipped silently."""
    text = INSTALL_SH.read_text(encoding="utf-8")

    loop = re.search(r"for pm in ([^;]+); do", text)
    managers = loop.group(1).split()

    body = text.split("install_optional()", 1)[1].split("install_system_packages()", 1)[0]
    handled = {
        alt
        for branch in re.findall(r"^\s+([\w|\-]+)\)", body, re.MULTILINE)
        for alt in branch.split("|")
    }

    missing = [m for m in managers if m not in handled]
    assert not missing, f"install_optional does not handle {missing}"


@pytest.mark.parametrize(
    ("name", "placeholder"),
    [
        ("scripts/pi-spy-rf.service", "User=pi"),
        ("scripts/pi-spy-rf.service", "/home/pi/Pi-Spy-RF"),
        ("scripts/pi-spy-rf.openrc", "pi:pi"),
        ("scripts/pi-spy-rf.openrc", "/home/pi/Pi-Spy-RF"),
        ("scripts/60-pi-spy-rf-sdr.rules", 'GROUP="plugdev"'),
    ],
)
def test_sed_placeholders_present(name, placeholder):
    """install.sh rewrites these with sed; if they move, it fails silently."""
    assert placeholder in (ROOT / name).read_text(encoding="utf-8"), (
        f"{name} no longer contains {placeholder!r}, which install.sh substitutes"
    )
