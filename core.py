"""
core.py — Paths, shell helpers, folder scanning, base-lock tracking.

Do NOT put UI code here. This is pure plumbing.
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path


# ----------------------------------------------------------------------------
# Path helpers
# ----------------------------------------------------------------------------
def _clean(p) -> Path:
    return Path(str(p).replace("\x00", "")).resolve()


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return _clean(Path(sys.executable).parent)
    return _clean(Path(__file__).parent)


# ----------------------------------------------------------------------------
# Path constants
# ----------------------------------------------------------------------------
BASE_DIR      = base_dir()
TOOLS_DIR     = BASE_DIR / "tools"
IMAGE0_DIR    = TOOLS_DIR / "image0"
BASE_PKGS_DIR = BASE_DIR / "base_pkgs"
OFFICIAL_DIR  = BASE_DIR / "official_pkgs"
OVERRIDES_DIR = BASE_DIR / "overrides"
DLC_DIR       = BASE_DIR / "game_dlc"
OUTPUT_DIR    = BASE_DIR / "output_pkgs"
SCHEMA_FILE   = BASE_DIR / "emulator_options.json"
LOCK_FILE     = IMAGE0_DIR / ".base_lock"

ORBIS         = TOOLS_DIR / "orbis-pub-cmd-keystone.exe"
ORBIS_PLAIN   = TOOLS_DIR / "orbis-pub-cmd.exe"
GENGP4        = TOOLS_DIR / "gengp4-patched.exe"
FART          = TOOLS_DIR / "fart.exe"
SFO           = TOOLS_DIR / "sfo.exe"
MAGICK        = TOOLS_DIR / "magick.exe"
SEVENZ        = TOOLS_DIR / "7z.exe"
PSPDECRYPT    = TOOLS_DIR / "pspdecrypt.exe"
MKISOFS       = TOOLS_DIR / "mkisofs.exe"
ISOINFO       = TOOLS_DIR / "cdrtools" / "isoinfo.exe"
AWK_NL        = TOOLS_DIR / "awk" / "nl.exe"
AWK           = TOOLS_DIR / "awk" / "awk.exe"
SFOINFO       = TOOLS_DIR / "SFOInfo.exe"


# ----------------------------------------------------------------------------
# Folder READMEs
# ----------------------------------------------------------------------------
FOLDER_READMES = {
    BASE_PKGS_DIR: (
        "base_pkgs/\n==========\n\n"
        "Put your BASE emulator PKGs here.\n"
        "Any *.pkg file you drop in will appear in the GUI list.\n"
    ),
    OFFICIAL_DIR: (
        "official_pkgs/\n==============\n\n"
        "Put big untouched OFFICIAL PKGs here.\n"
        "Only the EBOOT.BIN is extracted from these.\n"
    ),
    OVERRIDES_DIR: (
        "overrides/\n==========\n\n"
        "OPTIONAL. Files here OVERWRITE the extracted base PKG inside\n"
        "tools/image0/ before building.\n"
    ),
    DLC_DIR: (
        "game_dlc/\n=========\n\n"
        "OPTIONAL. Drop DLC folders here named after the game's TITLE_ID.\n"
    ),
    OUTPUT_DIR: (
        "output_pkgs/\n============\n\n"
        "Finished .pkg files appear here.\n"
    ),
}


def ensure_folders():
    for d, readme in FOLDER_READMES.items():
        d.mkdir(parents=True, exist_ok=True)
        r = d / "README.txt"
        if not r.exists():
            r.write_text(readme, encoding="utf-8")


def migrate_old_folders(log=None):
    migrations = [
        (BASE_DIR / "pkgemulatorhere", BASE_PKGS_DIR),
        (BASE_DIR / "putemulatorhere", OVERRIDES_DIR),
        (BASE_DIR / "putgamedlchere",  DLC_DIR),
        (BASE_DIR / "pkg",             OUTPUT_DIR),
    ]
    for old, new in migrations:
        if old.exists() and old.is_dir():
            new.mkdir(parents=True, exist_ok=True)
            for item in old.iterdir():
                target = new / item.name
                try:
                    if not target.exists():
                        shutil.move(str(item), str(target))
                        if log:
                            log(f"[migrate] {item.name} -> {new.name}/")
                except Exception as e:
                    if log:
                        log(f"[migrate] failed {item}: {e}")
            try:
                old.rmdir()
            except Exception:
                pass


# ----------------------------------------------------------------------------
# Shell helpers — all silent by default
# ----------------------------------------------------------------------------
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
CREATE_NO_WINDOW = _NO_WINDOW


def run_cmd(cmd, cwd=None):
    """Run silently, capture output."""
    try:
        r = subprocess.run(
            cmd, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=_NO_WINDOW)
        return r.returncode, r.stdout.decode(errors="ignore")
    except Exception as e:
        return -1, str(e)


def run_silent(cmd, cwd=None):
    """Run silently, discard output."""
    try:
        return subprocess.run(
            cmd, cwd=cwd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW).returncode
    except Exception:
        return -1


def popen_silent(cmd, **kwargs):
    """Popen with hidden window."""
    return subprocess.Popen(cmd, creationflags=_NO_WINDOW, **kwargs)


# ----------------------------------------------------------------------------
# Misc helpers
# ----------------------------------------------------------------------------
def rmtree(p):
    """Aggressive removal. Falls back to Windows rd if shutil fails."""
    p = Path(p)
    if not p.exists():
        return
    try:
        shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass
    if p.exists():
        try:
            subprocess.run(
                ["cmd", "/c", "rd", "/s", "/q", str(p)],
                creationflags=_NO_WINDOW)
        except Exception:
            pass


def safe_name(s: str) -> str:
    return "".join(c for c in s if c not in r'<>:"/\|?*').strip()


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def scan_base_pkgs():
    out = []
    for src, folder in [("base_pkgs", BASE_PKGS_DIR),
                        ("official",  OFFICIAL_DIR)]:
        folder.mkdir(parents=True, exist_ok=True)
        for pkg in sorted(folder.glob("*.pkg")):
            try:
                size = pkg.stat().st_size
            except Exception:
                size = 0
            out.append({"source": src, "name": pkg.stem,
                        "path": pkg, "size": size,
                        "size_h": human_size(size)})
    return out


# ----------------------------------------------------------------------------
# Base lock tracking
# ----------------------------------------------------------------------------
def current_extracted_base() -> str:
    if not LOCK_FILE.exists():
        return ""
    try:
        return LOCK_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def write_lock(base_name: str):
    try:
        IMAGE0_DIR.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(base_name, encoding="utf-8")
    except Exception:
        pass


def image0_looks_valid() -> bool:
    return (IMAGE0_DIR / "sce_sys" / "param.sfo").exists()


# ----------------------------------------------------------------------------
# Debug
# ----------------------------------------------------------------------------
def debug_path(name: str, p, log):
    """Log repr of a path and report control-char indexes."""
    s = str(p)
    log(f"[debug] {name}: {repr(s)}")
    bad = [i for i, ch in enumerate(s) if ord(ch) < 32]
    if bad:
        for i in bad:
            log(f"[debug]   !! ctrl char at idx {i}: {hex(ord(s[i]))}")
