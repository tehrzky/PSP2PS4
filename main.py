"""
PSP 2 PS4 AIO — GUI
Builds a PS4-installable PKG from a PSP .ISO, or extracts/builds custom
emulator PKGs. Uses the toolchain in ./tools/.

Layout: two columns — left scrolls (cards), right fixed (progress + log).
All PKG lists are scanned from disk. Nothing about emulators is hardcoded.
"""
import os
import sys
import json
import time
import shutil
import subprocess
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

# ----------------------------------------------------------------------------
# Paths (works whether running as .py or frozen .exe)
# ----------------------------------------------------------------------------
def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent

BASE_DIR      = base_dir()
TOOLS_DIR     = BASE_DIR / "tools"
IMAGE0_DIR    = TOOLS_DIR / "image0"
BASE_PKGS_DIR = BASE_DIR / "base_pkgs"
OFFICIAL_DIR  = BASE_DIR / "official_pkgs"
OVERRIDES_DIR = BASE_DIR / "overrides"
DLC_DIR       = BASE_DIR / "game_dlc"
OUTPUT_DIR    = BASE_DIR / "output_pkgs"
SCHEMA_FILE   = BASE_DIR / "emulator_options.json"

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
# Theme
# ----------------------------------------------------------------------------
COL_BG          = "#1a1a1e"
COL_CARD        = "#232327"
COL_CARD_HEADER = "#2f2f38"
COL_BORDER      = "#3a3a42"
COL_ACCENT      = "#8ab4f8"
COL_TEXT_DIM    = "#999999"
COL_SUCCESS     = "#3fb950"
COL_WARNING     = "#d29922"
COL_DANGER      = "#f85149"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ----------------------------------------------------------------------------
# Folder READMEs
# ----------------------------------------------------------------------------
FOLDER_READMES = {
    BASE_PKGS_DIR: (
        "base_pkgs/\n"
        "==========\n\n"
        "Put your BASE emulator PKGs here.\n"
        "These are the small emulator PKGs used as the base for building.\n\n"
        "Any *.pkg file you drop here will appear in the GUI list.\n"
        "The filename (without .pkg) becomes the display name.\n"
    ),
    OFFICIAL_DIR: (
        "official_pkgs/\n"
        "==============\n\n"
        "Put big untouched OFFICIAL PKGs here.\n\n"
        "Only the EBOOT.BIN is extracted from these.\n"
        "Useful when you want to build with the emulator version inside\n"
        "an official release someone shared.\n\n"
        "Any *.pkg file you drop here will appear in the GUI list.\n"
    ),
    OVERRIDES_DIR: (
        "overrides/\n"
        "==========\n\n"
        "OPTIONAL. Files here OVERWRITE the extracted base PKG inside\n"
        "tools/image0/ before building.\n\n"
        "Use for:\n"
        "  - custom EBOOT.BIN\n"
        "  - custom config-title.txt\n"
        "  - custom icons (icon0.png, pic1.png, save_data.png)\n"
        "  - any asset you want inside the final PKG\n\n"
        "If the checkbox in the GUI is OFF, nothing here is copied.\n"
    ),
    DLC_DIR: (
        "game_dlc/\n"
        "=========\n\n"
        "OPTIONAL. Drop DLC folders here named after the game's TITLE_ID.\n\n"
        "Example:\n"
        "  game_dlc/UCES00304/DLC1/...\n"
        "  game_dlc/UCES00304/DLC2/...\n\n"
        "Everything inside is merged into the game PKG's VMS/GAME folder.\n"
    ),
    OUTPUT_DIR: (
        "output_pkgs/\n"
        "============\n\n"
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
# Schema loader for emulator_options.json
# ----------------------------------------------------------------------------
def load_schema() -> dict:
    if SCHEMA_FILE.exists():
        try:
            return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
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
                {"value": "skip",            "label": "skip (recommended)"},
                {"value": "drawbounds",      "label": "drawbounds"},
                {"value": "drawboundsloco",  "label": "drawboundsloco"},
                {"value": "locoroco2",       "label": "locoroco2"},
                {"value": "patchworkheroes", "label": "patchworkheroes"},
                {"value": "rondo",           "label": "rondo"},
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

# ----------------------------------------------------------------------------
# Shell helpers
# ----------------------------------------------------------------------------
def run_cmd(cmd, cwd=None, check=False):
    try:
        r = subprocess.run(
            cmd, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return r.returncode, r.stdout.decode(errors="ignore")
    except Exception as e:
        return -1, str(e)

def run_visible(cmd, cwd=None):
    try:
        return subprocess.run(cmd, cwd=cwd).returncode
    except Exception:
        return -1

def rmtree(p):
    if Path(p).exists():
        shutil.rmtree(p, ignore_errors=True)

def safe_name(s: str) -> str:
    return "".join(c for c in s if c not in r'<>:"/\|?*').strip()

def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

def scan_base_pkgs():
    """Return list of dicts: source / name / path / size."""
    out = []
    for src, folder in [("base_pkgs", BASE_PKGS_DIR),
                        ("official",  OFFICIAL_DIR)]:
        folder.mkdir(parents=True, exist_ok=True)
        for pkg in sorted(folder.glob("*.pkg")):
            try:
                size = pkg.stat().st_size
            except Exception:
                size = 0
            out.append({
                "source": src,
                "name":   pkg.stem,
                "path":   pkg,
                "size":   size,
            })
    return out

# ----------------------------------------------------------------------------
# Schema-driven option form
# ----------------------------------------------------------------------------
class SchemaForm:
    def __init__(self, parent, schema: dict):
        self.schema = schema
        self.vars = {}
        self._build(parent)

    def _build(self, parent):
        for key, spec in self.schema.items():
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=6)

            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True)

            ctk.CTkLabel(left, text=spec.get("label", key),
                         font=ctk.CTkFont(size=12, weight="bold"),
                         anchor="w").pack(anchor="w")
            if spec.get("description"):
                ctk.CTkLabel(left, text=spec["description"],
                             font=ctk.CTkFont(size=10),
                             text_color=COL_TEXT_DIM,
                             wraplength=420, justify="left",
                             anchor="w").pack(anchor="w")

            kind = spec.get("type", "text")
            default = spec.get("default", "")

            if kind == "choice":
                values = [c["label"] for c in spec["choices"]]
                l2v = {c["label"]: c["value"] for c in spec["choices"]}
                default_label = next(
                    (c["label"] for c in spec["choices"] if c["value"] == default),
                    values[0] if values else "",
                )
                var = tk.StringVar(value=default_label)
                ctk.CTkOptionMenu(row, values=values, variable=var,
                                  width=220).pack(side="right", padx=(12, 0))
                self.vars[key] = ("choice", var, l2v)
            else:
                var = tk.StringVar(value=default)
                ctk.CTkEntry(row, textvariable=var,
                             width=300).pack(side="right", padx=(12, 0))
                self.vars[key] = ("text", var, None)

    def values(self) -> dict:
        out = {}
        for key, (kind, var, l2v) in self.vars.items():
            if kind == "choice":
                out[key] = l2v.get(var.get(), var.get())
            else:
                out[key] = var.get()
        return out


# ----------------------------------------------------------------------------
# Card helper
# ----------------------------------------------------------------------------
class Card(ctk.CTkFrame):
    """Rounded card with header strip and body frame."""
    def __init__(self, parent, number, title, subtitle=""):
        super().__init__(parent, corner_radius=10,
                         fg_color=COL_CARD,
                         border_width=1, border_color=COL_BORDER)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color=COL_CARD_HEADER,
                              corner_radius=8, height=40)
        header.grid(row=0, column=0, sticky="ew", padx=1, pady=(1, 0))
        header.grid_propagate(False)
        header.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(header, text=f" {number} ",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COL_ACCENT,
                     fg_color="#1e293b", corner_radius=6)\
            .grid(row=0, column=0, padx=(12, 8), pady=8)

        ctk.CTkLabel(header, text=title,
                     font=ctk.CTkFont(size=13, weight="bold"))\
            .grid(row=0, column=1, sticky="w")

        if subtitle:
            ctk.CTkLabel(header, text=subtitle,
                         font=ctk.CTkFont(size=10),
                         text_color=COL_TEXT_DIM)\
                .grid(row=0, column=2, sticky="w", padx=12)

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="ew", padx=14, pady=12)
        self.body.grid_columnconfigure(0, weight=1)


