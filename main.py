"""
PSP 2 PS4 AIO - GUI
Builds a PS4-installable PKG from a PSP .ISO, or extracts/builds custom
emulator PKGs. Uses the toolchain in ./tools/.

Author: tehrzky  (GUI rewrite)
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
# Paths (work whether running as .py or frozen .exe)
# ----------------------------------------------------------------------------
def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent

BASE_DIR        = base_dir()
TOOLS_DIR       = BASE_DIR / "tools"
IMAGE0_DIR      = TOOLS_DIR / "image0"
BASE_PKGS_DIR   = BASE_DIR / "base_pkgs"
OFFICIAL_DIR    = BASE_DIR / "official_pkgs"
OVERRIDES_DIR   = BASE_DIR / "overrides"
DLC_DIR         = BASE_DIR / "game_dlc"
OUTPUT_DIR      = BASE_DIR / "output_pkgs"
SCHEMA_FILE     = BASE_DIR / "emulator_options.json"

ORBIS           = TOOLS_DIR / "orbis-pub-cmd-keystone.exe"
ORBIS_PLAIN     = TOOLS_DIR / "orbis-pub-cmd.exe"
GENGP4          = TOOLS_DIR / "gengp4-patched.exe"
FART            = TOOLS_DIR / "fart.exe"
SFO             = TOOLS_DIR / "sfo.exe"
MAGICK          = TOOLS_DIR / "magick.exe"
SEVENZ          = TOOLS_DIR / "7z.exe"
PSPDECRYPT      = TOOLS_DIR / "pspdecrypt.exe"
MKISOFS         = TOOLS_DIR / "mkisofs.exe"
ISOINFO         = TOOLS_DIR / "cdrtools" / "isoinfo.exe"
AWK_NL          = TOOLS_DIR / "awk" / "nl.exe"
AWK             = TOOLS_DIR / "awk" / "awk.exe"
SFOINFO         = TOOLS_DIR / "SFOInfo.exe"

# ----------------------------------------------------------------------------
# Base emulators
# ----------------------------------------------------------------------------
BASE_EMULATORS = {
    "Killzone v1 (FW 5.00)":               "KillzoneV1",
    "Resistance v1 + Keystone (FW 9.00+)": "ResistanceV1",
    "Resistance v2 (FW 5.00+)":            "ResistanceV2",
    "Custom Emulator (tools/emulator/custom.pkg)": "custom",
}

FOLDER_READMES = {
    BASE_PKGS_DIR: (
        "base_pkgs/\n"
        "==========\n\n"
        "Put small base emulator PKGs here.\n\n"
        "Expected files (case-sensitive):\n"
        "  KillzoneV1.pkg\n"
        "  ResistanceV1.pkg\n"
        "  ResistanceV2.pkg\n"
        "  custom.pkg\n\n"
        "These are the emulator PKGs shipped with PSP2PS4.\n"
    ),
    OFFICIAL_DIR: (
        "official_pkgs/\n"
        "==============\n\n"
        "Put big untouched official PKGs here (the ones shared online).\n\n"
        "We only extract the EBOOT.BIN from these — everything else is ignored.\n"
        "This lets you build a PKG using the emulator version inside the\n"
        "official release.\n\n"
        "Filenames can be anything ending in .pkg\n"
    ),
    OVERRIDES_DIR: (
        "overrides/\n"
        "==========\n\n"
        "OPTIONAL. Files here OVERWRITE the extracted base PKG inside\n"
        "tools/image0/ before building.\n\n"
        "Use this for:\n"
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

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def ensure_folders():
    for d, readme in FOLDER_READMES.items():
        d.mkdir(parents=True, exist_ok=True)
        r = d / "README.txt"
        if not r.exists():
            r.write_text(readme, encoding="utf-8")

def migrate_old_folders(log=None):
    """Move contents from old folder names to new ones (once)."""
    migrations = [
        (BASE_DIR / "pkgemulatorhere",  BASE_PKGS_DIR),
        (BASE_DIR / "putemulatorhere",  OVERRIDES_DIR),
        (BASE_DIR / "putgamedlchere",   DLC_DIR),
        (BASE_DIR / "pkg",              OUTPUT_DIR),
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
    # built-in fallback
    return {
        "texcachemode": {
            "label": "Texture cache mode",
            "description": "Controls how the emulator handles the PSP texture cache.",
            "type": "choice",
            "placeholder": "#--texcachemode=",
            "default": "skip",
            "choices": [
                {"value": "skip",            "label": "skip (recommended default)"},
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


# ----------------------------------------------------------------------------
# Schema-driven form builder
# ----------------------------------------------------------------------------
class SchemaForm:
    """Builds widgets from emulator_options.json and reads their values."""

    def __init__(self, parent, schema: dict):
        self.schema = schema
        self.vars: dict = {}
        self._build(parent)

    def _build(self, parent):
        for key, spec in self.schema.items():
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            frame.pack(fill="x", pady=4)

            top = ctk.CTkFrame(frame, fg_color="transparent")
            top.pack(fill="x")
            ctk.CTkLabel(top, text=spec.get("label", key),
                         font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
            if spec.get("description"):
                ctk.CTkLabel(top, text=spec["description"],
                             font=ctk.CTkFont(size=10),
                             text_color="#aaaaaa",
                             wraplength=600, justify="left").pack(anchor="w")

            kind = spec.get("type", "text")
            default = spec.get("default", "")

            if kind == "choice":
                values = [c["label"] for c in spec["choices"]]
                label_to_value = {c["label"]: c["value"] for c in spec["choices"]}
                default_label = next(
                    (c["label"] for c in spec["choices"] if c["value"] == default),
                    values[0] if values else "",
                )
                var = tk.StringVar(value=default_label)
                ctk.CTkOptionMenu(frame, values=values, variable=var,
                                  width=400).pack(anchor="w", pady=(2, 0))
                self.vars[key] = ("choice", var, label_to_value)
            else:  # text
                var = tk.StringVar(value=default)
                ctk.CTkEntry(frame, textvariable=var, width=400).pack(anchor="w", pady=(2, 0))
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
# Main Application
# ----------------------------------------------------------------------------
class PSP2PS4App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PSP 2 PS4 AIO — GUI")
        self.geometry("1020x760")
        self.minsize(900, 640)

        ensure_folders()

        # runtime state
        self.iso_file: Path | None = None
        self.icon_file: Path | None = None
        self.boot_file: Path | None = None
        self.base_pkg_path: Path | None = None
        self.base_pkg_name: str = ""
        self.schema = load_schema()

        self._build_ui()
        migrate_old_folders(log=self.log)

    # -------------------------------------------------------------- UI shell
    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=240, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text="PSP 2 PS4 AIO",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(24, 2))
        ctk.CTkLabel(sidebar, text="V2.5 GUI",
                     font=ctk.CTkFont(size=11)).pack(pady=(0, 20))

        ctk.CTkButton(sidebar, text="🎮  Build PSP Game PKG",
                      command=lambda: self.show_page("game")).pack(pady=6, padx=16, fill="x")
        ctk.CTkButton(sidebar, text="📦  Manual PKG Builder",
                      command=lambda: self.show_page("manual")).pack(pady=6, padx=16, fill="x")

        ctk.CTkLabel(sidebar, text="", height=16).pack()

        ctk.CTkButton(sidebar, text="📂  base_pkgs/",
                      fg_color="transparent", border_width=1,
                      command=lambda: self.open_folder(BASE_PKGS_DIR)).pack(pady=3, padx=16, fill="x")
        ctk.CTkButton(sidebar, text="📂  official_pkgs/",
                      fg_color="transparent", border_width=1,
                      command=lambda: self.open_folder(OFFICIAL_DIR)).pack(pady=3, padx=16, fill="x")
        ctk.CTkButton(sidebar, text="📂  overrides/",
                      fg_color="transparent", border_width=1,
                      command=lambda: self.open_folder(OVERRIDES_DIR)).pack(pady=3, padx=16, fill="x")
        ctk.CTkButton(sidebar, text="📂  game_dlc/",
                      fg_color="transparent", border_width=1,
                      command=lambda: self.open_folder(DLC_DIR)).pack(pady=3, padx=16, fill="x")
        ctk.CTkButton(sidebar, text="📂  output_pkgs/",
                      fg_color="transparent", border_width=1,
                      command=lambda: self.open_folder(OUTPUT_DIR)).pack(pady=3, padx=16, fill="x")

        ctk.CTkButton(sidebar, text="⬇️  Install Framework 5.0",
                      fg_color="transparent", border_width=1,
                      command=self.open_framework).pack(pady=(16, 3), padx=16, fill="x")

        ctk.CTkButton(sidebar, text="🧹  Cleanup work dir",
                      fg_color="#8B0000", hover_color="#5a0000",
                      command=self.cleanup_workdir).pack(side="bottom", pady=12, padx=16, fill="x")

        self.content = ctk.CTkFrame(self, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.pages = {}
        self._build_game_page()
        self._build_manual_page()
        self.show_page("game")

    def show_page(self, name):
        for p in self.pages.values():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)

    # ---------------------------------------------------------- GAME PAGE
    def _build_game_page(self):
        page = ctk.CTkScrollableFrame(self.content, corner_radius=0)
        self.pages["game"] = page

        # Title
        head = ctk.CTkFrame(page, fg_color="transparent")
        head.pack(fill="x", pady=(10, 4), padx=12)
        ctk.CTkLabel(head, text="Build PSP Game PKG",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(head, text="Turn a PSP .ISO into a PS4-installable PKG",
                     font=ctk.CTkFont(size=12)).pack(anchor="w")

        # Mode toggle
        mode_section = self._section(page, "Mode", "")
        self.mode_var = tk.StringVar(value="game")
        ctk.CTkRadioButton(mode_section, text="Build Game PKG from ISO",
                           variable=self.mode_var, value="game",
                           command=self._on_mode_change).pack(anchor="w", pady=2)
        ctk.CTkRadioButton(mode_section, text="Build Emulator PKG (advanced, no ISO)",
                           variable=self.mode_var, value="emu",
                           command=self._on_mode_change).pack(anchor="w", pady=2)

        # Step 1 — Base PKG
        s1 = self._section(page, "1. Base PKG",
                           "Base PKG name is added to the output filename.")
        self.base_var = tk.StringVar(value=list(BASE_EMULATORS.keys())[0])
        self.base_menu = ctk.CTkOptionMenu(s1, values=self._base_menu_values(),
                                           variable=self.base_var, width=480,
                                           command=self._on_base_change)
        self.base_menu.pack(anchor="w", pady=4)

        row1 = ctk.CTkFrame(s1, fg_color="transparent")
        row1.pack(anchor="w", pady=4)
        ctk.CTkButton(row1, text="Extract Base PKG",
                      command=self.do_extract_emulator).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row1, text="↻ Rescan",
                      width=90,
                      command=self.rescan_official).pack(side="left")

        self.base_status = ctk.CTkLabel(s1, text="Not extracted yet",
                                        text_color="#ff8080")
        self.base_status.pack(anchor="w", pady=(4, 2))
        self.output_preview = ctk.CTkLabel(s1, text="",
                                           font=ctk.CTkFont(size=11),
                                           text_color="#8fe388")
        self.output_preview.pack(anchor="w")

        # Step 2 — Overrides
        s2 = self._section(page, "2. Optional: overrides/",
                           "Files here OVERWRITE the extracted base PKG.")
        self.use_overrides = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(s2, text="Copy files from overrides/ (overwrites base)",
                        variable=self.use_overrides).pack(anchor="w", pady=2)
        ctk.CTkLabel(s2,
                     text="⚠️  Use for custom EBOOT.BIN, config-title.txt, icons.",
                     text_color="#ffcc66").pack(anchor="w")
        ctk.CTkButton(s2, text="Open overrides/ folder",
                      fg_color="transparent", border_width=1,
                      command=lambda: self.open_folder(OVERRIDES_DIR)).pack(anchor="w", pady=4)

        # Step 3 — Game ISO
        self.iso_section = self._section(page, "3. Game ISO",
                                         "Pick your PSP game's .ISO file.")
        self.iso_label = ctk.CTkLabel(self.iso_section, text="No ISO selected",
                                      text_color="#ff8080")
        self.iso_label.pack(anchor="w", pady=2)
        ctk.CTkButton(self.iso_section, text="Browse ISO...",
                      command=self.pick_iso).pack(anchor="w", pady=4)

        # Step 4 — Decrypt
        self.decrypt_section = self._section(page, "4. Decrypt Method", "")
        self.decrypt_var = tk.IntVar(value=1)
        ctk.CTkRadioButton(self.decrypt_section,
                           text="Decrypt & rebuild ISO  — safest",
                           variable=self.decrypt_var, value=1).pack(anchor="w", pady=2)
        ctk.CTkRadioButton(self.decrypt_section,
                           text="Swap EBOOT (fallback) — use if decrypt fails",
                           variable=self.decrypt_var, value=2).pack(anchor="w", pady=2)
        ctk.CTkRadioButton(self.decrypt_section,
                           text="Skip decryption — assume already decrypted (fast, may not work)",
                           variable=self.decrypt_var, value=3).pack(anchor="w", pady=2)

        # Step 5 — Emulator options (schema)
        self.opts_section = self._section(page, "5. Emulator Options",
                                          "Loaded from emulator_options.json. Edit that file to add flags.")
        self.schema_form = SchemaForm(self.opts_section, self.schema)

        # Step 6 — Icon
        self.icon_section = self._section(page, "6. Icon / Background", "")
        self.icon_var = tk.IntVar(value=2)
        ctk.CTkRadioButton(self.icon_section,
                           text="Use default icons",
                           variable=self.icon_var, value=2).pack(anchor="w", pady=2)
        ctk.CTkLabel(self.icon_section,
                     text="(tools/pic/icon0.png, pic1.png, save_data.png)",
                     text_color="#aaaaaa",
                     font=ctk.CTkFont(size=10)).pack(anchor="w", padx=24)
        ctk.CTkRadioButton(self.icon_section,
                           text="Set custom icon / background",
                           variable=self.icon_var, value=1).pack(anchor="w", pady=(6, 2))

        self.icon_label = ctk.CTkLabel(self.icon_section, text="No icon selected")
        self.icon_label.pack(anchor="w", padx=24, pady=2)
        ctk.CTkButton(self.icon_section, text="Choose Icon...",
                      command=self.pick_icon).pack(anchor="w", padx=24, pady=2)

        self.boot_label = ctk.CTkLabel(self.icon_section, text="No boot image selected")
        self.boot_label.pack(anchor="w", padx=24, pady=2)
        ctk.CTkButton(self.icon_section, text="Choose Boot Image...",
                      command=self.pick_boot).pack(anchor="w", padx=24, pady=2)

        # Build button
        self.build_btn = ctk.CTkButton(
            page, text="🚀  BUILD PKG", height=46,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self.do_build)
        self.build_btn.pack(fill="x", padx=20, pady=20)

        # Log
        s9 = self._section(page, "Log", "")
        self.log_box = ctk.CTkTextbox(s9, height=200, wrap="word")
        self.log_box.pack(fill="both", expand=True, pady=4)
        self.log_box.configure(state="disabled")

    def _section(self, parent, title, subtitle=""):
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(frame, text=title,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 0))
        if subtitle:
            ctk.CTkLabel(frame, text=subtitle,
                         font=ctk.CTkFont(size=11),
                         text_color="#aaaaaa",
                         wraplength=700, justify="left").pack(anchor="w", padx=12, pady=(0, 6))
        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=(0, 10))
        return inner

    # --------------------------------------------------------- MANUAL PAGE
    def _build_manual_page(self):
        page = ctk.CTkScrollableFrame(self.content, corner_radius=0)
        self.pages["manual"] = page

        ctk.CTkLabel(page, text="Manual PKG Builder",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", pady=(10, 4), padx=12)
        ctk.CTkLabel(page,
                     text=("For advanced users. Put any files in tools/image0/ "
                           "then click Build. No ISO processing, no patching — "
                           "just pack whatever is there into a .pkg."),
                     wraplength=800, justify="left").pack(anchor="w", padx=12)

        ctk.CTkButton(page, text="Open tools/image0/ folder",
                      command=lambda: self.open_folder(IMAGE0_DIR)).pack(anchor="w", padx=12, pady=8)
        ctk.CTkButton(page, text="🚀  BUILD output_pkgs/manual.pkg",
                      height=44, font=ctk.CTkFont(size=15, weight="bold"),
                      command=self.do_manual_build).pack(anchor="w", padx=12, pady=8)

        self.manual_log = ctk.CTkTextbox(page, height=260, wrap="word")
        self.manual_log.pack(fill="both", expand=True, pady=8, padx=12)
        self.manual_log.configure(state="disabled")

    # ------------------------------------------------------------- LOGGING
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

    # -------------------------------------------------------- ASK ON MAIN
    def ask_main(self, prompt, title="Input", integer=False, minvalue=1, maxvalue=9999):
        box = {}
        done = {"flag": False}

        def run():
            try:
                if integer:
                    box["v"] = simpledialog.askinteger(title, prompt,
                                                       minvalue=minvalue, maxvalue=maxvalue)
                else:
                    box["v"] = simpledialog.askstring(title, prompt)
            finally:
                done["flag"] = True

        self.after(0, run)
        while not done["flag"]:
            time.sleep(0.05)
        return box.get("v")

    # --------------------------------------------------------- UI EVENTS
    def open_folder(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def open_framework(self):
        if messagebox.askyesno("Framework 5.0",
                               "Open the .NET 5.0 download page in your browser?"):
            os.startfile("https://dotnet.microsoft.com/en-us/download/dotnet/5.0")

    def cleanup_workdir(self):
        if not messagebox.askyesno("Cleanup",
                                   "Delete tools/image0 and temp files?"):
            return
        rmtree(IMAGE0_DIR)
        for f in (TOOLS_DIR / "image0.gp4", TOOLS_DIR / "image0.txt",
                  TOOLS_DIR / "sort_file.txt"):
            try: f.unlink(missing_ok=True)
            except Exception: pass
        self.base_status.configure(text="Not extracted yet", text_color="#ff8080")
        messagebox.showinfo("Cleanup", "Work directory cleaned.")

    def _base_menu_values(self):
        vals = ["── Base emulators ──"] + list(BASE_EMULATORS.keys())
        official = sorted(OFFICIAL_DIR.glob("*.pkg"))
        if official:
            vals.append("── From official_pkgs/ ──")
            vals.extend(f"{p.name}" for p in official)
        return vals

    def rescan_official(self):
        self.base_menu.configure(values=self._base_menu_values())
        self.log(f"[scan] official_pkgs: "
                 f"{len(list(OFFICIAL_DIR.glob('*.pkg')))} PKG(s) found")

    def _on_base_change(self, value):
        if value.startswith("──"):
            return
        if value in BASE_EMULATORS:
            self.base_pkg_path = TOOLS_DIR / "emulator" / f"{BASE_EMULATORS[value]}.pkg"
            self.base_pkg_name = BASE_EMULATORS[value]
        else:
            self.base_pkg_path = OFFICIAL_DIR / value
            self.base_pkg_name = Path(value).stem
        self._update_output_preview()

    def _on_mode_change(self):
        is_game = self.mode_var.get() == "game"
        for sec in (self.iso_section, self.decrypt_section,
                    self.opts_section, self.icon_section):
            parent = sec.master  # the outer frame from _section
            if is_game:
                parent.pack(fill="x", padx=12, pady=8)
            else:
                parent.pack_forget()
        self.build_btn.configure(
            text="🚀  BUILD PKG" if is_game else "🔨  BUILD EMULATOR PKG")
        self._update_output_preview()

    def _update_output_preview(self):
        disc = getattr(self, "detected_disc_id", "") or "<DISC_ID>"
        title = getattr(self, "detected_title", "") or "<Title>"
        base = self.base_pkg_name or "<BasePKG>"
        if self.mode_var.get() == "game":
            self.output_preview.configure(
                text=f"Output: {safe_name(title)}_{safe_name(disc)}_{base}.pkg")
        else:
            tid = disc if disc != "<DISC_ID>" else "<TITLE_ID>"
            self.output_preview.configure(text=f"Output: {base}_EMU_{safe_name(tid)}.pkg")

    def pick_iso(self):
        f = filedialog.askopenfilename(title="Select PSP game ISO",
                                       filetypes=[("ISO", "*.iso"), ("All", "*.*")])
        if f:
            self.iso_file = Path(f)
            self.iso_label.configure(text=str(self.iso_file), text_color="#8fe388")
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
        f = filedialog.askopenfilename(title="Select icon",
                                       filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All", "*.*")])
        if f:
            self.icon_file = Path(f)
            self.icon_label.configure(text=str(self.icon_file))
            self.icon_var.set(1)

    def pick_boot(self):
        f = filedialog.askopenfilename(title="Select boot image",
                                       filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All", "*.*")])
        if f:
            self.boot_file = Path(f)
            self.boot_label.configure(text=str(self.boot_file))
            self.icon_var.set(1)

    # -------------------------------------------------- EXTRACT BASE PKG
    def do_extract_emulator(self):
        if not ORBIS.exists():
            messagebox.showerror("Error", f"Missing: {ORBIS}")
            return
        choice = self.base_var.get()
        if choice.startswith("──"):
            messagebox.showwarning("Pick a base", "Choose an actual base PKG entry.")
            return
        if choice in BASE_EMULATORS:
            pkg = TOOLS_DIR / "emulator" / f"{BASE_EMULATORS[choice]}.pkg"
            name = BASE_EMULATORS[choice]
        else:
            pkg = OFFICIAL_DIR / choice
            name = Path(choice).stem
        if not pkg.exists():
            messagebox.showerror("Error", f"PKG not found:\n{pkg}")
            return
        threading.Thread(target=self._extract_thread,
                         args=(pkg, name), daemon=True).start()

    def _extract_thread(self, pkg: Path, name: str):
        try:
            self.log(f"--- Extracting base: {name} ---")
            rmtree(IMAGE0_DIR)
            IMAGE0_DIR.mkdir(parents=True, exist_ok=True)

            rc = run_visible([str(ORBIS), "img_extract",
                              "--passcode", "00000000000000000000000000000000",
                              str(pkg), str(TOOLS_DIR)])
            if rc != 0:
                self.log(f"img_extract failed (rc={rc})")
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
            for pat in ("*.json","*.sig","*.dds","*.dat","*.info","*.sha","*.xml","*.png"):
                for f in target.glob(pat):
                    f.unlink(missing_ok=True)
            for f in IMAGE0_DIR.glob("*.plt"):
                f.unlink(missing_ok=True)
            siea = IMAGE0_DIR / "SIEA"
            if siea.exists():
                for pat in ("*.lua","*.txt","*.json"):
                    for f in siea.glob(pat):
                        f.unlink(missing_ok=True)
                scr = siea / "scripts"
                if scr.exists():
                    for f in scr.glob("*.lua"):
                        f.unlink(missing_ok=True)
                rmtree(siea / "data")
            for sub in ("about","app","changeinfo","trophy"):
                rmtree(target / sub)

            tmpl = TOOLS_DIR / "perm" / "config-title.txt"
            if tmpl.exists():
                shutil.copy2(tmpl, IMAGE0_DIR / "config-title.txt")

            for d in list(IMAGE0_DIR.iterdir()):
                if d.is_dir() and "#v1.00" in d.name:
                    self.log(f"  removing stale: {d.name}")
                    rmtree(d)

            self.after(0, lambda: self.base_status.configure(
                text=f"✓ extracted: {name}", text_color="#8fe388"))
            self.log(f"✅ Base extracted: {name}")
        except Exception as e:
            self.log(f"❌ Extract error: {e}")

    # --------------------------------------------------------- BUILD
    def do_build(self):
        if self.base_pkg_path is None:
            messagebox.showerror("No base", "Pick and extract a base PKG first.")
            return
        if not IMAGE0_DIR.exists() or not (IMAGE0_DIR / "sce_sys").exists():
            messagebox.showerror("No extraction",
                                 "Extract a base PKG first (Step 1).")
            return
        if self.mode_var.get() == "game":
            if not self.iso_file or not self.iso_file.exists():
                messagebox.showerror("No ISO", "Pick a game ISO first.")
                return
            threading.Thread(target=self._build_game_thread, daemon=True).start()
        else:
            threading.Thread(target=self._build_emu_thread, daemon=True).start()

    # --- GAME PKG ---
    def _build_game_thread(self):
        try:
            iso = self.iso_file
            self.log(f"--- Building GAME PKG from {iso.name} ---")

            # read sfo
            info = TOOLS_DIR / "info_temp"
            rmtree(info)
            (info / "PSP_GAME").mkdir(parents=True, exist_ok=True)
            run_cmd([str(SEVENZ), "e", str(iso),
                     f"-o{info / 'PSP_GAME'}", "PSP_GAME/param.sfo", "-aoa"])
            sfo_src = info / "PSP_GAME" / "param.sfo"
            if not sfo_src.exists():
                self.log("❌ param.sfo not found in ISO")
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
                return

            self.detected_disc_id = disc_id
            self.detected_title = psp_name
            self.after(0, self._update_output_preview)

            content_id = f"UP9000-{disc_id}_00-PSPX{disc_id[-5:]}TEHRZKY"

            # patch param.sfo
            sfo = IMAGE0_DIR / "sce_sys" / "param.sfo"
            for k, v in [("VERSION", "01.00"),
                         ("CONTENT_ID", content_id),
                         ("TITLE_ID", disc_id),
                         ("TITLE", psp_name)]:
                run_cmd([str(SFO), "-e", k, v, str(sfo)])

            # folder structure
            game_dir = IMAGE0_DIR / f"{disc_id}#v1.00"
            for sub in ("aot", "vms/GAME", "vms/SAVEDATA"):
                (game_dir / sub).mkdir(parents=True, exist_ok=True)
            siea = IMAGE0_DIR / "SIEA"
            siea.mkdir(parents=True, exist_ok=True)
            with open(siea / "config-region.txt", "a", encoding="utf-8") as f:
                f.write(f'--active-sku="{disc_id}#v1.00"\n')

            # DLC
            dlc_src = DLC_DIR / disc_id
            if dlc_src.exists():
                shutil.copytree(dlc_src, game_dir / "vms" / "GAME" / disc_id,
                                dirs_exist_ok=True)
                self.log(f"  DLC merged: {disc_id}")

            # decrypt
            m = self.decrypt_var.get()
            if m == 1:
                if not self._decrypt_mkiso(iso, game_dir, disc_id):
                    self.log("⚠️ decrypt failed — falling back to swap")
                    self._swap(iso, game_dir, disc_id)
            elif m == 2:
                self._swap(iso, game_dir, disc_id)
            else:
                self._skip_copy(iso, game_dir, disc_id)

            # emulator options
            self._apply_schema_to_config()

            # overrides
            if self.use_overrides.get():
                self.log("Copying overrides/ ...")
                shutil.copytree(OVERRIDES_DIR, IMAGE0_DIR, dirs_exist_ok=True)

            # icons
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

    # --- EMULATOR PKG ---
    def _build_emu_thread(self):
        try:
            self.log("--- Building EMULATOR PKG ---")
            sfo = IMAGE0_DIR / "sce_sys" / "param.sfo"
            if not sfo.exists():
                self.log("❌ param.sfo missing — extract a base first")
                return

            tid = self.ask_main("TITLE_ID for this emulator PKG (e.g. UP9000-CUSA00000_00):",
                                "Emulator TITLE_ID")
            if not tid:
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

    # --- helpers for build ---
    def _decrypt_mkiso(self, iso: Path, game_dir: Path, disc_id: str) -> bool:
        tmp = TOOLS_DIR / "iso_extraction_temp"
        rmtree(tmp); tmp.mkdir(parents=True, exist_ok=True)
        sort_file = TOOLS_DIR / "sort_file.txt"
        try:
            p1 = subprocess.Popen([str(ISOINFO), "-f", "-i", str(iso)],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p2 = subprocess.Popen([str(AWK_NL), "-nln", "-s", ";"],
                                  stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p1.stdout.close()
            with open(sort_file, "w", encoding="utf-8", errors="ignore") as f:
                p3 = subprocess.Popen([str(AWK), "-F", ";", '{print substr($2,2) " -" $1}'],
                                      stdin=p2.stdout, stdout=f, stderr=subprocess.DEVNULL)
                p2.stdout.close()
                p3.wait()
        except Exception as e:
            self.log(f"sort error: {e}")

        self.log("Extracting ISO with 7z ...")
        run_cmd([str(SEVENZ), "x", str(iso), f"-o{tmp}", "-r", "-aoa"])

        eboot = tmp / "PSP_GAME" / "SYSDIR" / "EBOOT.BIN"
        if not eboot.exists():
            self.log("EBOOT.BIN missing inside ISO")
            rmtree(tmp); return False

        self.log("Decrypting EBOOT.BIN ...")
        run_cmd([str(PSPDECRYPT), str(eboot)])
        dec = eboot.with_suffix(".BIN.DEC")
        if not dec.exists():
            self.log("EBOOT.BIN.DEC not produced")
            rmtree(tmp); return False
        eboot.unlink(); dec.rename(eboot)

        out_iso = game_dir / f"{disc_id}#v1.00.IMG"
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
                # for texcachemode-skip, remove the line instead of adding
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
        self.log("Generating GP4 ...")
        run_cmd([str(GENGP4), str(IMAGE0_DIR)])

        gp4 = TOOLS_DIR / "image0.gp4"
        txt = TOOLS_DIR / "image0.txt"
        if gp4.exists():
            gp4.rename(txt)
        if txt.exists():
            run_cmd([str(FART), str(txt), "-i", 'default_id="1"', 'default_id="0"'])
            txt.rename(gp4)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        tmp_pkg = OUTPUT_DIR / "1.pkg"
        if tmp_pkg.exists():
            tmp_pkg.unlink()

        self.log("orbis-pub-cmd img_create ...")
        rc = run_visible([str(ORBIS), "img_create", str(gp4), str(tmp_pkg)])
        if rc != 0 or not tmp_pkg.exists():
            self.log("❌ img_create failed")
            return

        final = OUTPUT_DIR / out_name
        if final.exists():
            final.unlink()
        tmp_pkg.rename(final)

        size_mb = final.stat().st_size // (1024 * 1024)
        (OUTPUT_DIR / f"[{disc_id}] {title} ({size_mb}mb).txt").write_text("", encoding="utf-8")
        try: gp4.unlink()
        except Exception: pass
        rmtree(IMAGE0_DIR)

        self.log(f"✅ PKG created: {final.name}  ({size_mb} MB)")
        messagebox.showinfo("Success", f"PKG created:\n{final}")

    # -------------------------------------------------------- MANUAL BUILD
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
            if out.exists(): out.unlink()

            self.mlog("orbis-pub-cmd img_create ...")
            rc = run_visible([str(ORBIS_PLAIN), "img_create", str(gp4), str(out)])
            if rc != 0 or not out.exists():
                self.mlog("❌ build failed")
                return
            try: gp4.unlink()
            except Exception: pass
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
