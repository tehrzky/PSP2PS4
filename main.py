"""
main.py — PSP 2 PS4 AIO GUI.

Contains:
  - the main window (PSP2PS4App)
  - GamePage / ManualPage layouts
  - the build pipeline (extract, patch, decrypt, build)
"""
import os
import json
import time
import shutil
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

import core as C
from ui_theme import (F, ghost, Card, PkgList, SchemaForm,
                      BG, SIDEBAR, SURFACE, SURFACE_2, SURFACE_3,
                      BORDER, BORDER_LT, ACCENT, ACCENT_HI, ACCENT_ON,
                      SELECT, TEXT, TEXT_DIM, TEXT_FAINT,
                      SUCCESS, WARN, DANGER, RADIUS, RADIUS_SM, FONT_MONO)


# ============================================================================
# Schema loader
# ============================================================================
def load_schema() -> dict:
    if C.SCHEMA_FILE.exists():
        try:
            return json.loads(C.SCHEMA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "texcachemode": {
            "label": "Texture cache mode",
            "description": "Controls how the emulator handles the PSP texture cache.",
            "type": "choice",
            "placeholder": "#--texcachemode=",
            "default": "skip",
            "choices": [
                {"value": "skip", "label": "skip (recommended)"},
                {"value": "drawbounds", "label": "drawbounds"},
                {"value": "drawboundsloco", "label": "drawboundsloco"},
                {"value": "locoroco2", "label": "locoroco2"},
                {"value": "patchworkheroes", "label": "patchworkheroes"},
                {"value": "rondo", "label": "rondo"},
            ],
        },
        "region-dir": {
            "label": "Region data directory",
            "description": "Path on the PS4 where the emulator looks for game ISOs.",
            "type": "text",
            "placeholder": "#--region-dir=",
            "default": "/data/PS4ROMS/PSPISO/SIEA",
        },
    }


# ============================================================================
# Build pipeline — pure logic, call from worker threads
# ============================================================================
def _cleanup_sce(target: Path):
    for pat in ("*.json", "*.sig", "*.dds", "*.dat", "*.info",
                "*.sha", "*.xml", "*.png"):
        for f in target.glob(pat):
            f.unlink(missing_ok=True)
    for f in C.IMAGE0_DIR.glob("*.plt"):
        f.unlink(missing_ok=True)
    siea = C.IMAGE0_DIR / "SIEA"
    if siea.exists():
        for pat in ("*.lua", "*.txt", "*.json"):
            for f in siea.glob(pat):
                f.unlink(missing_ok=True)
        scr = siea / "scripts"
        if scr.exists():
            for f in scr.glob("*.lua"):
                f.unlink(missing_ok=True)
        C.rmtree(siea / "data")
    for sub in ("about", "app", "changeinfo", "trophy"):
        C.rmtree(target / sub)


def extract_base(pkg: Path, log) -> bool:
    log(f"--- Extracting base: {pkg.stem} ---")
    C.debug_path("pkg", pkg, log)

    C.rmtree(C.IMAGE0_DIR)
    C.IMAGE0_DIR.mkdir(parents=True, exist_ok=True)

    rc = C.run_silent([str(C.ORBIS), "img_extract",
                       "--passcode", "00000000000000000000000000000000",
                       str(pkg), str(C.TOOLS_DIR)])
    if rc != 0:
        log(f"❌ img_extract failed (rc={rc})")
        return False

    sc0 = C.TOOLS_DIR / "Sc0"
    sce = C.TOOLS_DIR / "sce_sys"
    if sc0.exists() and not sce.exists():
        sc0.rename(sce)
    if sce.exists():
        dest = C.IMAGE0_DIR / "sce_sys"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(sce, dest, dirs_exist_ok=True)
        C.rmtree(sce)

    _cleanup_sce(C.IMAGE0_DIR / "sce_sys")

    tmpl = C.TOOLS_DIR / "perm" / "config-title.txt"
    if tmpl.exists():
        shutil.copy2(tmpl, C.IMAGE0_DIR / "config-title.txt")

    for d in list(C.IMAGE0_DIR.iterdir()):
        if d.is_dir() and "#v1.00" in d.name:
            log(f"  removing stale: {d.name}")
            C.rmtree(d)

    C.write_lock(pkg.stem)
    log(f"✅ Base extracted: {pkg.stem}")
    return True


def ensure_base_extracted(base_pkg: Path, log) -> bool:
    name = base_pkg.stem
    if C.image0_looks_valid() and C.current_extracted_base() == name:
        log(f"[build] base already extracted: {name}")
        return True
    return extract_base(base_pkg, log)


