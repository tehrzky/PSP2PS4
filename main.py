"""
PSP 2 PS4 AIO — GUI v2.6 (Redesign)
Modern dark layout: header bar · slim nav rail · step cards · live summary
panel · docked terminal log · gradient build bar.

Build logic is identical to v2.5 — only the presentation layer changed.
"""
import os
import sys
import json
import time
import shutil
import subprocess
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk


# ----------------------------------------------------------------------------
# Paths (hardened against null-byte surprises)
# ----------------------------------------------------------------------------
def _clean(p) -> Path:
    return Path(str(p).replace("\x00", "")).resolve()


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return _clean(Path(sys.executable).parent)
    return _clean(Path(__file__).parent)


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
# Design tokens — tweak these to re-skin the whole app
# ----------------------------------------------------------------------------
BG         = "#0e0f13"   # window background
SIDEBAR    = "#12131a"   # nav rail
SURFACE    = "#171a21"   # cards
SURFACE_2  = "#1e222c"   # card headers / inputs
SURFACE_3  = "#262b38"   # hover / raised
BORDER     = "#2b3040"
BORDER_LT  = "#3d445c"
ACCENT     = "#7c9bff"
ACCENT_HI  = "#aec0ff"
ACCENT_ON  = "#0b0d14"   # text drawn on accent buttons
SELECT     = "#2b3a5e"   # selected list-row tint
TEXT       = "#e9ecf4"
TEXT_DIM   = "#9aa0b4"
TEXT_FAINT = "#626a80"
SUCCESS    = "#4ade80"
WARN       = "#fbbf24"
DANGER     = "#f87171"

RADIUS     = 14
RADIUS_SM  = 10
FONT       = "Segoe UI"
FONT_MONO  = "Cascadia Mono"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def F(size=13, weight="normal", family=FONT):
    return ctk.CTkFont(family=family, size=size, weight=weight)


def ghost(parent, text, command, width=120, height=32, icon=True):
    """Standard secondary button: transparent w/ hairline border."""
    return ctk.CTkButton(
        parent, text=text, command=command,
        width=width, height=height,
        fg_color="transparent", hover_color=SURFACE_3,
        border_width=1, border_color=BORDER,
        text_color=TEXT_DIM, font=F(12),
        corner_radius=RADIUS_SM)


# ----------------------------------------------------------------------------
# Folder READMEs
# ----------------------------------------------------------------------------
FOLDER_READMES = {
    BASE_PKGS_DIR: (
        "base_pkgs/\n==========\n\n"
        "Put your BASE emulator PKGs here.\n"
        "Any *.pkg file you drop in will appear in the GUI list.\n"
        "The filename (without .pkg) becomes the display name.\n"
    ),
    OFFICIAL_DIR: (
        "official_pkgs/\n==============\n\n"
        "Put big untouched OFFICIAL PKGs here.\n"
        "Only the EBOOT.BIN is extracted from these.\n\n"
        "Any *.pkg file you drop in will appear in the GUI list.\n"
    ),
    OVERRIDES_DIR: (
        "overrides/\n==========\n\n"
        "OPTIONAL. Files here OVERWRITE the extracted base PKG inside\n"
        "tools/image0/ before building.\n\n"
        "Use for custom EBOOT.BIN, config-title.txt, icons, or any asset\n"
        "you want inside the final PKG.\n"
    ),
    DLC_DIR: (
        "game_dlc/\n=========\n\n"
        "OPTIONAL. Drop DLC folders here named after the game's TITLE_ID.\n\n"
        "Example:\n  game_dlc/UCES00304/DLC1/...\n"
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


# ----------------------------------------------------------------------------
# Shell helpers
# ----------------------------------------------------------------------------
def run_cmd(cmd, cwd=None):
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
    out = []
    for src, folder in [("base_pkgs", BASE_PKGS_DIR),
                        ("official",  OFFICIAL_DIR)]:
        folder.mkdir(parents=True, exist_ok=True)
        for pkg in sorted(folder.glob("*.pkg")):
            try:
                size = pkg.stat().st_size
            except Exception:
                size = 0
            out.append({"source": src, "name": pkg.stem, "path": pkg, "size": size})
    return out


# ----------------------------------------------------------------------------
# Base lock helpers
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
# Schema form (mini option cards)
# ----------------------------------------------------------------------------
class SchemaForm:
    def __init__(self, parent, schema: dict):
        self.schema = schema
        self.vars = {}
        self._build(parent)

    def _build(self, parent):
        for key, spec in self.schema.items():
            box = ctk.CTkFrame(parent, fg_color=SURFACE_2,
                               corner_radius=RADIUS_SM, border_width=1,
                               border_color=BORDER)
            box.pack(fill="x", pady=5)
            box.grid_columnconfigure(0, weight=1)

            top = ctk.CTkFrame(box, fg_color="transparent")
            top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
            top.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(top, text=spec.get("label", key),
                         font=F(12, "bold"), anchor="w")\
                .grid(row=0, column=0, sticky="w")

            kind = spec.get("type", "text")
            default = spec.get("default", "")

            if kind == "choice":
                values = [c["label"] for c in spec["choices"]]
                l2v = {c["label"]: c["value"] for c in spec["choices"]}
                default_label = next(
                    (c["label"] for c in spec["choices"] if c["value"] == default),
                    values[0] if values else "")
                var = tk.StringVar(value=default_label)
                ctk.CTkOptionMenu(top, values=values, variable=var, width=190,
                                  fg_color=SURFACE_3, button_color=SURFACE_3,
                                  button_hover_color=BORDER_LT)\
                    .grid(row=0, column=1, sticky="e")
                self.vars[key] = ("choice", var, l2v)
            else:
                var = tk.StringVar(value=default)
                ctk.CTkEntry(top, textvariable=var, width=280,
                             fg_color=SURFACE_3, border_color=BORDER)\
                    .grid(row=0, column=1, sticky="e")
                self.vars[key] = ("text", var, None)

            if spec.get("description"):
                ctk.CTkLabel(box, text=spec["description"],
                             font=F(10), text_color=TEXT_FAINT,
                             wraplength=560, justify="left", anchor="w")\
                    .grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))

    def values(self) -> dict:
        out = {}
        for key, (kind, var, l2v) in self.vars.items():
            out[key] = l2v.get(var.get(), var.get()) if kind == "choice" else var.get()
        return out


