"""
ui_theme.py — Colors, fonts, and reusable widgets.

Change the color constants here to re-skin the whole app.
"""
import tkinter as tk

import customtkinter as ctk


# ----------------------------------------------------------------------------
# Design tokens
# ----------------------------------------------------------------------------
BG         = "#0e0f13"
SIDEBAR    = "#12131a"
SURFACE    = "#171a21"
SURFACE_2  = "#1e222c"
SURFACE_3  = "#262b38"
BORDER     = "#2b3040"
BORDER_LT  = "#3d445c"
ACCENT     = "#7c9bff"
ACCENT_HI  = "#aec0ff"
ACCENT_ON  = "#0b0d14"
SELECT     = "#2b3a5e"
TEXT       = "#e9ecf4"
TEXT_DIM   = "#9aa0b4"
TEXT_FAINT = "#626a80"
SUCCESS    = "#4ade80"
WARN       = "#fbbf24"
DANGER     = "#f87171"

RADIUS     = 12
RADIUS_SM  = 8
FONT       = "Segoe UI"
FONT_MONO  = "Cascadia Mono"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def F(size=13, weight="normal", family=FONT):
    return ctk.CTkFont(family=family, size=size, weight=weight)


# ----------------------------------------------------------------------------
# Buttons
# ----------------------------------------------------------------------------
def ghost(parent, text, command, width=0, height=30, **kw):
    """Secondary button: transparent, hairline border."""
    kwargs = dict(
        text=text, command=command, height=height,
        fg_color="transparent", hover_color=SURFACE_3,
        border_width=1, border_color=BORDER,
        text_color=TEXT_DIM, font=F(11),
        corner_radius=RADIUS_SM)
    if width:
        kwargs["width"] = width
    kwargs.update(kw)
    return ctk.CTkButton(parent, **kwargs)


# ----------------------------------------------------------------------------
# Card — tight numbered step container
# ----------------------------------------------------------------------------
class Card(ctk.CTkFrame):
    def __init__(self, parent, number, title, subtitle=""):
        super().__init__(parent, corner_radius=RADIUS,
                         fg_color=SURFACE,
                         border_width=1, border_color=BORDER)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color=SURFACE_2,
                              corner_radius=RADIUS, height=34)
        header.grid(row=0, column=0, sticky="ew", padx=1, pady=(1, 0))
        header.grid_propagate(False)
        header.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(header, text=str(number),
                     font=F(11, "bold"), text_color=ACCENT_ON,
                     fg_color=ACCENT, corner_radius=6,
                     width=22, height=22)\
            .grid(row=0, column=0, padx=(10, 8), pady=6)
        ctk.CTkLabel(header, text=title, font=F(12, "bold"), anchor="w")\
            .grid(row=0, column=1, sticky="w")
        if subtitle:
            ctk.CTkLabel(header, text=subtitle, font=F(9),
                         text_color=TEXT_FAINT, anchor="e")\
                .grid(row=0, column=2, sticky="e", padx=12)

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 10))
        self.body.grid_columnconfigure(0, weight=1)


# ----------------------------------------------------------------------------
# StatRow — label + value with equal padding (no flex gap)
# ----------------------------------------------------------------------------
class StatRow(ctk.CTkFrame):
    def __init__(self, parent, label: str, value: str = "—"):
        super().__init__(parent, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)

        self.lbl = ctk.CTkLabel(self, text=label, width=62, anchor="w",
                                font=F(10), text_color=TEXT_FAINT)
        self.lbl.grid(row=0, column=0, sticky="w")

        self.val = ctk.CTkLabel(self, text=value, anchor="w",
                                font=F(11), wraplength=200, justify="left")
        self.val.grid(row=0, column=1, sticky="w", padx=(4, 0))

    def set(self, value: str, color=None):
        self.val.configure(text=value or "—")
        if color:
            self.val.configure(text_color=color)


# ----------------------------------------------------------------------------
# PkgList — selectable 3-column PKG list
# ----------------------------------------------------------------------------
class PkgList(ctk.CTkFrame):
    HEADERS = ("Source", "Name", "Size")

    def __init__(self, parent, on_select, height=170):
        super().__init__(parent, fg_color=SURFACE_2,
                         corner_radius=RADIUS_SM, border_width=1,
                         border_color=BORDER)
        self.on_select = on_select
        self.selected_index = None
        self.items = []
        self.row_widgets = []

        hdr = ctk.CTkFrame(self, fg_color=SURFACE_3,
                           corner_radius=0, height=26)
        hdr.pack(fill="x", padx=1, pady=(1, 0))
        hdr.pack_propagate(False)
        for i, (txt, w) in enumerate(zip(self.HEADERS, (80, 230, 72))):
            ctk.CTkLabel(hdr, text=txt, width=w, anchor="w",
                         font=F(9, "bold"), text_color=TEXT_DIM)\
                .pack(side="left", padx=(10 if i == 0 else 4, 0))

        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color=SURFACE_2, height=height - 34,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_LT)
        self.scroll.pack(fill="both", expand=True, padx=2, pady=2)

        self.empty = ctk.CTkLabel(
            self.scroll,
            text=("No PKGs found.\n\n"
                  "Drop *.pkg files into base_pkgs/ or official_pkgs/,\n"
                  "then click ↻ Rescan."),
            justify="center", text_color=TEXT_FAINT, font=F(10))
        self.empty.pack(pady=24)

    def set_items(self, items):
        for w in self.row_widgets:
            w.destroy()
        self.row_widgets = []
        self.items = items
        self.selected_index = None

        if not items:
            self.empty.pack(pady=24)
            return
        self.empty.pack_forget()
        for idx, item in enumerate(items):
            self._make_row(idx, item)

    def _make_row(self, idx, item):
        row = ctk.CTkFrame(self.scroll, fg_color="transparent",
                           corner_radius=6, height=26)
        row.pack(fill="x", padx=2, pady=1)
        row.pack_propagate(False)

        ctk.CTkLabel(row, text=item["source"], width=80, anchor="w",
                     font=F(10), text_color=TEXT_DIM)\
            .pack(side="left", padx=(8, 4))
        ctk.CTkLabel(row, text=item["name"], width=230, anchor="w",
                     font=F(10)).pack(side="left")
        ctk.CTkLabel(row, text=item["size_h"], width=72, anchor="w",
                     font=F(10), text_color=TEXT_DIM).pack(side="left")

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