def read_iso_sfo(iso: Path, log):
    info = C.TOOLS_DIR / "info_temp"
    log(f"[debug] info: {repr(str(info))}")
    log(f"[debug] iso : {repr(str(iso))}")
    C.rmtree(info)
    try:
        (info / "PSP_GAME").mkdir(parents=True, exist_ok=True)
    except ValueError as e:
        log(f"❌ Cannot create {info}: {e}")
        log(f"❌ Delete '{info}' in Explorer and retry.")
        return "", ""

    C.run_cmd([str(C.SEVENZ), "e", str(iso),
               f"-o{info / 'PSP_GAME'}", "PSP_GAME/param.sfo", "-aoa"])
    sfo = info / "PSP_GAME" / "param.sfo"
    txt = info / "PSP_GAME" / "param.txt"
    if not sfo.exists():
        log("❌ param.sfo not found in ISO")
        return "", ""

    C.run_cmd([str(C.SFOINFO), "i", str(sfo), str(txt)])
    disc, name = "", ""
    for line in txt.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("DISC_ID"):
            disc = line.split(":", 1)[1].strip()
        elif line.startswith("TITLE"):
            name = line.split(":", 1)[1].strip()
    return disc, name


def patch_sfo(disc_id: str, title: str, log):
    content_id = f"UP9000-{disc_id}_00-PSPX{disc_id[-5:]}TEHRZKY"
    sfo = C.IMAGE0_DIR / "sce_sys" / "param.sfo"
    for k, v in [("VERSION", "01.00"),
                 ("CONTENT_ID", content_id),
                 ("TITLE_ID", disc_id),
                 ("TITLE", title)]:
        C.run_cmd([str(C.SFO), "-e", k, v, str(sfo)])
    log(f"[sfo] patched: {disc_id} / {title}")


def make_game_folder(disc_id: str) -> Path:
    game_dir = C.IMAGE0_DIR / f"{disc_id}#v1.00"
    for sub in ("aot", "vms/GAME", "vms/SAVEDATA"):
        (game_dir / sub).mkdir(parents=True, exist_ok=True)
    siea = C.IMAGE0_DIR / "SIEA"
    siea.mkdir(parents=True, exist_ok=True)
    with open(siea / "config-region.txt", "a", encoding="utf-8") as f:
        f.write(f'--active-sku="{disc_id}#v1.00"\n')
    return game_dir


def merge_dlc(game_dir: Path, disc_id: str, log):
    src = C.DLC_DIR / disc_id
    if src.exists():
        shutil.copytree(src, game_dir / "vms" / "GAME" / disc_id,
                        dirs_exist_ok=True)
        log(f"  DLC merged: {disc_id}")