# ----------------------------------------------------------------------------
# Card — numbered step container
# ----------------------------------------------------------------------------
class Card(ctk.CTkFrame):
    def __init__(self, parent, number, title, subtitle=""):
        super().__init__(parent, corner_radius=RADIUS,
                         fg_color=SURFACE,
                         border_width=1, border_color=BORDER)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color=SURFACE_2,
                              corner_radius=RADIUS, height=46)
        header.grid(row=0, column=0, sticky="ew", padx=1, pady=(1, 0))
        header.grid_propagate(False)
        header.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(header, text=str(number),
                     font=F(12, "bold"), text_color=ACCENT_ON,
                     fg_color=ACCENT, corner_radius=8, width=28, height=28)\
            .grid(row=0, column=0, padx=(14, 10), pady=9)
        ctk.CTkLabel(header, text=title, font=F(14, "bold"), anchor="w")\
            .grid(row=0, column=1, sticky="w")
        if subtitle:
            ctk.CTkLabel(header, text=subtitle, font=F(10),
                         text_color=TEXT_FAINT, anchor="e")\
                .grid(row=0, column=2, sticky="e", padx=16)

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="ew", padx=16, pady=(4, 16))
        self.body.grid_columnconfigure(0, weight=1)


# ----------------------------------------------------------------------------
# PkgList — three-column selectable list with hover
# ----------------------------------------------------------------------------
class PkgList(ctk.CTkFrame):
    HEADERS = ("Source", "Name", "Size")

    def __init__(self, parent, on_select, height=190):
        super().__init__(parent, fg_color=SURFACE_2,
                         corner_radius=RADIUS_SM, border_width=1,
                         border_color=BORDER)
        self.on_select = on_select
        self.selected_index = None
        self.items = []
        self.row_widgets = []

        hdr = ctk.CTkFrame(self, fg_color=SURFACE_3, corner_radius=0, height=30)
        hdr.pack(fill="x", padx=1, pady=(1, 0))
        hdr.pack_propagate(False)
        for i, (txt, w) in enumerate(zip(self.HEADERS, (86, 250, 76))):
            ctk.CTkLabel(hdr, text=txt, width=w, anchor="w",
                         font=F(10, "bold"), text_color=TEXT_DIM)\
                .pack(side="left", padx=(12 if i == 0 else 4, 0))

        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color=SURFACE_2, height=height - 42,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_LT)
        self.scroll.pack(fill="both", expand=True, padx=2, pady=2)

        self.empty = ctk.CTkLabel(
            self.scroll,
            text="No PKGs found.\n\nDrop *.pkg files into base_pkgs/ or official_pkgs/,\nthen click ↻ Rescan.",
            justify="center", text_color=TEXT_FAINT, font=F(11))
        self.empty.pack(pady=28)

    def set_items(self, items):
        for w in self.row_widgets:
            w.destroy()
        self.row_widgets = []
        self.items = items
        self.selected_index = None

        if not items:
            self.empty.pack(pady=28)
            return
        self.empty.pack_forget()
        for idx, item in enumerate(items):
            self._make_row(idx, item)

    def _make_row(self, idx, item):
        row = ctk.CTkFrame(self.scroll, fg_color="transparent",
                           corner_radius=8, height=30)
        row.pack(fill="x", padx=3, pady=2)
        row.pack_propagate(False)

        ctk.CTkLabel(row, text=item["source"], width=86, anchor="w",
                     font=F(11), text_color=TEXT_DIM)\
            .pack(side="left", padx=(10, 4))
        ctk.CTkLabel(row, text=item["name"], width=250, anchor="w",
                     font=F(11))\
            .pack(side="left")
        ctk.CTkLabel(row, text=human_size(item["size"]), width=76, anchor="w",
                     font=F(11), text_color=TEXT_DIM)\
            .pack(side="left")

        def click(_e, i=idx):
            self._select(i)

        def enter(_e, r=row, i=idx):
            if i != self.selected_index:
                r.configure(fg_color=SURFACE_3)

        def leave(_e, r=row, i=idx):
            if i != self.selected_index:
                r.configure(fg_color="transparent")

        for w in [row] + list(row.winfo_children()):
            w.bind("<Button-1>", click)
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
        self.row_widgets.append(row)

    def _select(self, idx):
        self.selected_index = idx
        for i, row in enumerate(self.row_widgets):
            row.configure(fg_color=SELECT if i == idx else "transparent")
        if 0 <= idx < len(self.items):
            self.on_select(self.items[idx])

    def highlight_by_name(self, name):
        for i, item in enumerate(self.items):
            if item["name"] == name:
                self._select(i)
                return


