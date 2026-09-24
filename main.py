"""
main.py — PSP 2 PS4 AIO GUI.

Compact layout:
  header → tab row → (cards | summary+terminal) → build footer
"""
import os
import json
import shutil
import subprocess
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

import core as C
from ui_theme import (F, ghost, Card, PkgList, StatRow, TerminalBox,
                      SchemaForm,
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
    return {}


# ============================================================================
# Build pipeline
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


def _strip_nulls(s: str) -> str:
    return s.replace("\x00", "").strip()


def read_iso_sfo(iso: Path, log):
    info = C.TOOLS_DIR / "info_temp"
    C.rmtree(info)
    try:
        (info / "PSP_GAME").mkdir(parents=True, exist_ok=True)
    except ValueError as e:
        log(f"❌ Cannot create {info}: {e}")
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
            disc = _strip_nulls(line.split(":", 1)[1])
        elif line.startswith("TITLE"):
            name = _strip_nulls(line.split(":", 1)[1])
    return disc, name


def patch_sfo(disc_id: str, title: str, log):
    content_id = f"UP9000-{disc_id}_00-PSPX{disc_id[-5:]}TEHRZKY"
    sfo = C.IMAGE0_DIR / "sce_sys" / "param.sfo"
    for k, v in [("VERSION", "01.00"),
                 ("CONTENT_ID", content_id),
                 ("TITLE_ID", disc_id),
                 ("TITLE", title)]:
        C.run_cmd([str(C.SFO), "-e", k, v, str(sfo)])


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

    log("Extracting ISO ...")
    C.run_cmd([str(C.SEVENZ), "x", str(iso), f"-o{tmp}", "-r", "-aoa"])

    eboot = tmp / "PSP_GAME" / "SYSDIR" / "EBOOT.BIN"
    if not eboot.exists():
        log("EBOOT.BIN missing inside ISO")
        C.rmtree(tmp)
        return False

    log("Decrypting EBOOT.BIN ...")
    C.run_cmd([str(C.PSPDECRYPT), str(eboot)])

    candidates = [
        eboot.with_suffix(".BIN.DEC"),
        eboot.parent / "EBOOT.DEC",
        eboot.parent / "EBOOT.BIN.dec",
        eboot.parent / "EBOOT.dec",
    ]
    dec = next((c for c in candidates if c.exists()), None)
    if dec is not None:
        log(f"✅ decrypted → {dec.name}")
        eboot.unlink()
        dec.rename(eboot)
    else:
        log("⚠️ no .DEC produced — assuming already decrypted")

    out_iso = game_dir / f"{disc_id}#v1.00.IMG"
    log("Building ISO ...")
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
        spec = schema.get(key)
        if not spec:
            continue
        ph = spec["placeholder"]
        if spec.get("type") == "choice" and val == "skip":
            if ph.startswith("#--texcachemode="):
                C.run_cmd([str(C.FART), "-i", str(cfg), ph, "--remove"])
                continue
        C.run_cmd([str(C.FART), "-C", str(cfg), ph, f"\\{ph}{val}"])


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
    if boot_file and Path(boot_file).exists():
        C.run_cmd([str(C.MAGICK), str(boot_file), "-resize", "1920x1080!",
                   str(sce / "pic1.png")])
        shutil.copy2(sce / "pic1.png", sce / "pic0.png")


def copy_default_icons(log):
    src = C.TOOLS_DIR / "pic"
    sce = C.IMAGE0_DIR / "sce_sys"
    if not src.exists():
        return
    for n in ("icon0.png", "pic1.png", "save_data.png"):
        s = src / n
        if s.exists():
            shutil.copy2(s, sce / n)


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

    log("Building PKG ...")
    rc = C.run_silent([str(C.ORBIS), "img_create", str(gp4), str(tmp_pkg)])
    if rc != 0 or not tmp_pkg.exists():
        log("❌ img_create failed")
        return None

    final = C.OUTPUT_DIR / out_name
    if final.exists():
        final.unlink()
    tmp_pkg.rename(final)

    size_mb = final.stat().st_size // (1024 * 1024)
    (C.OUTPUT_DIR / f"[{disc_id}] {title} ({size_mb}mb).txt")\
        .write_text("", encoding="utf-8")
    try:
        gp4.unlink()
    except Exception:
        pass

    log(f"✅ PKG created: {final.name}  ({size_mb} MB)")
    return final


# ============================================================================
# GamePage — cards left, summary+terminal right
# ============================================================================
class GamePage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, corner_radius=0, fg_color=BG)
        self.app = app
        self.schema = app.schema

        self.base_pkg_path = None
        self.base_pkg_name = ""

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0, minsize=310)

        self._build()

    def _build(self):
        # LEFT: cards
        left = ctk.CTkScrollableFrame(
            self, corner_radius=0, fg_color=BG,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_LT)
        left.grid(row=0, column=0, sticky="nsew",
                  padx=(14, 6), pady=(6, 10))
        left.grid_columnconfigure(0, weight=1)

        # Card 1
        c1 = Card(left, "1", "Base PKG", "emulator base")
        c1.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar = ctk.CTkFrame(c1.body, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 6))
        ghost(toolbar, "📂 base_pkgs/",
              lambda: self.app.open_folder(C.BASE_PKGS_DIR), width=118)\
            .pack(side="left", padx=(0, 4))
        ghost(toolbar, "📂 official_pkgs/",
              lambda: self.app.open_folder(C.OFFICIAL_DIR), width=132)\
            .pack(side="left", padx=(0, 4))
        ctk.CTkButton(toolbar, text="↻ Rescan", width=84, height=28,
                      corner_radius=RADIUS_SM, font=F(11),
                      fg_color=SURFACE_3, hover_color=BORDER_LT,
                      text_color=TEXT,
                      command=self.app.rescan_pkgs).pack(side="right")

        self.pkg_list = PkgList(c1.body, on_select=self._on_pkg_select,
                                height=170)
        self.pkg_list.pack(fill="x", pady=(0, 6))

        btn_row = ctk.CTkFrame(c1.body, fg_color="transparent")
        btn_row.pack(fill="x")
        ghost(btn_row, "🔍 Preview base", self.app.preview_base, width=126)\
            .pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="⬇  Extract Base PKG",
                      width=154, height=30, corner_radius=RADIUS_SM,
                      font=F(11, "bold"),
                      fg_color=SELECT, hover_color=BORDER_LT,
                      text_color=ACCENT_HI,
                      command=self.app.force_extract_base)\
            .pack(side="left")

        # Card 2
        c2 = Card(left, "2", "Overrides", "optional")
        c2.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.use_overrides = tk.BooleanVar(value=False)
        row2 = ctk.CTkFrame(c2.body, fg_color="transparent")
        row2.pack(fill="x")
        ctk.CTkCheckBox(row2,
                        text="Copy files from overrides/ into the base",
                        variable=self.use_overrides, font=F(11),
                        fg_color=ACCENT, hover_color=ACCENT_HI,
                        checkbox_width=18, checkbox_height=18)\
            .pack(side="left")
        ghost(row2, "📂 Open",
              lambda: self.app.open_folder(C.OVERRIDES_DIR), width=76)\
            .pack(side="right")

        # Card 3
        self.c3 = Card(left, "3", "Game ISO")
        self.c3.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.iso_label = ctk.CTkLabel(self.c3.body, text="No ISO selected",
                                      font=F(11), text_color=DANGER,
                                      anchor="w")
        self.iso_label.pack(anchor="w", pady=(0, 6))
        row3 = ctk.CTkFrame(self.c3.body, fg_color="transparent")
        row3.pack(fill="x")
        ctk.CTkButton(row3, text="Browse ISO…", width=124, height=30,
                      corner_radius=RADIUS_SM, font=F(11, "bold"),
                      fg_color=SURFACE_3, hover_color=BORDER_LT,
                      text_color=TEXT, command=self.app.pick_iso)\
            .pack(side="left")
        ghost(row3, "📂 game_dlc/",
              lambda: self.app.open_folder(C.DLC_DIR), width=118)\
            .pack(side="right")
        self.output_preview = ctk.CTkLabel(self.c3.body, text="",
                                           font=F(10, family=FONT_MONO),
                                           text_color=SUCCESS, anchor="w")
        self.output_preview.pack(anchor="w", pady=(6, 0))

        # Card 4
        self.c4 = Card(left, "4", "Decrypt Method")
        self.c4.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.decrypt_var = tk.IntVar(value=1)
        for txt, val in (
            ("Decrypt & rebuild ISO — safest", 1),
            ("Swap EBOOT — fallback if decrypt fails", 2),
            ("Skip — assume already decrypted (fast)", 3),
        ):
            ctk.CTkRadioButton(self.c4.body, text=txt,
                               variable=self.decrypt_var, value=val,
                               font=F(11), fg_color=ACCENT,
                               hover_color=ACCENT_HI,
                               radiobutton_width=16, radiobutton_height=16)\
                .pack(anchor="w", pady=2)

        # Card 5
        self.c5 = Card(left, "5", "Emulator Options", "from JSON")
        self.c5.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self.schema_form = SchemaForm(self.c5.body, self.schema)

        # Card 6
        self.c6 = Card(left, "6", "Icon / Background", "optional")
        self.c6.grid(row=5, column=0, sticky="ew")
        self.icon_var = tk.IntVar(value=2)
        ctk.CTkRadioButton(self.c6.body, text="Use default icons",
                           variable=self.icon_var, value=2, font=F(11),
                           fg_color=ACCENT, hover_color=ACCENT_HI,
                           radiobutton_width=16, radiobutton_height=16)\
            .pack(anchor="w", pady=2)
        ctk.CTkLabel(self.c6.body,
                     text="tools/pic/icon0.png · pic1.png · save_data.png",
                     font=F(9), text_color=TEXT_FAINT, anchor="w")\
            .pack(anchor="w", padx=22)
        ctk.CTkRadioButton(self.c6.body, text="Set custom",
                           variable=self.icon_var, value=1, font=F(11),
                           fg_color=ACCENT, hover_color=ACCENT_HI,
                           radiobutton_width=16, radiobutton_height=16)\
            .pack(anchor="w", pady=(6, 2))

        row6 = ctk.CTkFrame(self.c6.body, fg_color="transparent")
        row6.pack(fill="x", padx=22, pady=2)
        ctk.CTkButton(row6, text="Icon…", width=72, height=26,
                      corner_radius=RADIUS_SM, font=F(10),
                      fg_color=SURFACE_3, hover_color=BORDER_LT,
                      text_color=TEXT, command=self.app.pick_icon)\
            .pack(side="left", padx=(0, 6))
        ctk.CTkButton(row6, text="Boot image…", width=110, height=26,
                      corner_radius=RADIUS_SM, font=F(10),
                      fg_color=SURFACE_3, hover_color=BORDER_LT,
                      text_color=TEXT, command=self.app.pick_boot)\
            .pack(side="left")

        # ---------- RIGHT: summary + terminal ----------
        right = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=RADIUS,
                             border_width=1, border_color=BORDER,
                             width=310)
        right.grid(row=0, column=1, sticky="nsew",
                   padx=(6, 14), pady=(6, 10))
        right.grid_propagate(False)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="BUILD SUMMARY", font=F(9, "bold"),
                     text_color=TEXT_FAINT, anchor="w")\
            .grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))

        # stat rows — aligned labels
        stats = ctk.CTkFrame(right, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", padx=14)
        stats.grid_columnconfigure(0, weight=1)

        self.stat_status = StatRow(stats, "Status", "● Not extracted")
        self.stat_status.grid(row=0, column=0, sticky="ew", pady=2)
        self.stat_base = StatRow(stats, "Base", "—")
        self.stat_base.grid(row=1, column=0, sticky="ew", pady=2)
        self.stat_iso = StatRow(stats, "ISO", "—")
        self.stat_iso.grid(row=2, column=0, sticky="ew", pady=2)
        self.stat_out = StatRow(stats, "Output", "—")
        self.stat_out.grid(row=3, column=0, sticky="ew", pady=2)

        # progress
        prog_wrap = ctk.CTkFrame(right, fg_color="transparent")
        prog_wrap.grid(row=2, column=0, sticky="ew", padx=14, pady=(12, 0))
        prog_wrap.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(prog_wrap, height=6,
                                           progress_color=ACCENT,
                                           fg_color=SURFACE_3,
                                           corner_radius=4)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress.set(0)

        self.phase_label = ctk.CTkLabel(prog_wrap, text="Idle",
                                        font=F(10), text_color=TEXT_DIM,
                                        anchor="w")
        self.phase_label.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        # terminal
        self.terminal = TerminalBox(right, height=100)
        self.terminal.grid(row=3, column=0, sticky="ew",
                           padx=14, pady=(12, 0))

        # quick open
        ctk.CTkLabel(right, text="QUICK OPEN", font=F(9, "bold"),
                     text_color=TEXT_FAINT, anchor="w")\
            .grid(row=4, column=0, sticky="ew", padx=14, pady=(12, 6))

        qb = ctk.CTkFrame(right, fg_color="transparent")
        qb.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 12))
        qb.grid_columnconfigure((0, 1), weight=1)
        quick = [("📦 output", C.OUTPUT_DIR),
                 ("🧱 base_pkgs", C.BASE_PKGS_DIR),
                 ("🏛 official", C.OFFICIAL_DIR),
                 ("🔧 overrides", C.OVERRIDES_DIR),
                 ("🎴 game_dlc", C.DLC_DIR),
                 ("🗂 image0", C.IMAGE0_DIR)]
        for i, (label, path) in enumerate(quick):
            ghost(qb, label,
                  lambda p=path: self.app.open_folder(p), height=28)\
                .grid(row=i // 2, column=i % 2, sticky="ew",
                      padx=(0, 4) if i % 2 == 0 else (4, 0), pady=2)

    # public
    def set_items(self, items):
        self.pkg_list.set_items(items)

    def _on_pkg_select(self, item):
        self.base_pkg_path = item["path"]
        self.base_pkg_name = item["name"]
        self.stat_base.set(item["name"])
        self.app._update_output_preview()

    def set_output_preview(self, txt):
        self.output_preview.configure(text=f"→ {txt}")
        self.stat_out.set(txt)

    def set_status(self, text: str, color=None):
        self.stat_status.set(text, color)

    def set_base_ready(self, name: str):
        self.set_status(f"● Ready — {name}", SUCCESS)

    def set_building(self, active: bool):
        self.app.set_build_state(active)