def decrypt_and_mkiso(iso: Path, game_dir: Path, disc_id: str, log) -> bool:
    tmp = C.TOOLS_DIR / "iso_extraction_temp"
    C.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    sort_file = C.TOOLS_DIR / "sort_file.txt"

    try:
        p1 = C.popen_silent([str(C.ISOINFO), "-f", "-i", str(iso)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
        p2 = C.popen_silent([str(C.AWK_NL), "-nln", "-s", ";"],
                            stdin=p1.stdout, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
        p1.stdout.close()
        with open(sort_file, "w", encoding="utf-8", errors="ignore") as f:
            p3 = C.popen_silent(
                [str(C.AWK), "-F", ";", '{print substr($2,2) " -" $1}'],
                stdin=p2.stdout, stdout=f, stderr=subprocess.DEVNULL)
            p2.stdout.close()
            p3.wait()
    except Exception as e:
        log(f"sort error: {e}")

    log("Extracting ISO with 7z ...")
    C.run_cmd([str(C.SEVENZ), "x", str(iso), f"-o{tmp}", "-r", "-aoa"])

    eboot = tmp / "PSP_GAME" / "SYSDIR" / "EBOOT.BIN"
    if not eboot.exists():
        log("EBOOT.BIN missing inside ISO")
        C.rmtree(tmp)
        return False

    log("Decrypting EBOOT.BIN ...")
    C.run_cmd([str(C.PSPDECRYPT), str(eboot)])
    dec = eboot.with_suffix(".BIN.DEC")
    if not dec.exists():
        log("EBOOT.BIN.DEC not produced")
        C.rmtree(tmp)
        return False
    eboot.unlink()
    dec.rename(eboot)

    out_iso = game_dir / f"{disc_id}#v1.00.IMG"
    log("mkisofs ...")
    C.run_cmd([str(C.MKISOFS), "-quiet", "-sort", str(sort_file),
               "-iso-level", "4", "-xa",
               "-A", "PSP GAME", "-V", "PSP_GAME", "-sysid", "PSP GAME",
               "-volset", "", "-p", "", "-publisher", "",
               "-o", str(out_iso), str(tmp)])
    sort_file.unlink(missing_ok=True)
    C.rmtree(tmp)
    return out_iso.exists()


def swap_method(iso: Path, game_dir: Path, disc_id: str, log):
    target = game_dir / f"{disc_id}#v1.00.IMG"
    shutil.copy2(iso, target)
    cfg = C.IMAGE0_DIR / "config-title.txt"
    if cfg.exists():
        C.run_cmd([str(C.FART), "-C", str(cfg), "#1",
                   "\\--boot=umd0:/PSP_GAME/SYSDIR/BOOT.BIN"])
    log(f"ISO copied as {target.name}")


def skip_copy(iso: Path, game_dir: Path, disc_id: str, log):
    target = game_dir / f"{disc_id}#v1.00.IMG"
    shutil.copy2(iso, target)
    log(f"Copied directly (skip): {target.name}")


def apply_schema_to_config(schema: dict, values: dict, log):
    cfg = C.IMAGE0_DIR / "config-title.txt"
    if not cfg.exists():
        return
    for key, val in values.items():
        spec = schema[key]
        ph = spec["placeholder"]
        if spec.get("type") == "choice" and val == "skip":
            if ph.startswith("#--texcachemode="):
                C.run_cmd([str(C.FART), "-i", str(cfg), ph, "--remove"])
                log("texcachemode: skip (removed)")
                continue
        C.run_cmd([str(C.FART), "-C", str(cfg), ph, f"\\{ph}{val}"])
        log(f"config {key} = {val}")


def apply_overrides(log):
    if C.OVERRIDES_DIR.exists():
        log("Copying overrides/ ...")
        shutil.copytree(C.OVERRIDES_DIR, C.IMAGE0_DIR, dirs_exist_ok=True)


def apply_custom_icons(icon_file, boot_file, log):
    sce = C.IMAGE0_DIR / "sce_sys"
    if icon_file and Path(icon_file).exists():
        C.run_cmd([str(C.MAGICK), str(icon_file), "-resize", "512x512!",
                   "-colorspace", "sRGB", "-depth", "8",
                   str(sce / "icon0.png")])
        C.run_cmd([str(C.MAGICK), str(icon_file), "-resize", "512x512!",
                   str(C.IMAGE0_DIR / "SIEA" / "regional_icon.png")])
        log("Custom icon applied.")
    if boot_file and Path(boot_file).exists():
        C.run_cmd([str(C.MAGICK), str(boot_file), "-resize", "1920x1080!",
                   str(sce / "pic1.png")])
        shutil.copy2(sce / "pic1.png", sce / "pic0.png")
        log("Custom boot image applied.")


def copy_default_icons(log):
    src = C.TOOLS_DIR / "pic"
    sce = C.IMAGE0_DIR / "sce_sys"
    if not src.exists():
        return
    for n in ("icon0.png", "pic1.png", "save_data.png"):
        s = src / n
        if s.exists():
            shutil.copy2(s, sce / n)
    log("Default icons copied.")


def finish_pkg(out_name: str, disc_id: str, title: str, log):
    log("Generating GP4 ...")
    C.run_cmd([str(C.GENGP4), str(C.IMAGE0_DIR)])

    gp4 = C.TOOLS_DIR / "image0.gp4"
    txt = C.TOOLS_DIR / "image0.txt"
    if gp4.exists():
        gp4.rename(txt)
    if txt.exists():
        C.run_cmd([str(C.FART), str(txt), "-i",
                   'default_id="1"', 'default_id="0"'])
        txt.rename(gp4)

    C.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp_pkg = C.OUTPUT_DIR / "1.pkg"
    if tmp_pkg.exists():
        tmp_pkg.unlink()

    log("orbis-pub-cmd img_create ...")
    rc = C.run_silent([str(C.ORBIS), "img_create", str(gp4), str(tmp_pkg)])
    if rc != 0 or not tmp_pkg.exists():
        log("❌ img_create failed")
        return None

    final = C.OUTPUT_DIR / out_name
    if final.exists():
        final.unlink()
    tmp_pkg.rename(final)

    size_mb = final.stat().st_size // (1024 * 1024)
    (C.OUTPUT_DIR / f"[{disc_id}] {title} ({size_mb}mb