# ----------------------------------------------------------------------------
# Base PKG listbox (custom scrollable)
# ----------------------------------------------------------------------------
class PkgList(ctk.CTkFrame):
    """Scrollable list of PKG rows. Emits selection via callback."""

    HEADERS = ("Source", "Name", "Size")

    def __init__(self, parent, on_select, height=180):
        super().__init__(parent, fg_color="#1c1c20",
                         corner_radius=8, border_width=1,
                         border_color=COL_BORDER)
        self.on_select = on_select
        self.selected_index = None
        self.items = []
        self.row_widgets = []

        # header row
        hdr = ctk.CTkFrame(self, fg_color="#26262b",
                           corner_radius=0, height=28)
        hdr.pack(fill="x", padx=1, pady=(1, 0))
        hdr.pack_propagate(False)
        for i, (txt, w) in enumerate(zip(self.HEADERS, (90, 260, 80))):
            ctk.CTkLabel(hdr, text=txt, width=w, anchor="w",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color="#c8c8d0")\
                .pack(side="left", padx=(12 if i == 0 else 4, 0))

        # scroll area
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                             height=height - 40)
        self.scroll.pack(fill="both", expand=True, padx=2, pady=2)

        # empty state
        self.empty = ctk.CTkLabel(self.scroll,
                                  text="No PKGs found.\n\n"
                                       "Drop *.pkg files into base_pkgs/ or official_pkgs/,\n"
                                       "then click ↻ Rescan.",
                                  justify="center",
                                  text_color=COL_TEXT_DIM,
                                  font=ctk.CTkFont(size=11))
        self.empty.pack(pady=30)

    def set_items(self, items):
        for w in self.row_widgets:
            w.destroy()
        self.row_widgets = []
        self.items = items
        self.selected_index = None

        if not items:
            self.empty.pack(pady=30)
            return
        self.empty.pack_forget()

        for idx, item in enumerate(items):
            self._make_row(idx, item)

    def _make_row(self, idx, item):
        row = ctk.CTkFrame(self.scroll, fg_color="transparent",
                           corner_radius=6, height=28)
        row.pack(fill="x", padx=2, pady=1)
        row.pack_propagate(False)

        ctk.CTkLabel(row, text=item["source"], width=90, anchor="w",
                     font=ctk.CTkFont(size=11),
                     text_color="#a0a0b0")\
            .pack(side="left", padx=(10, 4))
        ctk.CTkLabel(row, text=item["name"], width=260, anchor="w",
                     font=ctk.CTkFont(size=11))\
            .pack(side="left")
        ctk.CTkLabel(row, text=human_size(item["size"]), width=80, anchor="w",
                     font=ctk.CTkFont(size=11),
                     text_color="#a0a0b0")\
            .pack(side="left")

        # bind clicks on row + all children
        def click(_e, i=idx):
            self._select(i)
        for w in [row] + list(row.winfo_children()):
            w.bind("<Button-1>", click)

        self.row_widgets.append(row)

    def _select(self, idx):
        for i, row in enumerate(self.row_widgets):
            if i == idx:
                row.configure(fg_color="#2c3a55")
            else:
                row.configure(fg_color="transparent")
        self.selected_index = idx
        if 0 <= idx < len(self.items):
            self.on_select(self.items[idx])

    def select_by_path(self, path):
        for i, item in enumerate(self.items):
            if item["path"] == path:
                self._select(i)
                return