# ----------------------------------------------------------------------------
# Main app
# ----------------------------------------------------------------------------
class PSP2PS4App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PSP 2 PS4 AIO")
        self.configure(fg_color=BG)
        ensure_folders()

        # state
        self.iso_file: Path | None = None
        self.icon_file: Path | None = None
        self.boot_file: Path | None = None
        self.base_pkg_path: Path | None = None
        self.base_pkg_name: str = ""
        self.detected_disc_id: str = ""
        self.detected_title: str = ""
        self.schema = load_schema()
        self.log_collapsed = False
        self.nav_buttons = {}

        self._build_ui()
        self._apply_window_size()

        self.log(f"[init] base_dir = {BASE_DIR}")
        self.log(f"[init] tools    = {TOOLS_DIR}")

        migrate_old_folders(log=self.log)
        self.rescan_pkgs()

        lock = current_extracted_base()
        if lock:
            self.log(f"[init] base already extracted: {lock}")
            self._set_base_ready(lock)

    # ============================================================ UI shell
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=0, minsize=216)  # nav rail
        self.grid_columnconfigure(1, weight=1)               # content
        self.grid_rowconfigure(2, weight=1)                  # pages
        self.grid_rowconfigure(3, weight=0)                  # log
        self.grid_rowconfigure(4, weight=0)                  # build bar

        self._build_sidebar()
        self._build_header()

        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color=BG)
        self.content.grid(row=2, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.pages = {}
        self._build_game_page()
        self._build_manual_page()
        self.show_page("game")

        self._build_log_panel()
        self._build_build_bar()

    def _build_sidebar(self):
        rail = ctk.CTkFrame(self, corner_radius=0, fg_color=SIDEBAR)
        rail.grid(row=0, column=0, rowspan=5, sticky="nsw")
        rail.grid_propagate(False)
        rail.configure(width=216)

        # logo mark
        logo = ctk.CTkFrame(rail, fg_color="transparent")
        logo.pack(pady=(24, 4))
        mark = ctk.CTkLabel(logo, text="P₂₄", font=F(20, "bold"),
                            text_color=ACCENT_ON, fg_color=ACCENT,
                            corner_radius=12, width=48, height=48)
        mark.pack()
        ctk.CTkLabel(rail, text="PSP 2 PS4 AIO", font=F(15, "bold"))\
            .pack(pady=(8, 0))
        ctk.CTkLabel(rail, text="BUILDER  ·  v2.6", font=F(9),
                     text_color=TEXT_FAINT).pack(pady=(2, 22))

        self._nav(rail, "game",   "🎮", "Build PKG",      lambda: self.show_page("game"))
        self._nav(rail, "manual", "🛠", "Manual Builder", lambda: self.show_page("manual"))

        ctk.CTkFrame(rail, fg_color=BORDER, height=1)\
            .pack(fill="x", padx=18, pady=(18, 14))

        side_link = lambda t, c: ghost(rail, t, c, height=34)\
            .pack(fill="x", padx=14, pady=3)
        side_link("⬇  Framework 5.0", self.open_framework)
        side_link("🧹 Cleanup work dir", self.cleanup_workdir)

        ctk.CTkLabel(rail, text="All PKG lists are scanned\nfrom disk at startup.",
                     font=F(9), text_color=TEXT_FAINT, justify="center")\
            .pack(side="bottom", pady=18)

    def _nav(self, parent, key, icon, label, command):
        b = ctk.CTkButton(parent, text=f"{icon}   {label}", command=command,
                          height=42, anchor="w", corner_radius=10,
                          font=F(13), border_width=0)
        b.pack(fill="x", padx=14, pady=3)
        self.nav_buttons[key] = b

    def _set_active_nav(self, key):
        for k, b in self.nav_buttons.items():
            if k == key:
                b.configure(fg_color=SELECT, text_color=ACCENT_HI,
                            hover_color=SELECT)
            else:
                b.configure(fg_color="transparent", text_color=TEXT_DIM,
                            hover_color=SURFACE_3)

    def _build_header(self):
        hdr = ctk.CTkFrame(self, corner_radius=0, fg_color=BG, height=64)
        hdr.grid(row=0, column=1, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(0, weight=1)

        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=20)
        ctk.CTkLabel(left, text="Build PSP Game PKG",
                     font=F(19, "bold"), anchor="w").pack(side="left")
        ctk.CTkLabel(left, text="Turn a PSP .ISO into a PS4-installable PKG.",
                     font=F(11), text_color=TEXT_DIM, anchor="w")\
            .pack(side="left", padx=(14, 0), pady=(5, 0))

        # base status pill (right side of header)
        self.hdr_status = ctk.CTkLabel(
            hdr, text="●  Base not extracted",
            font=F(11, "bold"), text_color=DANGER,
            fg_color=SURFACE, corner_radius=20,
            padx=16, height=34)
        self.hdr_status.grid(row=0, column=1, sticky="e", padx=20)

        ctk.CTkFrame(self, fg_color=BORDER, height=1)\
            .grid(row=1, column=1, sticky="ew")

    def _build_log_panel(self):
        self.log_panel = ctk.CTkFrame(self, fg_color=SIDEBAR,
                                      corner_radius=0, height=160)
        self.log_panel.grid(row=3, column=1, sticky="ew")
        self.log_panel.grid_propagate(False)
        self.log_panel.grid_columnconfigure(0, weight=1)
        self.log_panel.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self.log_panel, fg_color="transparent", height=32)
        head.grid(row=0, column=0, sticky="ew", padx=10)
        head.grid_propagate(False)

        ctk.CTkLabel(head, text="◈ TERMINAL",
                     font=F(10, "bold"), text_color=TEXT_FAINT)\
            .pack(side="left", padx=6)

        ghost(head, "🗑 Clear", self.clear_log, width=76, height=24)\
            .pack(side="right", padx=4, pady=4)
        self.collapse_btn = ghost(head, "▼ Collapse", self.toggle_log,
                                  width=92, height=24)
        self.collapse_btn.pack(side="right", padx=4, pady=4)

        self.log_box = ctk.CTkTextbox(
            self.log_panel, wrap="word",
            font=F(11, family=FONT_MONO),
            fg_color=SIDEBAR, text_color="#b9c8b9",
            border_width=0, corner_radius=0)
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.log_box.configure(state="disabled")
        for tag, col in (("ok", SUCCESS), ("err", DANGER), ("warn", WARN),
                         ("phase", ACCENT_HI), ("dim", TEXT_FAINT)):
            self.log_box.tag_config(tag, foreground=col)

    def _build_build_bar(self):
        bar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=68)
        bar.grid(row=4, column=1, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)

        ctk.CTkFrame(self, fg_color=BORDER, height=1)\
            .grid(row=4 - 1, column=1, sticky="ew")  # hairline above log handled below

        out_wrap = ctk.CTkFrame(bar, fg_color="transparent")
        out_wrap.grid(row=0, column=0, sticky="ew", padx=(20, 10), pady=14)
        ctk.CTkLabel(out_wrap, text="OUTPUT", font=F(9, "bold"),
                     text_color=TEXT_FAINT).pack(anchor="w")
        self.output_preview_bar = ctk.CTkLabel(
            out_wrap, text="—", font=F(12, family=FONT_MONO),
            text_color=TEXT_DIM, anchor="w")
        self.output_preview_bar.pack(anchor="w")

        ghost(bar, "📂  Open output", lambda: self.open_folder(OUTPUT_DIR),
              width=130, height=42)\
            .grid(row=0, column=1, padx=(0, 10), pady=13)

        self.build_btn = ctk.CTkButton(
            bar, text="🚀   BUILD PKG", height=42, width=210,
            font=F(14, "bold"), corner_radius=12,
            fg_color=ACCENT, hover_color=ACCENT_HI, text_color=ACCENT_ON,
            command=self.do_build)
        self.build_btn.grid(row=0, column=2, padx=(0, 20), pady=13)

    def toggle_log(self):
        self.log_collapsed = not self.log_collapsed
        if self.log_collapsed:
            self.log_panel.configure(height=34)
            self.log_box.grid_remove()
            self.collapse_btn.configure(text="▲ Expand")
        else:
            self.log_panel.configure(height=160)
            self.log_box.grid()
            self.collapse_btn.configure(text="▼ Collapse")

    def _apply_window_size(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        win_w = max(1120, min(1280, sw - 120))
        win_h = max(740, min(880, sh - 140))
        x = max(0, (sw - win_w) // 2)
        y = max(0, (sh - win_h) // 2 - 30)
        self.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.minsize(1120, 740)

    def show_page(self, name):
        self._set_active_nav(name)
        for p in self.pages.values():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)

    # ============================================================ game page
    def _build_game_page(self):
        page = ctk.CTkFrame(self.content, corner_radius=0, fg_color=BG)
        self.pages["game"] = page
        page.grid_rowconfigure(0, weight=1)
        page.grid_columnconfigure(0, weight=1)              # step cards
        page.grid_columnconfigure(1, weight=0, minsize=308) # summary rail

        # mode switch row (sits above cards, below header)
        mode_row = ctk.CTkFrame(page, fg_color="transparent", height=44)
        mode_row.grid(row=0, column=0, columnspan=2, sticky="new",
                      padx=(16, 16), pady=(12, 0))
        mode_row.grid_propagate(False)
        self.mode_var = tk.StringVar(value="Game PKG")
        ctk.CTkSegmentedButton(
            mode_row,
            values=["Game PKG", "Emulator PKG"],
            variable=self.mode_var,
            command=lambda v: self._on_mode_change(),
            height=36, corner_radius=10,
            fg_color=SURFACE_2, selected_color=SELECT,
            selected_hover_color=SELECT, unselected_color=SURFACE_2,
            unselected_hover_color=SURFACE_3, text_color=TEXT)\
            .pack(side="left")

        # --- LEFT: scrolling step cards (offset below mode row) ---
        left = ctk.CTkScrollableFrame(
            page, corner_radius=0, fg_color=BG,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_LT)
        left.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=(64, 12))
        left.grid_columnconfigure(0, weight=1)

        # Card 1 — Base PKG
        c1 = Card(left, "1", "Base PKG", "emulator base for the build")
        c1.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        toolbar = ctk.CTkFrame(c1.body, fg_color="transparent")
        toolbar.pack(fill="x", pady=(2, 8))
        ghost(toolbar, "📂 base_pkgs/", lambda: self.open_folder(BASE_PKGS_DIR),
              width=128).pack(side="left", padx=(0, 6))
        ghost(toolbar, "📂 official_pkgs/", lambda: self.open_folder(OFFICIAL_DIR),
              width=142).pack(side="left", padx=(0, 6))
        ctk.CTkButton(toolbar, text="↻ Rescan", width=92,
                      height=32, corner_radius=RADIUS_SM,
                      fg_color=SURFACE_3, hover_color=BORDER_LT,
                      text_color=TEXT, font=F(12),
                      command=self.rescan_pkgs).pack(side="right")

        self.pkg_list = PkgList(c1.body, on_select=self._on_pkg_select, height=196)
        self.pkg_list.pack(fill="x", pady=(0, 10))

        btn_row = ctk.CTkFrame(c1.body, fg_color="transparent")
        btn_row.pack(fill="x")
        ghost(btn_row, "🔍 Preview base", self.preview_base, width=138)\
            .pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="⬇  Extract Base PKG", width=168, height=34,
                      corner_radius=RADIUS_SM, font=F(12, "bold"),
                      fg_color=SELECT, hover_color=BORDER_LT,
                      text_color=ACCENT_HI, command=self.force_extract_base)\
            .pack(side="left")

        # Card 2 — Overrides
        c2 = Card(left, "2", "Overrides", "optional")
        c2.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.use_overrides = tk.BooleanVar(value=False)
        row2 = ctk.CTkFrame(c2.body, fg_color="transparent")
        row2.pack(fill="x")
        ctk.CTkCheckBox(row2, text="Copy files from overrides/ into the base",
                        variable=self.use_overrides, font=F(12),
                        fg_color=ACCENT, hover_color=ACCENT_HI)\
            .pack(side="left")
        ghost(row2, "📂 Open", lambda: self.open_folder(OVERRIDES_DIR), width=84)\
            .pack(side="right")

        # Card 3 — Game ISO
        self.c3 = Card(left, "3", "Game ISO", "your PSP game image")
        self.c3.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self.iso_label = ctk.CTkLabel(self.c3.body, text="No ISO selected",
                                      font=F(12), text_color=DANGER, anchor="w")
        self.iso_label.pack(anchor="w", pady=(2, 8))
        row3 = ctk.CTkFrame(self.c3.body, fg_color="transparent")
        row3.pack(fill="x")
        ctk.CTkButton(row3, text="Browse ISO…", width=140, height=34,
                      corner_radius=RADIUS_SM, font=F(12, "bold"),
                      fg_color=SURFACE_3, hover_color=BORDER_LT,
                      text_color=TEXT, command=self.pick_iso).pack(side="left")
        ghost(row3, "📂 game_dlc/", lambda: self.open_folder(DLC_DIR), width=126)\
            .pack(side="right")
        self.output_preview = ctk.CTkLabel(self.c3.body, text="",
                                           font=F(11, family=FONT_MONO),
                                           text_color=SUCCESS, anchor="w")
        self.output_preview.pack(anchor="w", pady=(10, 0))

        # Card 4 — Decrypt method
        self.c4 = Card(left, "4", "Decrypt Method")
        self.c4.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        self.decrypt_var = tk.IntVar(value=1)
        for txt, val in (("Decrypt & rebuild ISO — safest", 1),
                         ("Swap EBOOT — fallback if decrypt fails", 2),
                         ("Skip — assume already decrypted (fast, may not work)", 3)):
            ctk.CTkRadioButton(self.c4.body, text=txt, variable=self.decrypt_var,
                               value=val, font=F(12),
                               fg_color=ACCENT, hover_color=ACCENT_HI)\
                .pack(anchor="w", pady=3)

        # Card 5 — Emulator options
        self.c5 = Card(left, "5", "Emulator Options", "from emulator_options.json")
        self.c5.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        self.schema_form = SchemaForm(self.c5.body, self.schema)

        # Card 6 — Icons
        self.c6 = Card(left, "6", "Icon / Background", "optional")
        self.c6.grid(row=5, column=0, sticky="ew")
        self.icon_var = tk.IntVar(value=2)
        ctk.CTkRadioButton(self.c6.body, text="Use default icons",
                           variable=self.icon_var, value=2, font=F(12),
                           fg_color=ACCENT, hover_color=ACCENT_HI)\
            .pack(anchor="w", pady=3)
        ctk.CTkLabel(self.c6.body,
                     text="tools/pic/icon0.png · pic1.png · save_data.png",
                     font=F(10), text_color=TEXT_FAINT, anchor="w")\
            .pack(anchor="w", padx=26)
        ctk.CTkRadioButton(self.c6.body, text="Set custom icon / background",
                           variable=self.icon_var, value=1, font=F(12),
                           fg_color=ACCENT, hover_color=ACCENT_HI)\
            .pack(anchor="w", pady=(8, 3))

        row6 = ctk.CTkFrame(self.c6.body, fg_color="transparent")
        row6.pack(fill="x", padx=26, pady=2)
        ctk.CTkButton(row6, text="Choose Icon…", width=140, height=32,
                      corner_radius=RADIUS_SM, font=F(12),
                      fg_color=SURFACE_3, hover_color=BORDER_LT,
                      text_color=TEXT, command=self.pick_icon)\
            .pack(side="left", padx=(0, 10))
        self.icon_label = ctk.CTkLabel(row6, text="(none)", font=F(11),
                                       text_color=TEXT_FAINT, anchor="w")
        self.icon_label.pack(side="left")

        row6b = ctk.CTkFrame(self.c6.body, fg_color="transparent")
        row6b.pack(fill="x", padx=26, pady=2)
        ctk.CTkButton(row6b, text="Choose Boot Image…", width=160, height=32,
                      corner_radius=RADIUS_SM, font=F(12),
                      fg_color=SURFACE_3, hover_color=BORDER_LT,
                      text_color=TEXT, command=self.pick_boot)\
            .pack(side="left", padx=(0, 10))
        self.boot_label = ctk.CTkLabel(row6b, text="(none)", font=F(11),
                                       text_color=TEXT_FAINT, anchor="w")
        self.boot_label.pack(side="left")

        # --- RIGHT: summary rail ---
        right = ctk.CTkFrame(page, fg_color=SURFACE, corner_radius=RADIUS,
                             border_width=1, border_color=BORDER)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=(64, 12))
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="BUILD SUMMARY", font=F(10, "bold"),
                     text_color=TEXT_FAINT, anchor="w")\
            .grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))

        self.progress = ctk.CTkProgressBar(right, height=8,
                                           progress_color=ACCENT,
                                           fg_color=SURFACE_3,
                                           corner_radius=6)
        self.progress.grid(row=1, column=0, sticky="ew", padx=16)
        self.progress.set(0)
        self.phase_label = ctk.CTkLabel(right, text="Idle", font=F(11),
                                        text_color=TEXT_DIM, anchor="w")
        self.phase_label.grid(row=2, column=0, sticky="ew", padx=16, pady=(6, 0))

        sep = ctk.CTkFrame(right, fg_color=BORDER, height=1)
        sep.grid(row=3, column=0, sticky="ew", padx=16, pady=(14, 12))

        def kv(parent, row, k):
            ctk.CTkLabel(parent, text=k, font=F(10), text_color=TEXT_FAINT,
                         anchor="w").grid(row=row, column=0, sticky="nw",
                                          padx=(16, 8), pady=3)
            lbl = ctk.CTkLabel(parent, text="—", font=F(11), anchor="w",
                               wraplength=190, justify="left")
            lbl.grid(row=row, column=1, sticky="w", padx=(0, 16), pady=3)
            return lbl

        right.grid_columnconfigure(1, weight=1)
        self.status_base = kv(right, 4, "BASE")
        self.status_iso = kv(right, 5, "ISO")
        self.status_out = kv(right, 6, "OUTPUT")

        sep2 = ctk.CTkFrame(right, fg_color=BORDER, height=1)
        sep2.grid(row=7, column=0, columnspan=2, sticky="ew",
                  padx=16, pady=(12, 12))

        ctk.CTkLabel(right, text="QUICK OPEN", font=F(10, "bold"),
                     text_color=TEXT_FAINT, anchor="w")\
            .grid(row=8, column=0, columnspan=2, sticky="ew",
                  padx=16, pady=(0, 8))

        grid_btns = ctk.CTkFrame(right, fg_color="transparent")
        grid_btns.grid(row=9, column=0, columnspan=2, sticky="ew",
                       padx=16, pady=(0, 16))
        grid_btns.grid_columnconfigure((0, 1), weight=1)
        quick = [("📦 output", OUTPUT_DIR), ("🧱 base_pkgs", BASE_PKGS_DIR),
                 ("🏛 official", OFFICIAL_DIR), ("🔧 overrides", OVERRIDES_DIR),
                 ("🎴 game_dlc", DLC_DIR), ("🗂 image0", IMAGE0_DIR)]
        for i, (label, path) in enumerate(quick):
            ghost(grid_btns, label, lambda p=path: self.open_folder(p),
                  height=34).grid(row=i // 2, column=i % 2, sticky="ew",
                                  padx=(0, 6) if i % 2 == 0 else (6, 0),
                                  pady=3)

        # base status (also mirrored into header pill)
        self.base_status = self.hdr_status

    # ============================================================ manual page
    def _build_manual_page(self):
        page = ctk.CTkFrame(self.content, corner_radius=0, fg_color=BG)
        self.pages["manual"] = page
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(page, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 10))
        ctk.CTkLabel(toolbar, text="Manual PKG Builder", font=F(18, "bold"))\
            .pack(side="left")
        ctk.CTkLabel(toolbar,
                     text="Advanced — put anything in tools/image0/, then build.",
                     font=F(11), text_color=TEXT_DIM)\
            .pack(side="left", padx=(14, 0), pady=(4, 0))
        ghost(toolbar, "📂 Open tools/image0/",
              lambda: self.open_folder(IMAGE0_DIR), width=160, height=36)\
            .pack(side="right", padx=6)
        ctk.CTkButton(toolbar, text="🚀  Build manual.pkg", width=190, height=36,
                      corner_radius=RADIUS_SM, font=F(12, "bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HI,
                      text_color=ACCENT_ON, command=self.do_manual_build)\
            .pack(side="right")

        self.manual_log = ctk.CTkTextbox(page, wrap="word",
                                         font=F(11, family=FONT_MONO),
                                         fg_color=SIDEBAR, text_color="#b9c8b9",
                                         corner_radius=RADIUS)
        self.manual_log.grid(row=1, column=0, sticky="nsew",
                             padx=20, pady=(0, 16))
        self.manual_log.configure(state="disabled")

    # ============================================================ logging
    def log(self, msg):
        self.after(0, lambda m=msg: self._log_main(m))

    def _log_main(self, msg):
        try:
            self.log_box.configure(state="normal")
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
            else:
                tag = None
            self.log_box.insert("end", msg + "\n", (tag,) if tag else ())
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    # ============================================================ progress
    def set_progress(self, pct: int, label: str = ""):
        self.after(0, lambda: self._set_progress(pct, label))

    def _set_progress(self, pct, label):
        try:
            self.progress.set(pct / 100.0)
            if label:
                self.phase_label.configure(text=label)
        except Exception:
            pass

    # ============================================================ helpers
    def ask_main(self, prompt, title="Input", integer=False,
                 minvalue=1, maxvalue=9999):
        box = {}
        done = threading.Event()

        def run():
            try:
                if integer:
                    box["v"] = simpledialog.askinteger(
                        title, prompt, minvalue=minvalue, maxvalue=maxvalue)
                else:
                    box["v"] = simpledialog.askstring(title, prompt)
            finally:
                done.set()

        self.after(0, run)
        done.wait()
        return box.get("v")

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
        self.hdr_status.configure(text="●  Base not extracted",
                                  text_color=DANGER)
        self.status_base.configure(text="—")
        self.set_progress(0, "Idle")
        self.log("[cleanup] tools/image0 wiped.")

    # ============================================================ scan
    def rescan_pkgs(self):
        items = scan_base_pkgs()
        self.pkg_list.set_items(items)
        self.log(f"[scan] {len(items)} PKG(s) found "
                 f"(base_pkgs: {sum(1 for i in items if i['source']=='base_pkgs')}, "
                 f"official: {sum(1 for i in items if i['source']=='official')})")

    def _on_pkg_select(self, item):
        self.base_pkg_path = item["path"]
        self.base_pkg_name = item["name"]
        self.status_base.configure(text=item["name"])
        self._update_output_preview()

    def _on_mode_change(self):
        is_game = self.mode_var.get() == "Game PKG"
        for c in (self.c3, self.c4, self.c5, self.c6):
            c.grid() if is_game else c.grid_remove()
        self.build_btn.configure(
            text="🚀   BUILD PKG" if is_game else "🔨   BUILD EMULATOR PKG")
        self._update_output_preview()

    def _update_output_preview(self):
        disc = self.detected_disc_id or "<DISC_ID>"
        title = self.detected_title or "<Title>"
        base = self.base_pkg_name or "<BasePKG>"
        if self.mode_var.get() == "Game PKG":
            txt = f"{safe_name(title)}_{safe_name(disc)}_{base}.pkg"
        else:
            txt = f"{base}_EMU_<TITLE_ID>.pkg"
        self.output_preview.configure(text=f"→ {txt}")
        self.output_preview_bar.configure(text=txt)
        self.status_out.configure(text=txt)

    def _set_base_ready(self, name):
        self.hdr_status.configure(text=f"●  Ready — {name}",
                                  text_color=SUCCESS)

    # ============================================================ pickers
    def pick_iso(self):
        f = filedialog.askopenfilename(
            title="Select PSP game ISO",
            filetypes=[("ISO", "*.iso"), ("All", "*.*")])
        if not f:
            return
        try:
            p = _clean(f)
        except Exception as e:
            messagebox.showerror("Bad path", str(e))
            return
        self.iso_file = p
        self.iso_label.configure(text=str(p), text_color=SUCCESS)
        self.status_iso.configure(text=p.name)
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
        if not f:
            return
        self.icon_file = _clean(f)
        self.icon_label.configure(text=self.icon_file.name, text_color=SUCCESS)
        self.icon_var.set(1)

    def pick_boot(self):
        f = filedialog.askopenfilename(
            title="Select boot image",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All", "*.*")])
        if not f:
            return
        self.boot_file = _clean(f)
        self.boot_label.configure(text=self.boot_file.name, text_color=SUCCESS)
        self.icon_var.set(1)

    # ============================================================ extraction
    def preview_base(self):
        if not self.base_pkg_path or not self.base_pkg_path.exists():
            messagebox.showwarning("No base", "Select a PKG from the list first.")
            return
        threading.Thread(target=self._extract_thread,
                         args=(self.base_pkg_path, self.base_pkg_name, True),
                         daemon=True).start()

    def force_extract_base(self):
        if not self.base_pkg_path or not self.base_pkg_path.exists():
            messagebox.showwarning("No base", "Select a PKG from the list first.")
            return
        threading.Thread(target=self._extract_thread,
                         args=(self.base_pkg_path, self.base_pkg_name, False),
                         daemon=True).start()

    def _extract_thread(self, pkg: Path, name: str, open_after: bool):
        try:
            self.set_progress(10, f"Extracting {name}...")
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

            write_lock(name)
            self.after(0, lambda: self._set_base_ready(name))
            self.set_progress(30, f"{name} extracted")
            self.log(f"✅ Base extracted: {name}")

            if open_after:
                self.after(0, lambda: self.open_folder(IMAGE0_DIR))
        except Exception as e:
            self.log(f"❌ Extract error: {e}")
            self.set_progress(0, "Failed")

    # ============================================================ build
    def do_build(self):
        if self.base_pkg_path is None:
            messagebox.showerror("No base", "Select a base PKG first.")
            return
        if self.mode_var.get() == "Game PKG":
            if not self.iso_file or not self.iso_file.exists():
                messagebox.showerror("No ISO", "Pick a game ISO first.")
                return
            threading.Thread(target=self._build_game_thread, daemon=True).start()
        else:
            threading.Thread(target=self._build_emu_thread, daemon=True).start()

    def _ensure_base_extracted(self) -> bool:
        if image0_looks_valid() and current_extracted_base() == self.base_pkg_name:
            self.log(f"[build] base already extracted: {self.base_pkg_name}")
            return True
        self.log(f"[build] extracting base first: {self.base_pkg_name}")
        self.set_progress(5, f"Extracting {self.base_pkg_name}...")
        rmtree(IMAGE0_DIR)
        IMAGE0_DIR.mkdir(parents=True, exist_ok=True)
        rc = run_visible([str(ORBIS), "img_extract",
                          "--passcode", "00000000000000000000000000000000",
                          str(self.base_pkg_path), str(TOOLS_DIR)])
        if rc != 0:
            self.log(f"❌ img_extract failed (rc={rc})")
            return False

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
                rmtree(d)

        write_lock(self.base_pkg_name)
        self.after(0, lambda: self._set_base_ready(self.base_pkg_name))
        self.log(f"✅ Base extracted: {self.base_pkg_name}")
        return True

    # ---- Game build ----
    def _build_game_thread(self):
        try:
            iso = self.iso_file
            if "\x00" in str(iso):
                self.log("❌ ISO path invalid (null byte)")
                return

            if not self._ensure_base_extracted():
                self.set_progress(0, "Failed")
                return

            self.set_progress(35, "Reading ISO param.sfo...")
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

            self.set_progress(40, "Patching param.sfo...")
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
            self.set_progress(45, "Decrypting game image...")
            if m == 1:
                if not self._decrypt_mkiso(iso, game_dir, disc_id):
                    self.log("⚠️ decrypt failed — falling back to swap")
                    self._swap(iso, game_dir, disc_id)
            elif m == 2:
                self._swap(iso, game_dir, disc_id)
            else:
                self._skip_copy(iso, game_dir, disc_id)

            self.set_progress(72, "Applying emulator options...")
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
            self.log(traceback.format_exc())
            self.set_progress(0, "Failed")

    # ---- Emulator build ----
    def _build_emu_thread(self):
        try:
            if not self._ensure_base_extracted():
                self.set_progress(0, "Failed")
                return

            self.set_progress(40, "Preparing emulator PKG...")
            self.log("--- Building EMULATOR PKG ---")
            sfo = IMAGE0_DIR / "sce_sys" / "param.sfo"
            if not sfo.exists():
                self.log("❌ param.sfo missing")
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

        self.set_progress(52, "Extracting ISO...")
        self.log("Extracting ISO with 7z ...")
        run_cmd([str(SEVENZ), "x", str(iso), f"-o{tmp}", "-r", "-aoa"])

        eboot = tmp / "PSP_GAME" / "SYSDIR" / "EBOOT.BIN"
        if not eboot.exists():
            self.log("EBOOT.BIN missing inside ISO")
            rmtree(tmp)
            return False

        self.set_progress(58, "Decrypting EBOOT...")
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
        self.set_progress(64, "Building ISO...")
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
        self.set_progress(80, "Generating GP4...")
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

        self.set_progress(88, "Building PKG...")
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

        self.set_progress(100, f"Done — {final.name}")
        self.log(f"✅ PKG created: {final.name}  ({size_mb} MB)")
        messagebox.showinfo("Success", f"PKG created:\n{final}")

    # ============================================================ manual build
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
