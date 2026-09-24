import os
import sys
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from pathlib import Path

import customtkinter as ctk
from PIL import Image

# ---------- Paths ----------
def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent

BASE_DIR = get_base_dir()
TOOLS_DIR = BASE_DIR / "tools"
IMAGE0_DIR = TOOLS_DIR / "image0"
PKG_OUT_DIR = BASE_DIR / "pkg"
EMU_PKG_DIR = BASE_DIR / "pkgemulatorhere"
PUT_EMU_DIR = BASE_DIR / "putemulatorhere"
PUT_DLC_DIR = BASE_DIR / "putgamedlchere"

ORBIS_CMD = TOOLS_DIR / "orbis-pub-cmd-keystone.exe"
ORBIS_CMD_PLAIN = TOOLS_DIR / "orbis-pub-cmd.exe"
GENGP4 = TOOLS_DIR / "gengp4-patched.exe"
FART = TOOLS_DIR / "fart.exe"
SFO = TOOLS_DIR / "sfo.exe"
MAGICK = TOOLS_DIR / "magick.exe"
SEVENZ = TOOLS_DIR / "7z.exe"
PSPDECRYPT = TOOLS_DIR / "pspdecrypt.exe"
MKISOFS = TOOLS_DIR / "mkisofs.exe"
ISOINFO = TOOLS_DIR / "cdrtools" / "isoinfo.exe"
AWK_NL = TOOLS_DIR / "awk" / "nl.exe"
AWK = TOOLS_DIR / "awk" / "awk.exe"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ---------- Helpers ----------
def run_cmd(cmd, cwd=None, check=False):
    """Run a command silently and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=isinstance(cmd, str),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.returncode, result.stdout.decode(errors="ignore"), result.stderr.decode(errors="ignore")
    except Exception as e:
        return -1, "", str(e)


def run_visible(cmd, cwd=None):
    """Run a command with a visible window (for orbis img_extract etc.)."""
    try:
        return subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str)).returncode
    except Exception as e:
        return -1


def safe_rmtree(path):
    try:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def file_dialog(title, filetypes):
    return filedialog.askopenfilename(title=title, filetypes=filetypes)


def dir_dialog(title):
    return filedialog.askdirectory(title=title)


# ---------- Emulator Config ----------
EMULATORS = {
    "Killzone v1 (FW 5.00)": "KillzoneV1",
    "Resistance v1 + Keystone (FW 9.00+)": "ResistanceV1",
    "Custom Emulator (Working+EmuFolder)": "custom",
    "Resistance v2 + Keystone (FW 5.00+)": "ResistanceV2",
    "fPKG Untouched Emulator": None,  # special: list pkg files
}

TEXCACHE_MODES = ["drawboundsloco", "drawbounds", "locoroco2", "patchworkheroes", "rondo", "skip"]


# ---------- Main Application ----------
class PSP2PS4App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PSP 2 PS4 AIO - GUI")
        self.geometry("980x720")
        self.minsize(900, 640)

        # shared state
        self.iso_file: Path | None = None
        self.emulator_name: str | None = None
        self.title_id: str | None = None
        self.game_title: str | None = None
        self.emupkgname: str | None = None

        self._build_ui()

    # -------- UI --------
    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text="PSP 2 PS4 AIO", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(24, 4))
        ctk.CTkLabel(sidebar, text="V2.5 • by tehrzky", font=ctk.CTkFont(size=12)).pack(pady=(0, 20))

        self.btn_create = ctk.CTkButton(sidebar, text="🎮  Create PSP PKG", command=self.show_create_page)
        self.btn_create.pack(pady=6, padx=16, fill="x")

        self.btn_manual = ctk.CTkButton(sidebar, text="🛠️  PKG Maker (Custom)", command=self.show_manual_page)
        self.btn_manual.pack(pady=6, padx=16, fill="x")

        self.btn_framework = ctk.CTkButton(sidebar, text="⬇️  Install Framework 5.0", command=self.open_framework)
        self.btn_framework.pack(pady=6, padx=16, fill="x")

        self.btn_compat = ctk.CTkButton(sidebar, text="📋  Compatible Games List", command=self.open_compat)
        self.btn_compat.pack(pady=6, padx=16, fill="x")

        ctk.CTkLabel(sidebar, text="", height=20).pack()

        self.btn_clear = ctk.CTkButton(
            sidebar, text="🧹  Cleanup Work Dir", fg_color="#8B0000", hover_color="#5a0000",
            command=self.cleanup_workdir
        )
        self.btn_clear.pack(pady=6, padx=16, fill="x", side="bottom")

        # Main content
        self.content = ctk.CTkFrame(self, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.pages = {}
        self._create_create_page()
        self._create_manual_page()

        self.show_page("create")

    def show_page(self, name):
        for p in self.pages.values():
            p.grid_forget()
        self.pages[name].grid(row=0, column=0, sticky="nsew")

    # ---------- Create Page ----------
    def _create_create_page(self):
        page = ctk.CTkScrollableFrame(self.content, corner_radius=0)
        self.pages["create"] = page
        page.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(10, 4))
        ctk.CTkLabel(header, text="Create a PSP PKG for PS4",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header, text="Play the PSP in full HD on your PS4",
                     font=ctk.CTkFont(size=12)).pack(anchor="w")

        # Step 1: Emulator
        s1 = self._section(page, "1. Select Emulator", "Choose the emulator package to use as base")
        self.emu_var = tk.StringVar(value=list(EMULATORS.keys())[0])
        for name in EMULATORS:
            ctk.CTkRadioButton(s1, text=name, variable=self.emu_var, value=name).pack(anchor="w", pady=2)

        # Step 2: Extract
        s2 = self._section(page, "2. Extract Emulator", "Extracts the selected emulator into tools/image0")
        ctk.CTkButton(s2, text="Extract Emulator", command=self.do_extract_emulator).pack(anchor="w", pady=6)

        # Step 3: copy putemulatorhere?
        s3 = self._section(page, "3. Copy 'putemulatorhere' contents?",
                           "Overwrites existing files in the emulator with your custom config")
        row = ctk.CTkFrame(s3, fg_color="transparent")
        row.pack(anchor="w", pady=4)
        self.copy_put_var = tk.IntVar(value=1)
        ctk.CTkRadioButton(row, text="Yes - overwrite existing files",
                           variable=self.copy_put_var, value=1).pack(side="left", padx=(0, 12))
        ctk.CTkRadioButton(row, text="No - skip",
                           variable=self.copy_put_var, value=2).pack(side="left")

        # Step 4: Builder mode
        s4 = self._section(page, "4. PSP Builder Mode", "Choose what to build")
        self.builder_var = tk.IntVar(value=1)
        ctk.CTkRadioButton(s4, text="PSP PKG Maker (game ISO)",
                           variable=self.builder_var, value=1).pack(anchor="w", pady=2)
        ctk.CTkRadioButton(s4, text="PSP Playground Launcher (manual title ID)",
                           variable=self.builder_var, value=2).pack(anchor="w", pady=2)

        # Step 5: ISO selection
        s5 = self._section(page, "5. Game ISO / Title ID", "Pick your game's .ISO file")
        self.iso_label = ctk.CTkLabel(s5, text="No ISO selected", text_color="#ff8080")
        self.iso_label.pack(anchor="w", pady=4)
        ctk.CTkButton(s5, text="Browse ISO...", command=self.pick_iso).pack(anchor="w", pady=4)

        # Step 6: Decrypt
        s6 = self._section(page, "6. Decrypt Method", "How to handle the EBOOT.BIN")
        self.decrypt_var = tk.IntVar(value=1)
        ctk.CTkRadioButton(s6, text="Decrypt and process game image (not for homebrew)",
                           variable=self.decrypt_var, value=1).pack(anchor="w", pady=2)
        ctk.CTkRadioButton(s6, text="Swap EBOOT method (if decrypt is not working)",
                           variable=self.decrypt_var, value=2).pack(anchor="w", pady=2)
        ctk.CTkRadioButton(s6, text="Skip decryption and process directly (fast)",
                           variable=self.decrypt_var, value=3).pack(anchor="w", pady=2)

        # Step 7: texcachemode
        s7 = self._section(page, "7. texcachemode", "Patch config-title.txt with texcachemode")
        self.tex_var = tk.StringVar(value=TEXCACHE_MODES[0])
        ctk.CTkOptionMenu(s7, values=TEXCACHE_MODES, variable=self.tex_var).pack(anchor="w", pady=4)

        # Step 8: Customization
        s8 = self._section(page, "8. Game Customization", "Set icon / background")
        self.custom_var = tk.IntVar(value=2)
        ctk.CTkRadioButton(s8, text="Set an icon/background",
                           variable=self.custom_var, value=1).pack(anchor="w", pady=2)
        ctk.CTkRadioButton(s8, text="Skip setting an icon/background",
                           variable=self.custom_var, value=2).pack(anchor="w", pady=2)

        self.icon_path = ctk.CTkLabel(s8, text="No icon selected")
        self.icon_path.pack(anchor="w", pady=2)
        ctk.CTkButton(s8, text="Choose Icon...", command=self.pick_icon).pack(anchor="w", pady=2)

        self.boot_path = ctk.CTkLabel(s8, text="No boot image selected")
        self.boot_path.pack(anchor="w", pady=2)
        ctk.CTkButton(s8, text="Choose Boot Image...", command=self.pick_boot).pack(anchor="w", pady=2)

        # Build button
        self.build_btn = ctk.CTkButton(
            page, text="🚀  BUILD PKG", height=46,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self.do_build,
        )
        self.build_btn.pack(fill="x", padx=20, pady=20)

        # Log
        s9 = self._section(page, "Log", "")
        self.log_box = ctk.CTkTextbox(s9, height=180, wrap="word")
        self.log_box.pack(fill="both", expand=True, pady=4)
        self.log_box.configure(state="disabled")

    # ---------- Manual Page ----------
    def _create_manual_page(self):
        page = ctk.CTkScrollableFrame(self.content, corner_radius=0)
        self.pages["manual"] = page
        page.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(page, text="PKG Maker (Custom)",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", pady=(10, 4))
        ctk.CTkLabel(page,
                     text="Put your files in  tools/image0/  then click BUILD below.\n"
                          "This uses orbis-pub-cmd (non-keystone).",
                     justify="left").pack(anchor="w", pady=4)

        ctk.CTkButton(page, text="Open tools/image0 folder", command=self.open_image0).pack(anchor="w", pady=8)
        ctk.CTkButton(page, text="🚀  BUILD customemu.pkg", height=44,
                      font=ctk.CTkFont(size=15, weight="bold"),
                      command=self.do_manual_build).pack(anchor="w", pady=8)

        self.manual_log = ctk.CTkTextbox(page, height=220, wrap="word")
        self.manual_log.pack(fill="both", expand=True, pady=8)
        self.manual_log.configure(state="disabled")

    # ---------- UI Utilities ----------
    def _section(self, parent, title, subtitle=""):
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 0))
        if subtitle:
            ctk.CTkLabel(frame, text=subtitle, font=ctk.CTkFont(size=11),
                         text_color="#aaaaaa").pack(anchor="w", padx=12, pady=(0, 6))
        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=(0, 10))
        return inner

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.update_idletasks()

    def mlog(self, msg):
        self.manual_log.configure(state="normal")
        self.manual_log.insert("end", msg + "\n")
        self.manual_log.see("end")
        self.manual_log.configure(state="disabled")
        self.update_idletasks()

    def show_create_page(self):
        self.show_page("create")

    def show_manual_page(self):
        self.show_page("manual")

    def open_image0(self):
        IMAGE0_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(IMAGE0_DIR))

    def open_framework(self):
        if messagebox.askyesno("Framework 5.0",
                               "Open the .NET Framework 5.0 download page?\n"
                               "(An internet connection is required.)"):
            os.startfile("https://dotnet.microsoft.com/en-us/download/dotnet/5.0")

    def open_compat(self):
        if messagebox.askyesno("Compatibility List",
                               "Open the PSP Emulator Compatibility List?\n"
                               "(An internet connection is required.)"):
            os.startfile("https://www.psdevwiki.com/ps4/PSP_Emulator_Compatibility_List")

    def cleanup_workdir(self):
        if not messagebox.askyesno("Cleanup", "Delete tools/image0 and .gp4 temp files?"):
            return
        safe_rmtree(IMAGE0_DIR)
        for f in [TOOLS_DIR / "image0.gp4", TOOLS_DIR / "image0.txt", TOOLS_DIR / "sort_file.txt"]:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
        messagebox.showinfo("Cleanup", "Work directory cleaned.")

    # ---------- File Pickers ----------
    def pick_iso(self):
        f = file_dialog("Select your PSP game ISO", [("ISO files", "*.iso"), ("All files", "*.*")])
        if f:
            self.iso_file = Path(f)
            self.iso_label.configure(text=str(self.iso_file), text_color="#8fe388")

    def pick_icon(self):
        f = file_dialog("Select icon", [("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")])
        if f:
            self.icon_file = Path(f)
            self.icon_path.configure(text=str(self.icon_file))

    def pick_boot(self):
        f = file_dialog("Select boot image", [("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")])
        if f:
            self.boot_file = Path(f)
            self.boot_path.configure(text=str(self.boot_file))

    # ---------- Extract Emulator ----------
    def do_extract_emulator(self):
        if not ORBIS_CMD.exists():
            messagebox.showerror("Error", f"Missing: {ORBIS_CMD}")
            return

        choice = self.emu_var.get()
        emupkgname = EMULATORS[choice]

        if emupkgname is None:
            # fPKG untouched - list pkg files
            pkgs = sorted(EMU_PKG_DIR.glob("*.pkg"))
            if not pkgs:
                messagebox.showerror("Error", f"No .pkg files in {EMU_PKG_DIR}")
                return
            names = "\n".join(f"{i+1}. {p.name}" for i, p in enumerate(pkgs))
            idx = simpledialog.askinteger("Select PKG",
                                          f"Choose a PKG:\n\n{names}\n\nEnter number:",
                                          minvalue=1, maxvalue=len(pkgs))
            if not idx:
                return
            pkgpath = pkgs[idx - 1]
        else:
            pkgpath = TOOLS_DIR / "emulator" / f"{emupkgname}.pkg"
            if not pkgpath.exists():
                messagebox.showerror("Error", f"Emulator package not found:\n{pkgpath}")
                return

        threading.Thread(target=self._extract_thread, args=(pkgpath, emupkgname or choice), daemon=True).start()

    def _extract_thread(self, pkgpath, name):
        try:
            self.log(f"--- Extracting {name} ---")
            safe_rmtree(IMAGE0_DIR)
            IMAGE0_DIR.mkdir(parents=True, exist_ok=True)

            self.log("Running orbis-pub-cmd img_extract ...")
            rc = run_visible([
                str(ORBIS_CMD), "img_extract",
                "--passcode", "00000000000000000000000000000000",
                str(pkgpath), str(TOOLS_DIR),
            ])
            if rc != 0:
                self.log(f"img_extract failed (rc={rc})")
                return

            # Move Sc0 -> sce_sys if needed
            sc0 = TOOLS_DIR / "Sc0"
            sce_sys = TOOLS_DIR / "sce_sys"
            if sc0.exists() and not sce_sys.exists():
                sc0.rename(sce_sys)

            # Copy sce_sys into image0/sce_sys
            if sce_sys.exists():
                dest = IMAGE0_DIR / "sce_sys"
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copytree(sce_sys, dest, dirs_exist_ok=True)
                safe_rmtree(sce_sys)

            # Cleanup unneeded files
            target = IMAGE0_DIR / "sce_sys"
            if target.exists():
                for pat in ("*.json", "*.sig", "*.dds", "*.dat", "*.info", "*.sha", "*.xml", "*.png"):
                    for f in target.glob(pat):
                        try:
                            f.unlink()
                        except Exception:
                            pass
            for pat in ("*.plt",):
                for f in IMAGE0_DIR.glob(pat):
                    try:
                        f.unlink()
                    except Exception:
                        pass
            siea = IMAGE0_DIR / "SIEA"
            if siea.exists():
                for pat in ("*.lua", "*.txt", "*.json"):
                    for f in siea.glob(pat):
                        try:
                            f.unlink()
                        except Exception:
                            pass
                scripts = siea / "scripts"
                if scripts.exists():
                    for f in scripts.glob("*.lua"):
                        try:
                            f.unlink()
                        except Exception:
                            pass
                safe_rmtree(siea / "data")

            for sub in ("about", "app", "changeinfo", "trophy"):
                safe_rmtree(target / sub)

            # Copy config-title.txt template
            template = TOOLS_DIR / "perm" / "config-title.txt"
            if template.exists():
                shutil.copy2(template, IMAGE0_DIR / "config-title.txt")

            # Delete game data folders (#v1.00)
            for d in IMAGE0_DIR.iterdir():
                if d.is_dir() and "#v1.00" in d.name:
                    self.log(f"Deleting folder: {d.name}")
                    safe_rmtree(d)

            # Copy putemulatorhere if requested
            if self.copy_put_var.get() == 1 and PUT_EMU_DIR.exists():
                self.log("Copying putemulatorhere ...")
                shutil.copytree(PUT_EMU_DIR, IMAGE0_DIR, dirs_exist_ok=True)

            self.log("✅ Emulator extracted successfully.")
        except Exception as e:
            self.log(f"❌ Exception: {e}")

    # ---------- Build ISO ----------
    def do_build(self):
        if self.builder_var.get() == 1:
            if not self.iso_file or not self.iso_file.exists():
                messagebox.showerror("Error", "Please choose your game ISO first.")
                return
            threading.Thread(target=self._build_iso_thread, daemon=True).start()
        else:
            threading.Thread(target=self._build_playground_thread, daemon=True).start()

    def _build_iso_thread(self):
        try:
            iso = self.iso_file
            self.log(f"--- Building PKG from {iso.name} ---")

            # 1) Extract param.sfo info
            info_temp = TOOLS_DIR / "info_temp"
            safe_rmtree(info_temp)
            (info_temp / "PSP_GAME").mkdir(parents=True, exist_ok=True)

            self.log("Reading param.sfo ...")
            rc, _, err = run_cmd([str(SEVENZ), "e", str(iso),
                                  f"-o{info_temp / 'PSP_GAME'}", "PSP_GAME/param.sfo", "-aoa"])
            if not (info_temp / "PSP_GAME" / "param.sfo").exists():
                self.log(f"❌ Could not read param.sfo: {err}")
                return

            rc, out, _ = run_cmd([str(TOOLS_DIR / "SFOInfo.exe"), "i",
                                  str(info_temp / "PSP_GAME" / "param.sfo"),
                                  str(info_temp / "PSP_GAME" / "param.txt")])

            disc_id = ""
            psp_name = ""
            with open(info_temp / "PSP_GAME" / "param.txt", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("DISC_ID"):
                        disc_id = line.split(":", 1)[1].strip()
                    elif line.startswith("TITLE"):
                        psp_name = line.split(":", 1)[1].strip()

            if not disc_id:
                self.log("❌ Could not determine DISC_ID")
                return

            self.title_id = disc_id
            last5 = disc_id[-5:]
            content_id = f"UP9000-{disc_id}_00-PSPX{last5}TEHRZKY"

            self.log(f"DISC_ID   : {disc_id}")
            self.log(f"PSP Name  : {psp_name}")
            self.log(f"CONTENT_ID: {content_id}")

            # 2) Update param.sfo
            sfo = IMAGE0_DIR / "sce_sys" / "param.sfo"
            if not sfo.exists():
                self.log("❌ param.sfo not in tools/image0/sce_sys — did you extract an emulator first?")
                return

            for key, val in [("VERSION", "01.00"), ("CONTENT_ID", content_id), ("TITLE_ID", disc_id)]:
                run_cmd([str(SFO), "-e", key, val, str(sfo)])

            title = simpledialog.askstring("Game Title",
                                           f"PSP Name: {psp_name}\n\n"
                                           "Enter title (leave empty to use default):")
            if not title:
                title = psp_name
            self.game_title = title
            run_cmd([str(SFO), "-e", "TITLE", title, str(sfo)])

            self.log(f"Set TITLE: {title}")

            # 3) Create game folder structure
            game_dir = IMAGE0_DIR / f"{disc_id}#v1.00"
            for sub in ["aot", "vms/GAME", "vms/SAVEDATA"]:
                (game_dir / sub).mkdir(parents=True, exist_ok=True)

            with open(IMAGE0_DIR / "SIEA" / "config-region.txt", "a", encoding="utf-8") as f:
                f.write(f'--active-sku="{disc_id}#v1.00"\n')

            # 4) DLC copy
            if PUT_DLC_DIR.exists():
                for d in PUT_DLC_DIR.iterdir():
                    if d.is_dir() and d.name.lower() == disc_id.lower():
                        dest = game_dir / "vms" / "GAME" / d.name
                        shutil.copytree(d, dest, dirs_exist_ok=True)
                        self.log(f"DLC copied: {d.name}")

            # 5) Decrypt
            method = self.decrypt_var.get()
            if method == 1:
                ok = self._decrypt_and_mkiso(iso, game_dir, disc_id)
                if not ok:
                    self.log("⚠️ Decrypt failed, falling back to swap method")
                    self._swap_method(iso, game_dir, disc_id)
            elif method == 2:
                self._swap_method(iso, game_dir, disc_id)
            else:
                self._rename_directly(iso, game_dir, disc_id)

            # 6) texcachemode
            self._apply_texcachemode()

            # 7) Customization
            if self.custom_var.get() == 1:
                self._apply_customization()
            else:
                self._copy_default_icons()

            # 8) Build PKG
            self._finish_pkg(disc_id, title)

            safe_rmtree(info_temp)
        except Exception as e:
            self.log(f"❌ Exception: {e}")
            import traceback
            self.log(traceback.format_exc())

    def _decrypt_and_mkiso(self, iso, game_dir, disc_id):
        iso_temp = TOOLS_DIR / "iso_extraction_temp"
        safe_rmtree(iso_temp)
        iso_temp.mkdir(parents=True, exist_ok=True)

        sort_file = TOOLS_DIR / "sort_file.txt"
        self.log("Generating ISO sort file ...")
        try:
            # isoinfo -f -i iso | nl | awk
            p1 = subprocess.Popen([str(ISOINFO), "-f", "-i", str(iso)],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p2 = subprocess.Popen([str(AWK_NL), "-nln", "-s", ";"],
                                  stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p1.stdout.close()
            with open(sort_file, "w", encoding="utf-8", errors="ignore") as f:
                p3 = subprocess.Popen([str(AWK), "-F", ";", "{print substr($2,2) \" -\" $1}"],
                                      stdin=p2.stdout, stdout=f, stderr=subprocess.DEVNULL)
                p2.stdout.close()
                p3.wait()
        except Exception as e:
            self.log(f"sort_file error: {e}")

        self.log("Extracting ISO (this takes a while) ...")
        rc, _, err = run_cmd([str(SEVENZ), "x", str(iso), f"-o{iso_temp}", "-r", "-aoa"])
        if rc != 0:
            self.log(f"7z extract failed: {err}")
            return False

        eboot = iso_temp / "PSP_GAME" / "SYSDIR" / "EBOOT.BIN"
        if not eboot.exists():
            self.log("EBOOT.BIN not found inside ISO")
            return False

        self.log("Decrypting EBOOT.BIN ...")
        run_cmd([str(PSPDECRYPT), str(eboot)])
        dec = eboot.with_suffix(".BIN.DEC")
        if dec.exists():
            eboot.unlink()
            dec.rename(eboot)
            self.log("EBOOT.BIN decrypted.")
        else:
            self.log("EBOOT.BIN.DEC not produced.")
            safe_rmtree(iso_temp)
            return False

        out_img = game_dir / "game.iso"
        self.log("Building ISO with mkisofs ...")
        cmd = [
            str(MKISOFS), "-quiet",
            "-sort", str(sort_file),
            "-iso-level", "4", "-xa",
            "-A", "PSP GAME",
            "-V", "PSP_GAME",
            "-sysid", "PSP GAME",
            "-volset", "", "-p", "", "-publisher", "",
            "-o", str(out_img),
            str(iso_temp),
        ]
        run_cmd(cmd)

        # Rename to <TITLE_ID>#v1.00.IMG
        if out_img.exists():
            final = game_dir / f"{disc_id}#v1.00.IMG"
            if final.exists():
                final.unlink()
            out_img.rename(final)
            self.log(f"Created {final.name}")

        try:
            sort_file.unlink()
        except Exception:
            pass
        safe_rmtree(iso_temp)
        return True

    def _swap_method(self, iso, game_dir, disc_id):
        self.log("Using swap method (BOOT.BIN) ...")
        target = game_dir / f"{disc_id}#v1.00.IMG"
        shutil.copy2(iso, target)
        config = IMAGE0_DIR / "config-title.txt"
        if config.exists():
            run_cmd([str(FART), "-C", str(config),
                     "#1", "\\--boot=umd0:/PSP_GAME/SYSDIR/BOOT.BIN"])
        self.log(f"Copied ISO as {target.name}")

    def _rename_directly(self, iso, game_dir, disc_id):
        self.log("Direct copy (no decrypt) ...")
        target = game_dir / f"{disc_id}#v1.00.IMG"
        shutil.copy2(iso, target)
        self.log(f"Copied ISO as {target.name}")

    def _apply_texcachemode(self):
        mode = self.tex_var.get()
        config = IMAGE0_DIR / "config-title.txt"
        if not config.exists():
            return
        if mode == "skip":
            run_cmd([str(FART), "-i", str(config), "#--texcachemode=", "--remove"])
            self.log("texcachemode: skipped")
        else:
            run_cmd([str(FART), "-C", str(config),
                     "#--texcachemode=", f"\\--texcachemode={mode}"])
            self.log(f"texcachemode: {mode}")

    def _apply_customization(self):
        icon = getattr(self, "icon_file", None)
        boot = getattr(self, "boot_file", None)
        sce = IMAGE0_DIR / "sce_sys"

        if icon and icon.exists():
            run_cmd([str(MAGICK), str(icon), "-resize", "512x512!", "-colorspace", "sRGB",
                     "-depth", "8", str(sce / "icon0.png")])
            run_cmd([str(MAGICK), str(icon), "-resize", "228x128>", "-gravity", "center",
                     "-extent", "228x128", "-trim", "+repage",
                     "(", "-clone", "0", "-resize", "456x256", "-blur", "0x2",
                     "-extent", "228x128", "-colorize", "10%", ")", "+swap",
                     "-gravity", "center", "-composite", str(sce / "save_data.png")])
            run_cmd([str(MAGICK), str(icon), "-resize", "512x512!",
                     str(IMAGE0_DIR / "SIEA" / "regional_icon.png")])
            self.log("Icon applied.")

        if boot and boot.exists():
            pic1 = sce / "pic1.png"
            run_cmd([str(MAGICK), str(boot), "-resize", "1920x1080!", str(pic1)])
            shutil.copy2(pic1, sce / "pic0.png")
            self.log("Boot image applied.")

    def _copy_default_icons(self):
        src = TOOLS_DIR / "pic"
        sce = IMAGE0_DIR / "sce_sys"
        if src.exists():
            for name in ("icon0.png", "pic1.png", "save_data.png"):
                s = src / name
                if s.exists():
                    shutil.copy2(s, sce / name)
            self.log("Default icons copied.")

    def _finish_pkg(self, disc_id, title):
        self.log("Generating GP4 ...")
        run_cmd([str(GENGP4), str(IMAGE0_DIR)])

        gp4 = TOOLS_DIR / "image0.gp4"
        txt = TOOLS_DIR / "image0.txt"
        if gp4.exists():
            gp4.rename(txt)
        if txt.exists():
            run_cmd([str(FART), str(txt), "-i", 'default_id="1"', 'default_id="0"'])
            txt.rename(gp4)

        PKG_OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = PKG_OUT_DIR / "1.pkg"
        if out.exists():
            out.unlink()
        self.log("Running orbis-pub-cmd img_create ...")
        rc = run_visible([str(ORBIS_CMD), "img_create", str(gp4), str(out)])
        if rc != 0 or not out.exists():
            self.log("❌ img_create failed")
            return

        safe_name = "".join(c for c in f"{title}_{disc_id}_TEHR.pkg" if c not in r'<>:"/\|?*')
        final = PKG_OUT_DIR / safe_name
        if final.exists():
            final.unlink()
        out.rename(final)

        size_mb = final.stat().st_size // (1024 * 1024)
        txt_file = PKG_OUT_DIR / f"[{disc_id}] {title} [PSPtoPS4] ({size_mb}mb).txt"
        txt_file.write_text("", encoding="utf-8")

        try:
            gp4.unlink()
        except Exception:
            pass
        safe_rmtree(IMAGE0_DIR)

        self.log(f"✅ PKG created: {final}")
        messagebox.showinfo("Success", f"Your PSP PKG has been created:\n\n{final}")

    # ---------- Playground (manual) ----------
    def _build_playground_thread(self):
        try:
            disc_id = simpledialog.askstring("Title ID", "Title ID of your game (ex. SLES00939):")
            if not disc_id:
                return
            self.title_id = disc_id

            sfo = IMAGE0_DIR / "sce_sys" / "param.sfo"
            if not sfo.exists():
                self.log("❌ param.sfo not found in tools/image0/sce_sys")
                return

            content_id = f"UP9000-{disc_id}_00-{disc_id}TEHRZKY"
            for k, v in [("TITLE_ID", disc_id), ("CONTENT_ID", content_id)]:
                run_cmd([str(SFO), "-e", k, v, str(sfo)])

            emutitle = simpledialog.askstring("Title", "Set Title of your game:")
            if not emutitle:
                return
            title = f"PSP Emu {emutitle}"
            self.game_title = title
            run_cmd([str(SFO), "-e", "TITLE", title, str(sfo)])

            config = IMAGE0_DIR / "config-title.txt"
            config.write_text(
                f"# {title} Emu\n"
                f"# {disc_id}\n"
                f"# tehrzky\n"
                f'--region-dir="/data/PS4ROMS/PSPISO/SIEA"\n',
                encoding="utf-8"
            )

            if self.custom_var.get() == 1:
                self._apply_customization()
            else:
                self._copy_default_icons()

            self._finish_pkg(disc_id, title)
        except Exception as e:
            self.log(f"❌ Exception: {e}")

    # ---------- Manual Page Build ----------
    def do_manual_build(self):
        threading.Thread(target=self._manual_build_thread, daemon=True).start()

    def _manual_build_thread(self):
        try:
            self.mlog("Generating GP4 ...")
            run_cmd([str(GENGP4), str(IMAGE0_DIR)])

            gp4 = TOOLS_DIR / "image0.gp4"
            txt = TOOLS_DIR / "image0.txt"
            if gp4.exists():
                gp4.rename(txt)
            if txt.exists():
                run_cmd([str(FART), str(txt), "-i", 'default_id="1"', 'default_id="0"'])
                txt.rename(gp4)

            out = BASE_DIR / "1.pkg"
            if out.exists():
                out.unlink()
            self.mlog("Running orbis-pub-cmd img_create ...")
            rc = run_visible([str(ORBIS_CMD_PLAIN), "img_create", str(gp4), str(out)])
            if rc != 0 or not out.exists():
                self.mlog("❌ img_create failed")
                return
            final = BASE_DIR / "customemu.pkg"
            if final.exists():
                final.unlink()
            out.rename(final)
            try:
                gp4.unlink()
            except Exception:
                pass
            self.mlog(f"✅ PKG created: {final}")
            messagebox.showinfo("Success", f"Created:\n{final}")
        except Exception as e:
            self.mlog(f"❌ Exception: {e}")


if __name__ == "__main__":
    # sanity check
    missing = []
    for exe in [ORBIS_CMD, GENGP4, FART, SFO, MAGICK, SEVENZ, PSPDECRYPT, MKISOFS]:
        if not exe.exists():
            missing.append(str(exe))

    app = PSP2PS4App()
    if missing:
        app.log("⚠️ Missing tools (check your tools/ folder):")
        for m in missing:
            app.log(f"   - {m}")
    app.mainloop()