# ----------------------------------------------------------------------------
# Main App
# ----------------------------------------------------------------------------
class PSP2PS4App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PSP 2 PS4 AIO")

        ensure_folders()

        # runtime state
        self.iso_file: Path | None = None
        self.icon_file: Path | None = None
        self.boot_file: Path | None = None
        self.base_pkg_path: Path | None = None
        self.base_pkg_name: str = ""
        self.detected_disc_id: str = ""
        self.detected_title: str = ""
        self.schema = load_schema()

        self._build_ui()
        self._apply_window_size()
        migrate_old_folders(log=self.log)
        self.rescan_pkgs()

    # ---------------------------------------------------------- layout shell
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=0, minsize=230)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---------- sidebar ----------
        side = ctk.CTkFrame(self, width=230, corner_radius=0,
                            fg_color="#161619")
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)

        ctk.CTkLabel(side, text="PSP 2 PS4 AIO",
                     font=ctk.CTkFont(size=18, weight="bold"))\
            .pack(pady=(22, 2))
        ctk.CTkLabel(side, text="GUI  •  V2.5",
                     font=ctk.CTkFont(size=10),
                     text_color=COL_TEXT_DIM).pack(pady=(0, 22))

        ctk.CTkButton(side, text="🎮  Build PKG",
                      command=lambda: self.show_page("game"),
                      height=38, anchor="w")\
            .pack(pady=4, padx=14, fill="x")
        ctk.CTkButton(side, text="📦  Manual Builder",
                      command=lambda: self.show_page("manual"),
                      height=38, anchor="w",
                      fg_color="transparent", border_width=1)\
            .pack(pady=4, padx=14, fill="x")
        ctk.CTkButton(side, text="⬇️  Install Framework 5.0",
                      command=self.open_framework,
                      height=38, anchor="w",
                      fg_color="transparent", border_width=1)\
            .pack(pady=4, padx=14, fill="x")

        ctk.CTkButton(side, text="🧹  Cleanup work dir",
                      command=self.cleanup_workdir,
                      fg_color="#8B0000", hover_color="#5a0000",
                      height=34)\
            .pack(side="bottom", pady=14, padx=14, fill="x")

        ctk.CTkLabel(side, text="Drop your own PKGs into\nbase_pkgs/ and official_pkgs/",
                     font=ctk.CTkFont(size=9),
                     text_color=COL_TEXT_DIM,
                     justify="center").pack(side="bottom", pady=8)

        # ---------- content host ----------
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color=COL_BG)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.pages = {}
        self._build_game_page()
        self._build_manual_page()
        self.show_page("game")

    def _apply_window_size(self):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()

        win_w = min(1180, sw - 100)
        win_h = min(820,  sh - 140)
        win_w = max(win_w, 900)
        win_h = max(win_h, 600)

        x = max(0, (sw - win_w) // 2)
        y = max(0, (sh - win_h) // 2 - 20)
        self.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.minsize(900, 600)

    def show_page(self, name):
        for p in self.pages.values():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)

    # ------------------------------------------------------------- game page
    def _build_game_page(self):
        page = ctk.CTkFrame(self.content, corner_radius=0, fg_color=COL_BG)
        self.pages["game"] = page
        page.grid_rowconfigure(0, weight=1)
        page.grid_columnconfigure(0, weight=1)   # left (scrolls)
        page.grid_columnconfigure(1, weight=0, minsize=380)  # right (fixed)

        # ---------- LEFT column (scrollable) ----------
        left = ctk.CTkScrollableFrame(page, corner_radius=0,
                                      fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        left.grid_columnconfigure(0, weight=1)
        self.left_col = left

        # header
        hdr = ctk.CTkFrame(left, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=6, pady=(0, 4))
        ctk.CTkLabel(hdr, text="Build PSP Game PKG",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(hdr, text="Turn a PSP .ISO into a PS4-installable PKG.",
                     font=ctk.CTkFont(size=11),
                     text_color=COL_TEXT_DIM, anchor="w").pack(anchor="w")

        # mode segmented button
        mode_frame = ctk.CTkFrame(left, fg_color="transparent")
        mode_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=(6, 4))
        self.mode_var = tk.StringVar(value="Game PKG")
        self.mode_seg = ctk.CTkSegmentedButton(
            mode_frame,
            values=["Game PKG", "Emulator PKG"],
            variable=self.mode_var,
            command=lambda v: self._on_mode_change(),
            height=34)
        self.mode_seg.pack(fill="x")

        # Card 1 — Base PKG
        c1 = Card(left, "1", "Base PKG",
                  "Pick the emulator PKG used as the base")
        c1.grid(row=2, column=0, sticky="ew", padx=6, pady=6)

        # list + toolbar
        ctk.CTkLabel(c1.body, text="Available PKGs",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     anchor="w").pack(anchor="w")

        toolbar = ctk.CTkFrame(c1.body, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(toolbar, text="📂 base_pkgs/", width=130,
                      fg_color="transparent", border_width=1,
                      command=lambda: self.open_folder(BASE_PKGS_DIR))\
            .pack(side="left", padx=(0, 4))
        ctk.CTkButton(toolbar, text="📂 official_pkgs/", width=140,
                      fg_color="transparent", border_width=1,
                      command=lambda: self.open_folder(OFFICIAL_DIR))\
            .pack(side="left", padx=(0, 4))
        ctk.CTkButton(toolbar, text="↻ Rescan", width=90,
                      command=self.rescan_pkgs)\
            .pack(side="right")

        self.pkg_list = PkgList(c1.body, on_select=self._on_pkg_select, height=200)
        self.pkg_list.pack(fill="x", pady=(4, 6))

        status = ctk.CTkFrame(c1.body, fg_color="transparent")
        status.pack(fill="x", pady=(4, 0))
        self.base_status = ctk.CTkLabel(status, text="● Not extracted",
                                        text_color=COL_DANGER,
                                        font=ctk.CTkFont(size=11, weight="bold"))
        self.base_status.pack(side="left")
        ctk.CTkButton(status, text="Extract Base PKG", width=150,
                      command=self.do_extract_emulator)\
            .pack(side="right")

        # Card 2 — Overrides
        c2 = Card(left, "2", "Overrides (optional)",
                  "overrides/ overwrites the extracted base")
        c2.grid(row=3, column=0, sticky="ew", padx=6, pady=6)
        self.use_overrides = tk.BooleanVar(value=False)
        row2 = ctk.CTkFrame(c2.body, fg_color="transparent")
        row2.pack(fill="x")
        ctk.CTkCheckBox(row2, text="Copy files from overrides/",
                        variable=self.use_overrides).pack(side="left")
        ctk.CTkButton(row2, text="📂 Open", width=80,
                      fg_color="transparent", border_width=1,
                      command=lambda: self.open_folder(OVERRIDES_DIR))\
            .pack(side="right")
        ctk.CTkLabel(c2.body,
                     text="⚠️  Files here OVERWRITE the base (custom EBOOT.BIN, config, icons).",
                     text_color=COL_WARNING,
                     font=ctk.CTkFont(size=10), anchor="w")\
            .pack(anchor="w", pady=(4, 0))

        # Card 3 — Game ISO (hidden in emulator mode)
        self.c3 = Card(left, "3", "Game ISO",
                       "Pick your PSP game's .ISO file")
        self.c3.grid(row=4, column=0, sticky="ew", padx=6, pady=6)
        self.iso_label = ctk.CTkLabel(self.c3.body, text="No ISO selected",
                                      text_color=COL_DANGER, anchor="w")
        self.iso_label.pack(anchor="w", pady=2)
        row3 = ctk.CTkFrame(self.c3.body, fg_color="transparent")
        row3.pack(fill="x", pady=4)
        ctk.CTkButton(row3, text="Browse ISO...", width=140,
                      command=self.pick_iso).pack(side="left")
        ctk.CTkButton(row3, text="📂 game_dlc/", width=120,
                      fg_color="transparent", border_width=1,
                      command=lambda: self.open_folder(DLC_DIR))\
            .pack(side="right")
        self.output_preview = ctk.CTkLabel(self.c3.body, text="",
                                           font=ctk.CTkFont(size=11),
                                           text_color=COL_SUCCESS, anchor="w")
        self.output_preview.pack(anchor="w", pady=(4, 0))

        # Card 4 — Decrypt
        self.c4 = Card(left, "4", "Decrypt Method")
        self.c4.grid(row=5, column=0, sticky="ew", padx=6, pady=6)
        self.decrypt_var = tk.IntVar(value=1)
        ctk.CTkRadioButton(self.c4.body,
                           text="Decrypt & rebuild ISO  — safest",
                           variable=self.decrypt_var, value=1)\
            .pack(anchor="w", pady=2)
        ctk.CTkRadioButton(self.c4.body,
                           text="Swap EBOOT  — fallback if decrypt fails",
                           variable=self.decrypt_var, value=2)\
            .pack(anchor="w", pady=2)
        ctk.CTkRadioButton(self.c4.body,
                           text="Skip  — assume already decrypted (fast, may not work)",
                           variable=self.decrypt_var, value=3)\
            .pack(anchor="w", pady=2)

        # Card 5 — Emulator Options
        self.c5 = Card(left, "5", "Emulator Options",
                       "Loaded from emulator_options.json")
        self.c5.grid(row=6, column=0, sticky="ew", padx=6, pady=6)
        self.schema_form = SchemaForm(self.c5.body, self.schema)

        # Card 6 — Icon
        self.c6 = Card(left, "6", "Icon / Background")
        self.c6.grid(row=7, column=0, sticky="ew", padx=6, pady=6)
        self.icon_var = tk.IntVar(value=2)
        ctk.CTkRadioButton(self.c6.body, text="Use default icons",
                           variable=self.icon_var, value=2)\
            .pack(anchor="w", pady=2)
        ctk.CTkLabel(self.c6.body,
                     text="(tools/pic/icon0.png, pic1.png, save_data.png)",
                     text_color=COL_TEXT_DIM,
                     font=ctk.CTkFont(size=10), anchor="w")\
            .pack(anchor="w", padx=24)
        ctk.CTkRadioButton(self.c6.body, text="Set custom icon / background",
                           variable=self.icon_var, value=1)\
            .pack(anchor="w", pady=(6, 2))

        row6 = ctk.CTkFrame(self.c6.body, fg_color="transparent")
        row6.pack(fill="x", padx=24, pady=2)
        ctk.CTkButton(row6, text="Choose Icon...", width=140,
                      command=self.pick_icon).pack(side="left", padx=(0, 8))
        self.icon_label = ctk.CTkLabel(row6, text="(none)",
                                       text_color=COL_TEXT_DIM, anchor="w")
        self.icon_label.pack(side="left")

        row6b = ctk.CTkFrame(self.c6.body, fg_color="transparent")
        row6b.pack(fill="x", padx=24, pady=2)
        ctk.CTkButton(row6b, text="Choose Boot Image...", width=160,
                      command=self.pick_boot).pack(side="left", padx=(0, 8))
        self.boot_label = ctk.CTkLabel(row6b, text="(none)",
                                       text_color=COL_TEXT_DIM, anchor="w")
        self.boot_label.pack(side="left")

        # spacer for bottom bar
        ctk.CTkFrame(left, fg_color="transparent", height=6)\
            .grid(row=8, column=0)

        # ---------- RIGHT column ----------
        right = ctk.CTkFrame(page, fg_color=COL_CARD, corner_radius=10,
                             border_width=1, border_color=COL_BORDER)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        right.grid_rowconfigure(3, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # Progress
        ctk.CTkLabel(right, text="Progress",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew",
                                      padx=14, pady=(12, 2))
        self.progress = ctk.CTkProgressBar(right, height=10,
                                           progress_color=COL_ACCENT)
        self.progress.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 2))
        self.progress.set(0)
        self.progress_label = ctk.CTkLabel(right, text="0%  Idle",
                                           font=ctk.CTkFont(size=10),
                                           text_color=COL_TEXT_DIM,
                                           anchor="w")
        self.progress_label.grid(row=2, column=0, sticky="ew",
                                 padx=14, pady=(0, 8))

        # Log header + clear button
        log_hdr = ctk.CTkFrame(right, fg_color="transparent")
        log_hdr.grid(row=3, column=0, sticky="new", padx=14)
        ctk.CTkLabel(log_hdr, text="Log",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(side="left")
        ctk.CTkButton(log_hdr, text="🗑 Clear", width=70, height=24,
                      fg_color="transparent", border_width=1,
                      font=ctk.CTkFont(size=10),
                      command=self.clear_log).pack(side="right")

        self.log_box = ctk.CTkTextbox(right, wrap="word",
                                      font=ctk.CTkFont(family="Consolas", size=11),
                                      fg_color="#121214",
                                      text_color="#c8e6c9")
        self.log_box.grid(row=4, column=0, sticky="nsew",
                          padx=14, pady=(4, 12))
        self.log_box.configure(state="disabled")

        # bottom bar (fixed inside left column)
        bottom = ctk.CTkFrame(page, fg_color="#161619", corner_radius=0,
                              height=64)
        bottom.grid(row=1, column=0, sticky="ew", padx=(8, 4), pady=(0, 8))
        bottom.grid_propagate(False)
        bottom.grid_columnconfigure(0, weight=1)

        self.build_btn = ctk.CTkButton(bottom, text="🚀  BUILD PKG",
                                       height=44,
                                       font=ctk.CTkFont(size=15, weight="bold"),
                                       command=self.do_build)
        self.build_btn.grid(row=0, column=0, sticky="ew",
                            padx=(10, 6), pady=10)
        ctk.CTkButton(bottom, text="📂", width=48, height=44,
                      fg_color="transparent", border_width=1,
                      command=lambda: self.open_folder(OUTPUT_DIR))\
            .grid(row=0, column=1, padx=(0, 10), pady=10)

        page.grid_rowconfigure(1, weight=0)

    # ----------------------------------------------------------- manual page
    def _build_manual_page(self):
        page = ctk.CTkFrame(self.content, corner_radius=0, fg_color=COL_BG)
        self.pages["manual"] = page
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(page, text="Manual PKG Builder",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew",
                                      padx=20, pady=(16, 2))
        ctk.CTkLabel(page,
                     text="Advanced. Put anything in tools/image0/ then build. "
                          "No ISO processing, no patching — just pack what's there.",
                     font=ctk.CTkFont(size=11),
                     text_color=COL_TEXT_DIM,
                     wraplength=780, justify="left", anchor="w")\
            .grid(row=1, column=0, sticky="ew", padx=20)

        toolbar = ctk.CTkFrame(page, fg_color="transparent")
        toolbar.grid(row=2, column=0, sticky="ew", padx=20, pady=10)
        ctk.CTkButton(toolbar, text="Open tools/image0/",
                      fg_color="transparent", border_width=1,
                      command=lambda: self.open_folder(IMAGE0_DIR))\
            .pack(side="left")
        ctk.CTkButton(toolbar, text="🚀  BUILD output_pkgs/manual.pkg",
                      command=self.do_manual_build).pack(side="left", padx=8)

        self.manual_log = ctk.CTkTextbox(page, wrap="word",
                                         font=ctk.CTkFont(family="Consolas", size=11),
                                         fg_color="#121214",
                                         text_color="#c8e6c9")
        self.manual_log.grid(row=3, column=0, sticky="nsew",
                             padx=20, pady=(0, 16))
        self.manual_log.configure(state="disabled")

    # ------------------------------------------------------------------ log
    def log(self, msg):
        self.after(0, lambda m=msg: self._log_main(m))

    def _log_main(self, msg):
        try:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def mlog(self, msg):
        self.after(0, lambda m=msg: self._mlog_main(m))

    def _mlog_main(self, msg):
        try:
            self.manual_log.configure(state="normal")
            self.manual_log.insert("end", msg + "\n")
            self.manual_log.see("end")
            self.manual_log.configure(state="disabled")
        except Exception:
            pass

    def clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def set_progress(self, pct: int, label: str = ""):
        self.after(0, lambda: self._set_progress(pct, label))

    def _set_progress(self, pct, label):
        try:
            self.progress.set(pct / 100.0)
            self.progress_label.configure(text=f"{pct}%  {label}")
        except Exception:
            pass

    # ---------------------------------------------------------- ask on main
    def ask_main(self, prompt, title="Input", integer=False,
                 minvalue=1, maxvalue=9999):
        box = {}
        done = {"flag": False}

        def run():
            try:
                if integer:
                    box["v"] = simpledialog.askinteger(
                        title, prompt, minvalue=minvalue, maxvalue=maxvalue)
                else:
                    box["v"] = simpledialog.askstring(title, prompt)
            finally:
                done["flag"] = True

        self.after(0, run)
        while not done["flag"]:
            time.sleep(0.05)
        return box.get("v")

    # ---------------------------------------------------------- UI actions
    def open_folder(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def open_framework(self):
        if messagebox.askyesno("Framework 5.0",
                               "Open the .NET 5.0 download page?"):
            os.startfile("https://dotnet.microsoft.com/en-us/download/dotnet/5.0")

    def cleanup_workdir(self):
        if not messagebox.askyesno("Cleanup",
                                   "Delete tools/image0 and temp files?"):
            return
        rmtree(IMAGE0_DIR)
        for f in (TOOLS_DIR / "image0.gp4", TOOLS_DIR / "image0.txt",
                  TOOLS_DIR / "sort_file.txt"):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
        self.base_status.configure(text="● Not extracted", text_color=COL_DANGER)
        self.set_progress(0, "Idle")
        self.log("[cleanup] tools/image0 wiped.")
        messagebox.showinfo("Cleanup", "Work directory cleaned.")

    # --------------------------------------------------------- scan PKGs
    def rescan_pkgs(self):
        items = scan_base_pkgs()
        self.pkg_list.set_items(items)
        self.log(f"[scan] {len(items)} PKG(s) found "
                 f"(base_pkgs: {sum(1 for i in items if i['source']=='base_pkgs')}, "
                 f"official: {sum(1 for i in items if i['source']=='official')})")

    def _on_pkg_select(self, item):
        self.base_pkg_path = item["path"]
        self.base_pkg_name = item["name"]
        self._update_output_preview()

    def _on_mode_change(self):
        is_game = self.mode_var.get() == "Game PKG"
        if is_game:
            self.c3.grid()
            self.c4.grid()
            self.c5.grid()
            self.c6.grid()
            self.build_btn.configure(text="🚀  BUILD PKG")
        else:
            self.c3.grid_remove()
            self.c4.grid_remove()
            self.c5.grid_remove()
            self.c6.grid_remove()
            self.build_btn.configure(text="🔨  BUILD EMULATOR PKG")
        self._update_output_preview()

    def _update_output_preview(self):
        disc = self.detected_disc_id or "<DISC_ID>"
        title = self.detected_title or "<Title>"
        base = self.base_pkg_name or "<BasePKG>"
        if self.mode_var.get() == "Game PKG":
            txt = f"Output: {safe_name(title)}_{safe_name(disc)}_{base}.pkg"
        else:
            txt = f"Output: {base}_EMU_<TITLE_ID>.pkg"
        self.output_preview.configure(text=txt)

    # -------------------------------------------------------- pickers
    def pick_iso(self):
        f = filedialog.askopenfilename(
            title="Select PSP game ISO",
            filetypes=[("ISO", "*.iso"), ("All", "*.*")])
        if f:
            self.iso_file = Path(f)
            self.iso_label.configure(text=str(self.iso_file),
                                     text_color=COL_SUCCESS)
            threading.Thread(target=self._peek_iso, daemon=True).start()

    def _peek_iso(self):
        try:
            info = TOOLS_DIR / "info_temp"
            rmtree(info)
            (info / "PSP_GAME").mkdir(parents=True, exist_ok=True)
            run_cmd([str(SEVENZ), "e", str(self.iso_file),
                     f"-o{info / 'PSP_GAME'}", "PSP_GAME/param.sfo", "-aoa"])
            sfo = info / "PSP_GAME" / "param.sfo"
            txt = info / "PSP_GAME" / "param.txt"
            if not sfo.exists():
                return
            run_cmd([str(SFOINFO), "i", str(sfo), str(txt)])
            disc, name = "", ""
            for line in txt.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("DISC_ID"):
                    disc = line.split(":", 1)[1].strip()
                elif line.startswith("TITLE"):
                    name = line.split(":", 1)[1].strip()
            self.detected_disc_id = disc
            self.detected_title = name
            self.after(0, self._update_output_preview)
        except Exception:
            pass

    def pick_icon(self):
        f = filedialog.askopenfilename(
            title="Select icon",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All", "*.*")])
        if f:
            self.icon_file = Path(f)
            self.icon_label.configure(text=Path(f).name,
                                      text_color=COL_SUCCESS)
            self.icon_var.set(1)

    def pick_boot(self):
        f = filedialog.askopenfilename(
            title="Select boot image",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All", "*.*")])
        if f:
            self.boot_file = Path(f)
            self.boot_label.configure(text=Path(f).name,
                                      text_color=COL_SUCCESS)
            self.icon_var.set(1)

    # ---------------------------------------------------- extract base
    def do_extract_emulator(self):
        if not ORBIS.exists():
            messagebox.showerror("Error", f"Missing: {ORBIS}")
            return
        if not self.base_pkg_path or not self.base_pkg_path.exists():
            messagebox.showwarning("No base",
                                   "Select a PKG from the list first.")
            return
        threading.Thread(target=self._extract_thread,
                         args=(self.base_pkg_path, self.base_pkg_name),
                         daemon=True).start()

    def _extract_thread(self, pkg: Path, name: str):
        try:
            self.set_progress(5, f"Extracting {name}")
            self.log(f"--- Extracting base: {name} ---")
            rmtree(IMAGE0_DIR)
            IMAGE0_DIR.mkdir(parents=True, exist_ok=True)

            rc = run_visible([str(ORBIS), "img_extract",
                              "--passcode", "00000000000000000000000000000000",
                              str(pkg), str(TOOLS_DIR)])
            if rc != 0:
                self.log(f"img_extract failed (rc={rc})")
                self.set_progress(0, "Failed")
                return

            sc0 = TOOLS_DIR / "Sc0"
            sce = TOOLS_DIR / "sce_sys"
            if sc0.exists() and not sce.exists():
                sc0.rename(sce)
            if sce.exists():
                dest = IMAGE0_DIR / "sce_sys"
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copytree(sce, dest, dirs_exist_ok=True)
                rmtree(sce)

            target = IMAGE0_DIR / "sce_sys"
            for pat in ("*.json", "*.sig", "*.dds", "*.dat", "*.info",
                        "*.sha", "*.xml", "*.png"):
                for f in target.glob(pat):
                    f.unlink(missing_ok=True)
            for f in IMAGE0_DIR.glob("*.plt"):
                f.unlink(missing_ok=True)
            siea = IMAGE0_DIR / "SIEA"
            if siea.exists():
                for pat in ("*.lua", "*.txt", "*.json"):
                    for f in siea.glob(pat):
                        f.unlink(missing_ok=True)
                scr = siea / "scripts"
                if scr.exists():
                    for f in scr.glob("*.lua"):
                        f.unlink(missing_ok=True)
                rmtree(siea / "data")
            for sub in ("about", "app", "changeinfo", "trophy"):
                rmtree(target / sub)

            tmpl = TOOLS_DIR / "perm" / "config-title.txt"
            if tmpl.exists():
                shutil.copy2(tmpl, IMAGE0_DIR / "config-title.txt")

            for d in list(IMAGE0_DIR.iterdir()):
                if d.is_dir() and "#v1.00" in d.name:
                    self.log(f"  removing stale: {d.name}")
                    rmtree(d)

            self.after(0, lambda: self.base_status.configure(
                text=f"● Ready  ({name})", text_color=COL_SUCCESS))
            self.set_progress(20, f"{name} extracted")
            self.log(f"✅ Base extracted: {name}")
        except Exception as e:
            self.log(f"❌ Extract error: {e}")
            self.set_progress(0, "Failed")

    # ---------------------------------------------------------------- build
    def do_build(self):
        if self.base_pkg_path is None:
            messagebox.showerror("No base", "Select a base PKG first.")
            return
        if not IMAGE0_DIR.exists() or not (IMAGE0_DIR / "sce_sys").exists():
            messagebox.showerror("Not extracted",
                                 "Extract a base PKG first (Step 1).")
            return
        if self.mode_var.get() == "Game PKG":
            if not self.iso_file or not self.iso_file.exists():
                messagebox.showerror("No ISO", "Pick a game ISO first.")
                return
            threading.Thread(target=self._build_game_thread, daemon=True).start()
        else:
            threading.Thread(target=self._build_emu_thread, daemon=True).start()

    # ---- Game build ----
    def _build_game_thread(self):
        try:
            iso = self.iso_file
            self.set_progress(22, "Reading ISO param.sfo")
            self.log(f"--- Building GAME PKG from {iso.name} ---")

            info = TOOLS_DIR / "info_temp"
            rmtree(info)
            (info / "PSP_GAME").mkdir(parents=True, exist_ok=True)
            run_cmd([str(SEVENZ), "e", str(iso),
                     f"-o{info / 'PSP_GAME'}", "PSP_GAME/param.sfo", "-aoa"])
            sfo_src = info / "PSP_GAME" / "param.sfo"
            if not sfo_src.exists():
                self.log("❌ param.sfo not found in ISO")
                self.set_progress(0, "Failed")
                return
            txt = info / "PSP_GAME" / "param.txt"
            run_cmd([str(SFOINFO), "i", str(sfo_src), str(txt)])

            disc_id, psp_name = "", ""
            for line in txt.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("DISC_ID"):
                    disc_id = line.split(":", 1)[1].strip()
                elif line.startswith("TITLE"):
                    psp_name = line.split(":", 1)[1].strip()
            if not disc_id:
                self.log("❌ No DISC_ID in param.sfo")
                self.set_progress(0, "Failed")
                return

            self.detected_disc_id = disc_id
            self.detected_title = psp_name
            self.after(0, self._update_output_preview)

            self.set_progress(30, "Patching param.sfo")
            content_id = f"UP9000-{disc_id}_00-PSPX{disc_id[-5:]}TEHRZKY"
            sfo = IMAGE0_DIR / "sce_sys" / "param.sfo"
            for k, v in [("VERSION", "01.00"),
                         ("CONTENT_ID", content_id),
                         ("TITLE_ID", disc_id),
                         ("TITLE", psp_name)]:
                run_cmd([str(SFO), "-e", k, v, str(sfo)])

            game_dir = IMAGE0_DIR / f"{disc_id}#v1.00"
            for sub in ("aot", "vms/GAME", "vms/SAVEDATA"):
                (game_dir / sub).mkdir(parents=True, exist_ok=True)
            siea = IMAGE0_DIR / "SIEA"
            siea.mkdir(parents=True, exist_ok=True)
            with open(siea / "config-region.txt", "a", encoding="utf-8") as f:
                f.write(f'--active-sku="{disc_id}#v1.00"\n')

            dlc_src = DLC_DIR / disc_id
            if dlc_src.exists():
                shutil.copytree(dlc_src, game_dir / "vms" / "GAME" / disc_id,
                                dirs_exist_ok=True)
                self.log(f"  DLC merged: {disc_id}")

            m = self.decrypt_var.get()
            self.set_progress(40, "Processing game image")
            if m == 1:
                if not self._decrypt_mkiso(iso, game_dir, disc_id):
                    self.log("⚠️ decrypt failed — falling back to swap")
                    self._swap(iso, game_dir, disc_id)
            elif m == 2:
                self._swap(iso, game_dir, disc_id)
            else:
                self._skip_copy(iso, game_dir, disc_id)

            self.set_progress(78, "Applying emulator options")
            self._apply_schema_to_config()

            if self.use_overrides.get():
                self.log("Copying overrides/ ...")
                shutil.copytree(OVERRIDES_DIR, IMAGE0_DIR, dirs_exist_ok=True)

            if self.icon_var.get() == 1:
                self._apply_custom_icons()
            else:
                self._copy_default_icons()

            out_name = f"{safe_name(psp_name)}_{safe_name(disc_id)}_{self.base_pkg_name}.pkg"
            self._finish_pkg(out_name, disc_id, psp_name)
        except Exception as e:
            self.log(f"❌ Exception: {e}")
            import traceback
            self.log(traceback.format_exc())
            self.set_progress(0, "Failed")

    # ---- Emulator build ----
    def _build_emu_thread(self):
        try:
            self.set_progress(30, "Preparing emulator PKG")
            self.log("--- Building EMULATOR PKG ---")
            sfo = IMAGE0_DIR / "sce_sys" / "param.sfo"
            if not sfo.exists():
                self.log("❌ param.sfo missing — extract a base first")
                self.set_progress(0, "Failed")
                return

            tid = self.ask_main(
                "TITLE_ID for this emulator PKG\n"
                "(example: UP9000-CUSA00000_00):",
                "Emulator TITLE_ID")
            if not tid:
                self.set_progress(0, "Cancelled")
                return
            content_id = f"{tid}-{self.base_pkg_name}"
            title = f"Emu {self.base_pkg_name}"

            for k, v in [("TITLE_ID", tid),
                         ("CONTENT_ID", content_id),
                         ("TITLE", title)]:
                run_cmd([str(SFO), "-e", k, v, str(sfo)])

            if self.use_overrides.get():
                self.log("Copying overrides/ ...")
                shutil.copytree(OVERRIDES_DIR, IMAGE0_DIR, dirs_exist_ok=True)

            out_name = f"{self.base_pkg_name}_EMU_{safe_name(tid)}.pkg"
            self._finish_pkg(out_name, tid, title)
        except Exception as e:
            self.log(f"❌ Exception: {e}")
            self.set_progress(0, "Failed")

    # ---- build helpers ----
    def _decrypt_mkiso(self, iso: Path, game_dir: Path, disc_id: str) -> bool:
        tmp = TOOLS_DIR / "iso_extraction_temp"
        rmtree(tmp)
        tmp.mkdir(parents=True, exist_ok=True)
        sort_file = TOOLS_DIR / "sort_file.txt"

        self.set_progress(45, "Generating ISO index")
        try:
            p1 = subprocess.Popen([str(ISOINFO), "-f", "-i", str(iso)],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p2 = subprocess.Popen([str(AWK_NL), "-nln", "-s", ";"],
                                  stdin=p1.stdout, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL)
            p1.stdout.close()
            with open(sort_file, "w", encoding="utf-8", errors="ignore") as f:
                p3 = subprocess.Popen(
                    [str(AWK), "-F", ";", '{print substr($2,2) " -" $1}'],
                    stdin=p2.stdout, stdout=f, stderr=subprocess.DEVNULL)
                p2.stdout.close()
                p3.wait()
        except Exception as e:
            self.log(f"sort error: {e}")

        self.set_progress(48, "Extracting ISO")
        self.log("Extracting ISO with 7z ...")
        run_cmd([str(SEVENZ), "x", str(iso), f"-o{tmp}", "-r", "-aoa"])

        eboot = tmp / "PSP_GAME" / "SYSDIR" / "EBOOT.BIN"
        if not eboot.exists():
            self.log("EBOOT.BIN missing inside ISO")
            rmtree(tmp)
            return False

        self.set_progress(52, "Decrypting EBOOT.BIN")
        self.log("Decrypting EBOOT.BIN ...")
        run_cmd([str(PSPDECRYPT), str(eboot)])
        dec = eboot.with_suffix(".BIN.DEC")
        if not dec.exists():
            self.log("EBOOT.BIN.DEC not produced")
            rmtree(tmp)
            return False
        eboot.unlink()
        dec.rename(eboot)

        out_iso = game_dir / f"{disc_id}#v1.00.IMG"
        self.set_progress(58, "Building ISO with mkisofs")
        self.log("mkisofs ...")
        run_cmd([str(MKISOFS), "-quiet", "-sort", str(sort_file),
                 "-iso-level", "4", "-xa",
                 "-A", "PSP GAME", "-V", "PSP_GAME", "-sysid", "PSP GAME",
                 "-volset", "", "-p", "", "-publisher", "",
                 "-o", str(out_iso), str(tmp)])
        sort_file.unlink(missing_ok=True)
        rmtree(tmp)
        return out_iso.exists()

    def _swap(self, iso, game_dir, disc_id):
        target = game_dir / f"{disc_id}#v1.00.IMG"
        shutil.copy2(iso, target)
        cfg = IMAGE0_DIR / "config-title.txt"
        if cfg.exists():
            run_cmd([str(FART), "-C", str(cfg), "#1",
                     "\\--boot=umd0:/PSP_GAME/SYSDIR/BOOT.BIN"])
        self.log(f"ISO copied as {target.name}")

    def _skip_copy(self, iso, game_dir, disc_id):
        target = game_dir / f"{disc_id}#v1.00.IMG"
        shutil.copy2(iso, target)
        self.log(f"Copied directly (skip): {target.name}")

    def _apply_schema_to_config(self):
        cfg = IMAGE0_DIR / "config-title.txt"
        if not cfg.exists():
            return
        values = self.schema_form.values()
        for key, val in values.items():
            spec = self.schema[key]
            ph = spec["placeholder"]
            if spec.get("type") == "choice" and val == "skip":
                if ph.startswith("#--texcachemode="):
                    run_cmd([str(FART), "-i", str(cfg), ph, "--remove"])
                    self.log("texcachemode: skip (removed)")
                    continue
            run_cmd([str(FART), "-C", str(cfg), ph, f"\\{ph}{val}"])
            self.log(f"config {key} = {val}")

    def _apply_custom_icons(self):
        sce = IMAGE0_DIR / "sce_sys"
        if self.icon_file and self.icon_file.exists():
            run_cmd([str(MAGICK), str(self.icon_file), "-resize", "512x512!",
                     "-colorspace", "sRGB", "-depth", "8", str(sce / "icon0.png")])
            run_cmd([str(MAGICK), str(self.icon_file), "-resize", "512x512!",
                     str(IMAGE0_DIR / "SIEA" / "regional_icon.png")])
            self.log("Custom icon applied.")
        if self.boot_file and self.boot_file.exists():
            run_cmd([str(MAGICK), str(self.boot_file), "-resize", "1920x1080!",
                     str(sce / "pic1.png")])
            shutil.copy2(sce / "pic1.png", sce / "pic0.png")
            self.log("Custom boot image applied.")

    def _copy_default_icons(self):
        src = TOOLS_DIR / "pic"
        sce = IMAGE0_DIR / "sce_sys"
        if not src.exists():
            return
        for n in ("icon0.png", "pic1.png", "save_data.png"):
            s = src / n
            if s.exists():
                shutil.copy2(s, sce / n)
        self.log("Default icons copied.")

    def _finish_pkg(self, out_name: str, disc_id: str, title: str):
        self.set_progress(84, "Generating GP4")
        self.log("Generating GP4 ...")
        run_cmd([str(GENGP4), str(IMAGE0_DIR)])

        gp4 = TOOLS_DIR / "image0.gp4"
        txt = TOOLS_DIR / "image0.txt"
        if gp4.exists():
            gp4.rename(txt)
        if txt.exists():
            run_cmd([str(FART), str(txt), "-i",
                     'default_id="1"', 'default_id="0"'])
            txt.rename(gp4)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        tmp_pkg = OUTPUT_DIR / "1.pkg"
        if tmp_pkg.exists():
            tmp_pkg.unlink()

        self.set_progress(88, "orbis-pub-cmd img_create")
        self.log("orbis-pub-cmd img_create ...")
        rc = run_visible([str(ORBIS), "img_create", str(gp4), str(tmp_pkg)])
        if rc != 0 or not tmp_pkg.exists():
            self.log("❌ img_create failed")
            self.set_progress(0, "Failed")
            return

        final = OUTPUT_DIR / out_name
        if final.exists():
            final.unlink()
        tmp_pkg.rename(final)

        size_mb = final.stat().st_size // (1024 * 1024)
        (OUTPUT_DIR / f"[{disc_id}] {title} ({size_mb}mb).txt")\
            .write_text("", encoding="utf-8")
        try:
            gp4.unlink()
        except Exception:
            pass
        rmtree(IMAGE0_DIR)

        self.set_progress(100, f"Done — {final.name}")
        self.log(f"✅ PKG created: {final.name}  ({size_mb} MB)")
        messagebox.showinfo("Success", f"PKG created:\n{final}")

    # -------------------------------------------------------- manual build
    def do_manual_build(self):
        threading.Thread(target=self._manual_thread, daemon=True).start()

    def _manual_thread(self):
        try:
            self.mlog("Generating GP4 ...")
            run_cmd([str(GENGP4), str(IMAGE0_DIR)])
            gp4 = TOOLS_DIR / "image0.gp4"
            txt = TOOLS_DIR / "image0.txt"
            if gp4.exists():
                gp4.rename(txt)
            if txt.exists():
                run_cmd([str(FART), str(txt), "-i",
                         'default_id="1"', 'default_id="0"'])
                txt.rename(gp4)

            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            out = OUTPUT_DIR / "manual.pkg"
            if out.exists():
                out.unlink()

            self.mlog("orbis-pub-cmd img_create ...")
            rc = run_visible([str(ORBIS_PLAIN), "img_create", str(gp4), str(out)])
            if rc != 0 or not out.exists():
                self.mlog("❌ build failed")
                return
            try:
                gp4.unlink()
            except Exception:
                pass
            self.mlog(f"✅ Created: {out}")
            messagebox.showinfo("Success", f"Created:\n{out}")
        except Exception as e:
            self.mlog(f"❌ Exception: {e}")


# ----------------------------------------------------------------------------
if __name__ == "__main__":
    app = PSP2PS4App()
    missing = [p for p in (ORBIS, GENGP4, FART, SFO, MAGICK, SEVENZ,
                           PSPDECRYPT, MKISOFS) if not p.exists()]
    if missing:
        app.log("⚠️ Missing tools:")
        for m in missing:
            app.log(f"   - {m}")
    app.mainloop()