# ----------------------------------------------------------------------------
# TerminalBox — compact log, expandable
# ----------------------------------------------------------------------------
class TerminalBox(ctk.CTkFrame):
    def __init__(self, parent, height=100):
        super().__init__(parent, fg_color=SIDEBAR,
                         corner_radius=RADIUS_SM,
                         border_width=1, border_color=BORDER)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._collapsed = False
        self._expanded_h = height * 2
        self._normal_h = height

        head = ctk.CTkFrame(self, fg_color="transparent", height=24)
        head.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 0))
        head.grid_propagate(False)

        ctk.CTkLabel(head, text="TERMINAL", font=F(9, "bold"),
                     text_color=TEXT_FAINT).pack(side="left")

        self.expand_btn = ctk.CTkButton(
            head, text="▸", width=24, height=20,
            fg_color="transparent", hover_color=SURFACE_3,
            text_color=TEXT_DIM, font=F(10),
            command=self._toggle)
        self.expand_btn.pack(side="right", padx=(2, 0))

        ctk.CTkButton(head, text="🗑", width=24, height=20,
                      fg_color="transparent", hover_color=SURFACE_3,
                      text_color=TEXT_DIM, font=F(10),
                      command=self.clear).pack(side="right", padx=2)

        self.box = ctk.CTkTextbox(
            self, wrap="word",
            font=F(10, family=FONT_MONO),
            fg_color=SIDEBAR, text_color="#b9c8b9",
            border_width=0, corner_radius=0)
        self.box.grid(row=1, column=0, sticky="nsew",
                      padx=6, pady=(2, 6))
        self.box.configure(state="disabled")
        for tag, col in (("ok", SUCCESS), ("err", DANGER), ("warn", WARN),
                         ("phase", ACCENT_HI), ("dim", TEXT_FAINT)):
            self.box.tag_config(tag, foreground=col)

        self.configure(height=height)
        self.grid_propagate(False)

    def _toggle(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.configure(height=34)
            self.box.grid_remove()
            self.expand_btn.configure(text="▸")
        else:
            self.configure(height=self._expanded_h)
            self.box.grid()
            self.expand_btn.configure(text="▾")

    def write(self, msg: str, tag=None):
        try:
            self.box.configure(state="normal")
            self.box.insert("end", msg + "\n", (tag,) if tag else ())
            self.box.see("end")
            self.box.configure(state="disabled")
        except Exception:
            pass

    def clear(self):
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        self.box.configure(state="disabled")


# ----------------------------------------------------------------------------
# SchemaForm — renders emulator_options.json as mini-cards
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
            box.pack(fill="x", pady=3)
            box.grid_columnconfigure(0, weight=1)

            top = ctk.CTkFrame(box, fg_color="transparent")
            top.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
            top.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(top, text=spec.get("label", key),
                         font=F(11, "bold"), anchor="w")\
                .grid(row=0, column=0, sticky="w")

            kind = spec.get("type", "text")
            default = spec.get("default", "")

            if kind == "choice":
                values = [c["label"] for c in spec["choices"]]
                l2v = {c["label"]: c["value"] for c in spec["choices"]}
                default_label = next(
                    (c["label"] for c in spec["choices"]
                     if c["value"] == default),
                    values[0] if values else "")
                var = tk.StringVar(value=default_label)
                ctk.CTkOptionMenu(top, values=values, variable=var,
                                  width=180, height=28,
                                  fg_color=SURFACE_3, button_color=SURFACE_3,
                                  button_hover_color=BORDER_LT,
                                  font=F(11))\
                    .grid(row=0, column=1, sticky="e")
                self.vars[key] = ("choice", var, l2v)
            else:
                var = tk.StringVar(value=default)
                ctk.CTkEntry(top, textvariable=var, width=260, height=28,
                             fg_color=SURFACE_3, border_color=BORDER,
                             font=F(11))\
                    .grid(row=0, column=1, sticky="e")
                self.vars[key] = ("text", var, None)

            if spec.get("description"):
                ctk.CTkLabel(box, text=spec["description"],
                             font=F(9), text_color=TEXT_FAINT,
                             wraplength=520, justify="left", anchor="w")\
                    .grid(row=1, column=0, sticky="ew",
                          padx=10, pady=(0, 8))

    def values(self) -> dict:
        out = {}
        for key, (kind, var, l2v) in self.vars.items():
            out[key] = (l2v.get(var.get(), var.get())
                        if kind == "choice" else var.get())
        return out