# ============================================================================
# ManualPage
# ============================================================================
class ManualPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, corner_radius=0, fg_color=BG)
        self.app = app

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 6))
        ctk.CTkLabel(toolbar, text="Manual PKG Builder",
                     font=F(16, "bold")).pack(side="left")
        ctk.CTkLabel(toolbar,
                     text="Advanced — put anything in tools/image0/, then build.",
                     font=F(10), text_color=TEXT_DIM)\
            .pack(side="left", padx=(10, 0), pady=(4, 0))
        ghost(toolbar, "📂 Open tools/image0/",
              lambda: self.app.open_folder(C.IMAGE0_DIR),
              width=156, height=32).pack(side="right", padx=4)
        ctk.CTkButton(toolbar, text="🚀  Build manual.pkg",
                      width=178, height=32,
                      corner_radius=RADIUS_SM, font=F(11, "bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HI,
                      text_color=ACCENT_ON,
                      command=self.app.do_manual_build)\
            .pack(side="right")

        self.manual_log = ctk.CTkTextbox(self, wrap="word",
                                         font=F(11, family=FONT_MONO),
                                         fg_color=SIDEBAR,
                                         text_color="#b9c8b9",
                                         corner_radius=RADIUS)
        self.manual_log.grid(row=1, column=0, sticky="nsew",
                             padx=16, pady=(0, 12))
        self.manual_log.configure(state="disabled")


# ============================================================================
# Main app
# ============================================================================
class PSP2PS4App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PSP 2 PS4 AIO")
        self.configure(fg_color=BG)
        C.ensure_folders()

        self.iso_file = None
        self.icon_file = None
        self.boot_file = None
        self.detected_disc_id = ""
        self.detected_title = ""
        self.schema = load_schema()

        self._build_ui()
        self._apply_window_size()

        self.log(f"[init] {C.BASE_DIR}")
        C.migrate_old_folders(log=self.log)
        self.rescan_pkgs()

        lock = C.current_extracted_base()
        if lock:
            self.pages["game"].set_base_ready(lock)

    # ---------------------------------------------------------- UI
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)   # pages
        self.grid_rowconfigure(3, weight=0)   # build bar

        self._build_header()
        self._build_tabs()

        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color=BG)
        self.content.grid(row=2, column=0, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.pages = {
            "game": GamePage(self.content, self),
            "manual": ManualPage(self.content, self),
        }
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")
        self.show_page("game")

        self._build_build_bar()

    def _build_header(self):
        hdr = ctk.CTkFrame(self, corner_radius=0, fg_color=BG, height=56)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(1, weight=1)

        # logo
        logo_wrap = ctk.CTkFrame(hdr, fg_color="transparent")
        logo_wrap.grid(row=0, column=0, sticky="w", padx=(16, 10), pady=10)
        ctk.CTkLabel(logo_wrap, text="P₂₄", font=F(14, "bold"),
                     text_color=ACCENT_ON, fg_color=ACCENT,
                     corner_radius=8, width=34, height=34).pack(side="left")
        ttl = ctk.CTkFrame(logo_wrap, fg_color="transparent")
        ttl.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(ttl, text="PSP 2 PS4 AIO",
                     font=F(14, "bold"), anchor="w").pack(anchor="w")
        ctk.CTkLabel(ttl, text="BUILDER  ·  v2.8",
                     font=F(9), text_color=TEXT_FAINT, anchor="w")\
            .pack(anchor="w")

        # right: framework link
        ghost(hdr, "⬇  Framework 5.0",
              self.open_framework, width=150, height=30)\
            .grid(row=0, column=2, sticky="e", padx=(0, 16), pady=13)

    def _build_tabs(self):
        row = ctk.CTkFrame(self, fg_color="transparent", height=44)
        row.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 6))
        row.grid_propagate(False)

        # left: page tabs
        self.page_var = tk.StringVar(value="Build PKG")
        ctk.CTkSegmentedButton(
            row,
            values=["Build PKG", "Manual Builder"],
            variable=self.page_var,
            command=self._on_page_tab,
            height=34, corner_radius=RADIUS_SM,
            fg_color=SURFACE_2,
            selected_color=SELECT, selected_hover_color=SELECT,
            unselected_color=SURFACE_2, unselected_hover_color=SURFACE_3,
            text_color=TEXT, font=F(11))\
            .pack(side="left")

        # middle-right: mode toggle (only relevant on build page)
        self.mode_row = ctk.CTkFrame(row, fg_color="transparent")
        self.mode_row.pack(side="left", padx=(16, 0))
        self.mode_var = tk.StringVar(value="Game PKG")
        self.mode_seg = ctk.CTkSegmentedButton(
            self.mode_row,
            values=["Game PKG", "Emulator PKG"],
            variable=self.mode_var,
            command=lambda v: self._on_mode_change(),
            height=34, corner_radius=RADIUS_SM,
            fg_color=SURFACE_2,
            selected_color=SELECT, selected_hover_color=SELECT,
            unselected_color=SURFACE_2, unselected_hover_color=SURFACE_3,
            text_color=TEXT, font=F(11))
        self.mode_seg.pack(side="left")

        # right: cleanup
        ghost(row, "🧹 Cleanup", self.cleanup_workdir,
              width=100, height=30)\
            .pack(side="right")

    def _on_page_tab(self, value):
        if value == "Build PKG":
            self.show_page("game")
            self.mode_row.pack(side="left", padx=(16, 0))
        else:
            self.show_page("manual")
            self.mode_row.pack_forget()

    def _build_build_bar(self):
        bar = ctk.CTkFrame(self, fg_color=SURFACE,
                           corner_radius=0, height=74)     # was 58
        bar.grid(row=3, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)

        out_wrap = ctk.CTkFrame(bar, fg_color="transparent")
        out_wrap.grid(row=0, column=0, sticky="ew",
                      padx=(16, 10), pady=16)              # was 10
        ctk.CTkLabel(out_wrap, text="OUTPUT", font=F(9, "bold"),
                     text_color=TEXT_FAINT).pack(anchor="w")
        self.output_preview_bar = ctk.CTkLabel(
            out_wrap, text="—", font=F(11, family=FONT_MONO),
            text_color=TEXT_DIM, anchor="w")
        self.output_preview_bar.pack(anchor="w")

        ghost(bar, "📂  Open output",
              lambda: self.open_folder(C.OUTPUT_DIR),
              width=126, height=38)\
            .grid(row=0, column=1, padx=(0, 8), pady=18)   # was 10

        self.build_btn = ctk.CTkButton(
            bar, text="🚀   BUILD PKG", height=38, width=200,
            font=F(13, "bold"), corner_radius=10,
            fg_color=ACCENT, hover_color=ACCENT_HI, text_color=ACCENT_ON,
            command=self.do_build)
        self.build_btn.grid(row=0, column=2, padx=(0, 20), pady=18)

    def _apply_window_size(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        win_w = max(1060, min(1240, sw - 120))
        win_h = max(680, min(820, sh - 140))
        x = max(0, (sw - win_w) // 2)
        y = max(0, (sh - win_h) // 2 - 30)
        self.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.minsize(1060, 680)

    def show_page(self, name):
        for k, p in self.pages.items():
            if k != name:
                p.grid_remove()
        self.pages[name].grid()

    # ---------------------------------------------------------- logging
    def log(self, msg):
        self.after(0, lambda m=msg: self._log_main(m))

    def _log_main(self, msg):
        try:
            gp = self.pages.get("game")
            if gp is None:
                return
            tag = None
            if msg.startswith("✅"):
                tag = "ok"
            elif msg.startswith("❌"):
                tag = "err"
            elif msg.startswith("⚠️"):
                tag = "warn"
            elif msg.startswith("---"):
                tag = "phase"
            elif msg.startswith("["):
                tag = "dim"
            gp.terminal.write(msg, tag)
        except Exception:
            pass

    # ---------------------------------------------------------- progress
    def set_progress(self, pct: int, label: str = ""):
        self.after(0, lambda: self._set_progress(pct, label))

    def _set_progress(self, pct, label):
        try:
            gp = self.pages["game"]
            gp.progress.set(pct / 100.0)
            if label:
                gp.phase_label.configure(text=label)
        except Exception:
            pass

    # ---------------------------------------------------------- build state
    def set_build_state(self, active: bool, phase: str = ""):
        def apply():
            try:
                if active:
                    txt = "⏳  BUILDING…" + (f"  {phase}" if phase else "")
                    self.build_btn.configure(
                        text=txt, state="disabled",
                        fg_color=SURFACE_3, text_color=TEXT_DIM)
                else:
                    mode = self.pages["game"].mode_var.get() \
                        if "game" in self.pages else "Game PKG"
                    txt = ("🚀   BUILD PKG"
                           if mode == "Game PKG"
                           else "🔨   BUILD EMULATOR PKG")
                    self.build_btn.configure(
                        text=txt, state="normal",
                        fg_color=ACCENT, text_color=ACCENT_ON)
            except Exception:
                pass
        self.after(0, apply)

    # ---------------------------------------------------------- dialogs
    def ask_main(self, prompt, title="Input", integer=False,
                 minvalue=1, maxvalue=9999):
        box = {}
        done = threading.Event()

        def run():
            try:
                if integer:
                    box["v"] = simpledialog.askinteger(
                        title, prompt, minvalue=minvalue,
                        maxvalue=maxvalue)
                else:
                    box["v"] = simpledialog.askstring(title, prompt)
            finally:
                done.set()

        self.after(0, run)
        done.wait()
        return box.get("v")

    def msg_main(self, kind, title, message):
        box = {}
        done = threading.Event()

        def run():
            try:
                if kind == "info":
                    messagebox.showinfo(title, message)
                elif kind == "error":
                    messagebox.showerror(title, message)
                elif kind == "warn":
                    messagebox.showwarning(title, message)
                elif kind == "yesno":
                    box["v"] = messagebox.askyesno(title, message)
            finally:
                done.set()

        self.after(0, run)
        done.wait()
        return box.get("v")

    # ---------------------------------------------------------- UI ops
    def open_folder(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def open_framework(self):
        if messagebox.askyesno(
                "Framework 5.0",
                "Open the .NET 5.0 download page?"):
            os.startfile(
                "https://dotnet.microsoft.com/en-us/download/dotnet/5.0")

    def cleanup_workdir(self):
        if not messagebox.askyesno(
                "Cleanup", "Delete tools/image0 and temp files?"):
            return
        C.rmtree(C.IMAGE0_DIR)
        for f in (C.TOOLS_DIR / "image0.gp4",
                  C.TOOLS_DIR / "image0.txt",
                  C.TOOLS_DIR / "sort_file.txt"):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
        gp = self.pages["game"]
        gp.set_status("● Not extracted", DANGER)
        gp.stat_base.set("—")
        self.set_progress(0, "Idle")
        self.log("[cleanup] tools/image0 wiped.")

    # ---------------------------------------------------------- scan
    def rescan_pkgs(self):
        items = C.scan_base_pkgs()
        self.pages["game"].set_items(items)
        self.log(f"[scan] {len(items)} PKG(s)")

    def _update_output_preview(self):
        gp = self.pages["game"]
        disc = self.detected_disc_id or "<DISC_ID>"
        title = self.detected_title or "<Title>"
        base = gp.base_pkg_name or "<BasePKG>"
        if gp.mode_var.get() == "Game PKG":
            txt = f"{C.safe_name(title)}_{C.safe_name(disc)}_{base}.pkg"
        else:
            txt = f"{base}_EMU_<TITLE_ID>.pkg"
        gp.set_output_preview(txt)
        self.output_preview_bar.configure(text=txt)

    def _on_mode_change(self):
        gp = self.pages["game"]
        is_game = gp.mode_var.get() == "Game PKG"
        for c in (gp.c3, gp.c4, gp.c5, gp.c6):
            c.grid() if is_game else c.grid_remove()
        self.build_btn.configure(
            text="🚀   BUILD PKG" if is_game
            else "🔨   BUILD EMULATOR PKG")
        self._update_output_preview()

    # ---------------------------------------------------------- pickers
    def pick_iso(self):
        f = filedialog.askopenfilename(
            title="Select PSP game ISO",
            filetypes=[("ISO", "*.iso"), ("All", "*.*")])
        if not f:
            return
        try:
            p = C._clean(f)
        except Exception as e:
            messagebox.showerror("Bad path", str(e))
            return
        self.iso_file = p
        gp = self.pages["game"]
        gp.iso_label.configure(text=str(p), text_color=SUCCESS)
        gp.stat_iso.set(p.name)
        threading.Thread(target=self._peek_iso, daemon=True).start()

    def _peek_iso(self):
        try:
            disc, name = read_iso_sfo(self.iso_file, self.log)
            self.detected_disc_id = disc
            self.detected_title = name
            self.after(0, self._update_output_preview)
        except Exception as e:
            self.log(f"❌ peek error: {e}")

    def pick_icon(self):
        f = filedialog.askopenfilename(
            title="Select icon",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All", "*.*")])
        if not f:
            return
        self.icon_file = C._clean(f)
        self.pages["game"].icon_var.set(1)
        self.log(f"[icon] {self.icon_file.name}")

    def pick_boot(self):
        f = filedialog.askopenfilename(
            title="Select boot image",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All", "*.*")])
        if not f:
            return
        self.boot_file = C._clean(f)
        self.pages["game"].icon_var.set(1)
        self.log(f"[boot] {self.boot_file.name}")

    # ---------------------------------------------------------- extract
    def preview_base(self):
        gp = self.pages["game"]
        if not gp.base_pkg_path or not gp.base_pkg_path.exists():
            messagebox.showwarning("No base",
                                   "Select a PKG from the list first.")
            return
        # If this exact base is already extracted, just open the folder.
        name = gp.base_pkg_path.stem
        if C.image0_looks_valid() and C.current_extracted_base() == name:
            self.log(f"[preview] {name} already extracted — opening folder")
            self.open_folder(C.IMAGE0_DIR)
            return
        threading.Thread(target=self._extract_thread,
                         args=(gp.base_pkg_path, True),
                         daemon=True).start()

    def _extract_thread(self, pkg: Path, open_after: bool):
        try:
            self.set_progress(10, f"Extracting {pkg.stem}…")
            ok = extract_base(pkg, self.log)
            if not ok:
                self.set_progress(0, "Failed")
                return
            self.after(0, lambda: self.pages["game"].set_base_ready(pkg.stem))
            self.set_progress(30, f"{pkg.stem} extracted")
            if open_after:
                self.after(0, lambda: self.open_folder(C.IMAGE0_DIR))
        except Exception as e:
            self.log(f"❌ Extract error: {e}")
            self.set_progress(0, "Failed")

    # ---------------------------------------------------------- build
    def do_build(self):
        gp = self.pages["game"]
        if gp.base_pkg_path is None:
            messagebox.showerror("No base", "Select a base PKG first.")
            return

        if gp.mode_var.get() == "Game PKG":
            if not self.iso_file or not self.iso_file.exists():
                messagebox.showerror("No ISO", "Pick a game ISO first.")
                return
            threading.Thread(target=self._build_game_thread,
                             daemon=True).start()
        else:
            tid = simpledialog.askstring(
                "Emulator TITLE_ID",
                "TITLE_ID for this emulator PKG\n"
                "(example: UP9000-CUSA00000_00):")
            if not tid:
                return
            threading.Thread(target=self._build_emu_thread,
                             args=(tid,), daemon=True).start()

    def _build_game_thread(self):
        gp = self.pages["game"]
        try:
            iso = self.iso_file
            self.set_build_state(True, "extracting base")
            if not ensure_base_extracted(gp.base_pkg_path, self.log):
                self.set_progress(0, "Failed")
                return
            self.after(0, lambda: gp.set_base_ready(gp.base_pkg_name))

            self.set_build_state(True, "reading ISO")
            self.set_progress(35, "Reading ISO param.sfo…")
            disc_id, psp_name = read_iso_sfo(iso, self.log)
            if not disc_id:
                self.set_progress(0, "Failed")
                return
            self.detected_disc_id = disc_id
            self.detected_title = psp_name
            self.after(0, self._update_output_preview)

            self.set_progress(40, "Patching param.sfo…")
            patch_sfo(disc_id, psp_name, self.log)

            game_dir = make_game_folder(disc_id)
            merge_dlc(game_dir, disc_id, self.log)

            m = gp.decrypt_var.get()
            self.set_build_state(True, "decrypting")
            self.set_progress(45, "Processing game image…")
            if m == 1:
                if not decrypt_and_mkiso(iso, game_dir, disc_id, self.log):
                    self.log("⚠️ decrypt failed — swap")
                    swap_method(iso, game_dir, disc_id, self.log)
            elif m == 2:
                swap_method(iso, game_dir, disc_id, self.log)
            else:
                skip_copy(iso, game_dir, disc_id, self.log)

            self.set_progress(72, "Applying options…")
            vals = gp.schema_form.values()
            apply_schema_to_config(self.schema, vals, self.log)

            if gp.use_overrides.get():
                apply_overrides(self.log)

            if gp.icon_var.get() == 1:
                apply_custom_icons(self.icon_file, self.boot_file, self.log)
            else:
                copy_default_icons(self.log)

            out_name = (f"{C.safe_name(psp_name)}"
                        f"_{C.safe_name(disc_id)}"
                        f"_{gp.base_pkg_name}.pkg")
            self.set_build_state(True, "building pkg")
            self.set_progress(80, "Building PKG…")
            final = finish_pkg(out_name, disc_id, psp_name, self.log)
            if final:
                self.set_progress(100, f"Done — {final.name}")
                self.msg_main("info", "Success",
                              f"PKG created:\n{final}")
            else:
                self.set_progress(0, "Failed")
        except Exception as e:
            self.log(f"❌ Exception: {e}")
            self.log(traceback.format_exc())
            self.set_progress(0, "Failed")
        finally:
            self.set_build_state(False)

    def _build_emu_thread(self, tid):
        gp = self.pages["game"]
        try:
            self.set_build_state(True, "extracting base")
            if not ensure_base_extracted(gp.base_pkg_path, self.log):
                self.set_progress(0, "Failed")
                return
            self.after(0, lambda: gp.set_base_ready(gp.base_pkg_name))

            self.set_progress(40, "Preparing emulator PKG…")
            sfo = C.IMAGE0_DIR / "sce_sys" / "param.sfo"
            if not sfo.exists():
                self.log("❌ param.sfo missing")
                self.set_progress(0, "Failed")
                return

            content_id = f"{tid}-{gp.base_pkg_name}"
            title = f"Emu {gp.base_pkg_name}"
            for k, v in [("TITLE_ID", tid),
                         ("CONTENT_ID", content_id),
                         ("TITLE", title)]:
                C.run_cmd([str(C.SFO), "-e", k, v, str(sfo)])
            # ... rest unchanged

            if gp.use_overrides.get():
                apply_overrides(self.log)

            out_name = f"{gp.base_pkg_name}_EMU_{C.safe_name(tid)}.pkg"
            self.set_build_state(True, "building pkg")
            self.set_progress(80, "Building PKG…")
            final = finish_pkg(out_name, tid, title, self.log)
            if final:
                self.set_progress(100, f"Done — {final.name}")
                self.msg_main("info", "Success",
                              f"PKG created:\n{final}")
            else:
                self.set_progress(0, "Failed")
        except Exception as e:
            self.log(f"❌ Exception: {e}")
            self.set_progress(0, "Failed")
        finally:
            self.set_build_state(False)

    # ---------------------------------------------------------- manual
    def do_manual_build(self):
        threading.Thread(target=self._manual_thread,
                         daemon=True).start()

    def _manual_thread(self):
        try:
            self.manual_log("Generating GP4 …")
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
            out = C.OUTPUT_DIR / "manual.pkg"
            if out.exists():
                out.unlink()

            self.manual_log("orbis-pub-cmd img_create …")
            rc = C.run_silent([str(C.ORBIS_PLAIN), "img_create",
                               str(gp4), str(out)])
            if rc != 0 or not out.exists():
                self.manual_log("❌ build failed")
                return
            try:
                gp4.unlink()
            except Exception:
                pass
            self.manual_log(f"✅ Created: {out}")
            self.msg_main("info", "Success", f"Created:\n{out}")
        except Exception as e:
            self.manual_log(f"❌ Exception: {e}")

    def manual_log(self, msg):
        mp = self.pages["manual"]

        def do():
            try:
                mp.manual_log.configure(state="normal")
                mp.manual_log.insert("end", msg + "\n")
                mp.manual_log.see("end")
                mp.manual_log.configure(state="disabled")
            except Exception:
                pass
        self.after(0, do)


# ============================================================================
def run():
    app = PSP2PS4App()
    missing = [p for p in (C.ORBIS, C.GENGP4, C.FART, C.SFO, C.MAGICK,
                           C.SEVENZ, C.PSPDECRYPT, C.MKISOFS)
               if not p.exists()]
    if missing:
        app.log("⚠️ Missing tools:")
        for m in missing:
            app.log(f"   - {m}")
    app.mainloop()


if __name__ == "__main__":
    run()
