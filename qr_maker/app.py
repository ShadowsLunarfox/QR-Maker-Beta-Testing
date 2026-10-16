"""A local desktop QR designer built with Tkinter."""

from __future__ import annotations

import queue
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, fields
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageChops, ImageDraw, ImageTk
from tkinterdnd2 import COPY, DND_FILES, TkinterDnD

from .appearance import GlassCard, PALETTES, THEMES, apply_native_material, resolve_theme
from .clipboard import ClipboardBusy, image_formats, set_image_clipboard
from .content import CONTENT_FIELDS, CONTENT_TYPES, PRIMARY_FIELDS, content_description
from .history import History
from .inspection import ScanCheckError, check_export
from .render import GRADIENTS, PRESETS, SHAPES, Options, build_design, export_bytes, render_image, save_design
from .settings import FORMATS, SURFACES, load_settings, options_from_snapshot, save_settings

class QRApp(TkinterDnD.Tk):
    def __init__(self, *, safe_rendering=False):
        super().__init__()
        self.title("QR Studio • Local QR Maker")
        self.geometry("1190x830")
        self.minsize(990, 730)
        self.option_add("*Font", "{Segoe UI} 10")
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qr-render")
        self.export_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qr-export")
        self.events = queue.Queue()
        self.serial = 0
        self.pending = None
        self.active_future = None
        self.paint_pending = None
        self.poll_pending = None
        self.preview_serial = -1
        self.design_serial = -1
        self._painted_preview = None
        self._paint_key = None
        self._surface_key = None
        self._surface = None
        self.design = None
        self.preview = None
        self.photo = None
        self.closed = False
        self.exporting = False
        self.copying = False
        self.checking = False
        self.copy_pending = None
        self.history_pending = None
        self.scan_ok = None
        self.traces_paused = True
        self.settings = load_settings()
        last = self.settings["last"]
        self.theme_var = tk.StringVar(self, last.get("theme") if last.get("theme") in THEMES else "System")
        self.compatibility_var = tk.BooleanVar(self, safe_rendering or last.get("native_glass") is not True)
        self._applied_glass_request = None
        self.theme_name = resolve_theme(self.theme_var.get())
        self.palette = PALETTES[self.theme_name]
        self.shell_background = self.palette["background"]
        self.native_glass = False
        self.theme_pending = None
        self.theme_update_pending = None
        self._theme_applying = False
        self._toned_widgets = []
        self._cards = []
        self.has_error = False
        defaults = options_from_snapshot(last)
        self.vars = {}
        for field in fields(defaults):
            value = getattr(defaults, field.name)
            cls = tk.BooleanVar if isinstance(value, bool) else tk.IntVar if isinstance(value, int) else tk.StringVar
            self.vars[field.name] = cls(self, value=value)
        self.format_var = tk.StringVar(self, last.get("format") if last.get("format") in FORMATS else "PNG")
        self.preview_surface = tk.StringVar(self, last.get("surface") if last.get("surface") in SURFACES else "Checkerboard")
        self.template_var = tk.StringVar(self, "")
        self.status = tk.StringVar(self, "Preparing your preview…")
        self.url_note = tk.StringVar(self, "Add your link. Changes appear automatically.")
        self.details = tk.StringVar(self, "")
        self.advice = tk.StringVar(self, "")
        self.scan_note = tk.StringVar(self, "Scan check: not run")
        self.logo_label = tk.StringVar(self, Path(defaults.logo_path).name if defaults.logo_path else "No logo selected")
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.layout("Theme.TRadiobutton", [("Radiobutton.padding", {"sticky": "nswe", "children": [
            ("Radiobutton.label", {"sticky": "nswe"})]})])
        self._styles()
        self._build()
        self.history = History(self._edit_snapshot())
        self._update_history_buttons()
        self._bind_history(self)
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self._drop_logo)
        self.vars["content_type"].trace_add("write", lambda *_: self._refresh_content(not self.traces_paused))
        self._refresh_content(self.vars["content_type"].get() != "URL")
        self.theme_var.trace_add("write", self._request_theme)
        self.compatibility_var.trace_add("write", self._request_theme)
        self._apply_theme(force=True)
        self.theme_pending = self.after(2000, self._check_system_theme)
        for variable in self.vars.values():
            variable.trace_add("write", self._changed)
        self.preview_surface.trace_add("write", lambda *_: self._request_paint(0))
        self.preview_surface.trace_add("write", self._history_changed)
        self.format_var.trace_add("write", self._format_changed)
        self.traces_paused = False
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Control-s>", lambda _: self._export())
        self.bind("<Control-Shift-C>", lambda _: self._copy_image())
        self.bind("<Control-Shift-F12>", self._use_compatible_rendering)
        self.bind("<Return>", lambda _: self._schedule(0))
        self.poll_pending = self.after(25, self._poll)
        self._schedule(0)

    def _styles(self):
        p = self.palette
        style = self.style
        style.configure(".", background=p["card"], foreground=p["ink"],
                        selectbackground=p["accent"], selectforeground=p["accent_text"],
                        troughcolor=p["stage"], bordercolor=p["line"], lightcolor=p["line"], darkcolor=p["line"])
        style.configure("TFrame", background=p["card"])
        style.configure("Shell.TFrame", background=self.shell_background)
        style.configure("Card.TFrame", background=p["card"])
        style.configure("TLabel", background=p["card"], foreground=p["ink"])
        style.configure("Card.TLabel", background=p["card"], foreground=p["ink"])
        style.configure("Muted.TLabel", foreground=p["muted"])
        style.configure("CardMuted.TLabel", background=p["card"], foreground=p["muted"])
        style.configure("Heading.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Small.TLabel", font=("Segoe UI", 9), foreground=p["muted"])
        style.configure("Footer.TLabel", background=self.shell_background, foreground=p["muted"], font=("Segoe UI", 9))
        style.configure("TButton", padding=(10, 8), background=p["input"], foreground=p["ink"], borderwidth=1)
        style.map("TButton", background=[("disabled", p["card"]), ("pressed", p["selected"]), ("active", p["hover"])],
                  foreground=[("disabled", p["disabled_ink"])], bordercolor=[("focus", p["accent"])])
        style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_text"], font=("Segoe UI", 10, "bold"), borderwidth=0, padding=(18, 11))
        style.map("Accent.TButton", background=[("disabled", p["disabled"]), ("active", p["accent_hover"])],
                  foreground=[("disabled", p["disabled_ink"]), ("!disabled", p["accent_text"])])
        for name in ("TEntry", "TCombobox", "TSpinbox"):
            style.configure(name, padding=7, fieldbackground=p["input"], background=p["input"], foreground=p["ink"],
                            arrowcolor=p["muted"], insertcolor=p["ink"], bordercolor=p["line"])
            style.map(name, fieldbackground=[("readonly", p["input"]), ("disabled", p["card"])],
                      foreground=[("disabled", p["disabled_ink"]), ("readonly", p["ink"])],
                      bordercolor=[("focus", p["accent"]), ("active", p["accent"])],
                      background=[("active", p["hover"])])
        style.configure("TNotebook", background=p["card"], borderwidth=0, tabmargins=(0, 0, 0, 10))
        style.configure("TNotebook.Tab", padding=(15, 9), background=p["card"], foreground=p["muted"])
        style.map("TNotebook.Tab", background=[("selected", p["selected"]), ("active", p["hover"])],
                  foreground=[("selected", p["ink"]), ("active", p["ink"])])
        style.configure("TCheckbutton", background=p["card"], foreground=p["ink"], padding=(0, 5),
                        indicatorbackground=p["input"], indicatorforeground=p["accent_text"])
        style.map("TCheckbutton", background=[("active", p["card"])], indicatorbackground=[("selected", p["accent"])])
        style.configure("Horizontal.TScale", background=p["input"], troughcolor=p["line"], borderwidth=0)
        style.map("Horizontal.TScale", background=[("active", p["accent"])])
        style.configure("Vertical.TScrollbar", background=p["line"], troughcolor=p["card"],
                        arrowcolor=p["muted"], borderwidth=0, arrowsize=12)
        style.map("Vertical.TScrollbar", background=[("active", p["muted"])])
        style.configure("Theme.TRadiobutton", background=p["card"], foreground=p["muted"],
                        padding=(12, 8), anchor="center", font=("Segoe UI", 9))
        style.map("Theme.TRadiobutton", background=[("selected", p["selected"]), ("active", p["hover"])],
                  foreground=[("selected", p["ink"]), ("active", p["ink"])])
        style.configure("Shell.TCheckbutton", background=self.shell_background, foreground=p["muted"],
                        font=("Segoe UI", 9), padding=(0, 3))
        style.map("Shell.TCheckbutton", background=[("active", self.shell_background)])
        self.option_add("*TCombobox*Listbox.background", p["input"])
        self.option_add("*TCombobox*Listbox.foreground", p["ink"])
        self.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", p["accent_text"])

    def _tone(self, widget, **roles):
        self._toned_widgets.append((widget, roles))
        widget.configure(**{option: self.shell_background if role == "shell" else self.palette[role]
                            for option, role in roles.items()})
        return widget

    def _card(self, parent, **kwargs):
        card = GlassCard(parent, self.palette, self.shell_background, **kwargs)
        self._cards.append(card)
        return card

    def _apply_theme(self, force=False):
        if self.closed or self._theme_applying:
            return
        name = resolve_theme(self.theme_var.get())
        allow_glass = not self.compatibility_var.get()
        if name == self.theme_name and allow_glass == self._applied_glass_request and not force:
            return
        self._theme_applying = True
        try:
            self.palette = PALETTES[name]
            self.native_glass = apply_native_material(self, name == "Dark", allow_glass=allow_glass)
            self.shell_background = "#000000" if self.native_glass else self.palette["background"]
            self.configure(background=self.shell_background)
            self._styles()
            for widget, roles in self._toned_widgets:
                widget.configure(**{option: self.shell_background if role == "shell" else self.palette[role]
                                    for option, role in roles.items()})
            for card in self._cards:
                card.set_palette(self.palette, self.shell_background)
            self.canvas.itemconfigure(self.placeholder_item, fill=self.palette["muted"])
            self._set_advice_color()
            self._set_scan_color()
            self._update_popdowns(self)
            self._painted_preview = None
            self._request_paint(0)
            self.theme_name = name
            self._applied_glass_request = allow_glass
        finally:
            self._theme_applying = False

    def _request_theme(self, *_):
        if not self.closed and self.theme_update_pending is None:
            self.theme_update_pending = self.after_idle(self._flush_theme)

    def _flush_theme(self):
        self.theme_update_pending = None
        self._apply_theme()

    def _use_compatible_rendering(self, _event=None):
        self.compatibility_var.set(True)
        self.status.set("Compatibility rendering enabled.")
        return "break"

    def _combobox(self, parent, **kwargs):
        widget = ttk.Combobox(parent, **kwargs)
        widget.configure(postcommand=lambda: self._style_popdown(widget))
        return widget

    def _style_popdown(self, widget):
        popdown = self.tk.call("ttk::combobox::PopdownWindow", widget)
        self.tk.call(f"{popdown}.f.l", "configure", "-background", self.palette["input"],
                     "-foreground", self.palette["ink"], "-selectbackground", self.palette["accent"],
                     "-selectforeground", self.palette["accent_text"])

    def _update_popdowns(self, parent):
        for widget in parent.winfo_children():
            if isinstance(widget, ttk.Combobox):
                if self.tk.getboolean(self.tk.call("winfo", "exists", f"{widget}.popdown")):
                    self._style_popdown(widget)
            self._update_popdowns(widget)

    def _set_advice_color(self):
        role = "error" if self.has_error else "warning" if self.design and self.design.warnings else "muted"
        self.advice_label.configure(foreground=self.palette[role])

    def _set_scan_color(self):
        role = "warning" if self.scan_ok is False else "accent" if self.scan_ok else "muted"
        self.scan_label.configure(foreground=self.palette[role])

    def _check_system_theme(self):
        self.theme_pending = None
        if self.closed:
            return
        if self.theme_var.get() == "System":
            self._request_theme()
        self.theme_pending = self.after(2000, self._check_system_theme)

    def _build(self):
        header = self._tone(tk.Frame(self, height=88), bg="shell")
        header.pack(fill="x")
        mark = tk.Canvas(header, width=44, height=44, bg="#2563d9", highlightthickness=0)
        mark.pack(side="left", padx=(26, 14), pady=20)
        for x, y in ((8, 8), (25, 8), (8, 25)):
            mark.create_rectangle(x, y, x + 10, y + 10, outline="white", width=2)
        mark.create_rectangle(25, 25, 29, 29, fill="white", outline="")
        mark.create_rectangle(32, 32, 36, 36, fill="white", outline="")
        title = self._tone(tk.Frame(header), bg="shell")
        title.pack(side="left")
        self._tone(tk.Label(title, text="QR Studio", font=("Segoe UI", 22, "bold")), fg="ink", bg="shell").pack(anchor="w")
        self._tone(tk.Label(title, text="Your link. Your style.", font=("Segoe UI", 10)), fg="muted", bg="shell").pack(anchor="w")
        appearance = self._tone(tk.Frame(header), bg="shell")
        appearance.pack(side="right", padx=26)
        self._tone(tk.Label(appearance, text="APPEARANCE", font=("Segoe UI", 8, "bold")), fg="muted", bg="shell").pack(anchor="e", pady=(0, 5))
        modes = self._tone(tk.Frame(appearance, highlightthickness=1), bg="card", highlightbackground="line")
        modes.pack()
        for mode in THEMES:
            ttk.Radiobutton(modes, text=mode, value=mode, variable=self.theme_var, style="Theme.TRadiobutton", takefocus=True).pack(side="left")
        ttk.Checkbutton(appearance, text="Compatibility rendering", variable=self.compatibility_var,
                        style="Shell.TCheckbutton").pack(anchor="e", pady=(5, 0))
        self._tone(tk.Label(header, text="LOCAL CREATION\nNO UPLOADS", font=("Segoe UI", 8, "bold"), justify="right"),
                   bg="shell", fg="muted").pack(side="right", padx=(8, 4))

        main = ttk.Frame(self, style="Shell.TFrame", padding=(24, 0, 24, 8))
        main.pack(fill="both", expand=True)
        link_surface = self._card(main, height=130, padding=18)
        link_surface.pack(fill="x", pady=(0, 16))
        link_card = link_surface.body
        ttk.Label(link_card, text="QR CONTENT", style="CardMuted.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        line = ttk.Frame(link_card, style="Card.TFrame")
        line.pack(fill="x", pady=(8, 5))
        self._combobox(line, textvariable=self.vars["content_type"], values=CONTENT_TYPES, state="readonly", width=10).pack(side="left", padx=(0, 10))
        self.url_entry = ttk.Entry(line, textvariable=self.vars["url"], font=("Segoe UI", 12))
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ttk.Button(line, text="Generate", style="Accent.TButton", command=lambda: self._schedule(0)).pack(side="right")
        ttk.Button(line, text="Details", command=lambda: self.notebook.select(self.content_page)).pack(side="right", padx=(0, 8))
        ttk.Label(link_card, textvariable=self.url_note, style="CardMuted.TLabel").pack(anchor="w")

        body = ttk.Frame(main, style="Shell.TFrame")
        body.pack(fill="both", expand=True)
        sidebar_surface = self._card(body, width=400, padding=16)
        sidebar_surface.pack(side="left", fill="y", padx=(0, 16))
        sidebar = sidebar_surface.body
        notebook = ttk.Notebook(sidebar)
        self.notebook = notebook
        notebook.pack(fill="both", expand=True)
        for name, builder in (("Design", self._design_tab), ("Content", self._content_tab), ("Logo", self._logo_tab), ("Export", self._export_tab)):
            outer = ttk.Frame(notebook)
            notebook.add(outer, text=name)
            if name == "Content":
                self.content_page = outer
            elif name == "Logo":
                self.logo_page = outer
            scroll = self._tone(tk.Canvas(outer, highlightthickness=0), background="card")
            scrollbar = ttk.Scrollbar(outer, orient="vertical", command=scroll.yview)
            scroll.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            scroll.pack(side="left", fill="both", expand=True)
            inner = ttk.Frame(scroll, padding=(10, 16, 12, 12))
            window = scroll.create_window((0, 0), window=inner, anchor="nw")
            inner.bind("<Configure>", lambda event, c=scroll: c.configure(scrollregion=c.bbox("all")))
            scroll.bind("<Configure>", lambda event, c=scroll, w=window: c.itemconfigure(w, width=event.width))
            builder(inner)
            # Scroll only the tab beneath the pointer; do not consume combobox scrolling.
            def wheel(event, c=scroll):
                if isinstance(event.widget, (ttk.Combobox, ttk.Spinbox)):
                    return
                if c.winfo_rootx() <= event.x_root < c.winfo_rootx() + c.winfo_width() and c.winfo_rooty() <= event.y_root < c.winfo_rooty() + c.winfo_height():
                    c.yview_scroll(-int(event.delta / 120), "units")
            self.bind("<MouseWheel>", wheel, add="+")
        history_actions = ttk.Frame(sidebar)
        history_actions.pack(side="bottom", fill="x", pady=(10, 6), before=notebook)
        self.undo_button = ttk.Button(history_actions, text="Undo  Ctrl+Z", command=self._undo)
        self.undo_button.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.redo_button = ttk.Button(history_actions, text="Redo  Ctrl+Y", command=self._redo)
        self.redo_button.pack(side="left", fill="x", expand=True)
        ttk.Button(sidebar, text="Reset design", command=self._reset).pack(side="bottom", fill="x", before=history_actions)

        preview_surface = self._card(body, padding=20)
        preview_surface.pack(side="left", fill="both", expand=True)
        preview_card = preview_surface.body
        preview_card.columnconfigure(0, weight=1)
        preview_card.rowconfigure(1, weight=1, minsize=90)
        top = ttk.Frame(preview_card, style="Card.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Live preview", style="Card.TLabel", font=("Segoe UI", 13, "bold")).pack(side="left")
        self._combobox(top, textvariable=self.preview_surface, values=SURFACES, state="readonly", width=13).pack(side="right")
        self.canvas = self._tone(tk.Canvas(preview_card, highlightthickness=1), background="stage", highlightbackground="line")
        self.canvas.grid(row=1, column=0, sticky="nsew", pady=(12, 8))
        self.preview_item = self.canvas.create_image(0, 0, state="hidden")
        self.placeholder_item = self.canvas.create_text(0, 0, text="Your QR code will appear here", fill=self.palette["muted"], font=("Segoe UI", 12))
        self.canvas.bind("<Configure>", lambda _: self._request_paint())
        self.details_label = ttk.Label(preview_card, textvariable=self.details, style="CardMuted.TLabel", wraplength=440)
        self.details_label.grid(row=2, column=0, sticky="ew")
        self.advice_label = ttk.Label(preview_card, textvariable=self.advice, style="CardMuted.TLabel", wraplength=480)
        self.advice_label.grid(row=3, column=0, sticky="ew", pady=(8, 8))
        self.scan_label = ttk.Label(preview_card, textvariable=self.scan_note, style="CardMuted.TLabel", wraplength=480)
        self.scan_label.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        quick_actions = ttk.Frame(preview_card)
        quick_actions.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        self.copy_button = ttk.Button(quick_actions, text="Copy image", command=self._copy_image, state="disabled")
        self.copy_button.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.check_button = ttk.Button(quick_actions, text="Check scan", command=self._check_scan, state="disabled")
        self.check_button.pack(side="left", fill="x", expand=True)
        self.export_button = ttk.Button(preview_card, text="Export QR code", style="Accent.TButton", command=self._export, state="disabled")
        self.export_button.grid(row=6, column=0, sticky="ew")
        footer = ttk.Frame(self, style="Shell.TFrame", padding=(26, 5, 26, 14))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status, style="Footer.TLabel").pack(side="left")
        ttk.Label(footer, text="Ctrl+S export  /  Ctrl+Shift+C copy", style="Footer.TLabel").pack(side="right")
        self.url_entry.focus_set()

    def _label(self, parent, text):
        ttk.Label(parent, text=text, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 6))

    def _entry(self, parent, label, name, **kwargs):
        self._label(parent, label)
        ttk.Entry(parent, textvariable=self.vars[name], **kwargs).pack(fill="x")

    def _text_input(self, parent, name, height=5):
        widget = self._tone(tk.Text(parent, height=height, wrap="word", relief="flat", padx=8, pady=8),
                            bg="input", fg="ink", insertbackground="ink", selectbackground="accent", selectforeground="accent_text")
        widget.pack(fill="x")
        widget.insert("1.0", self.vars[name].get())
        widget.edit_modified(False)

        def edited(_event=None):
            if widget.edit_modified():
                value = widget.get("1.0", "end-1c")
                if value != self.vars[name].get():
                    self.vars[name].set(value)
                widget.edit_modified(False)

        def sync(*_):
            value = self.vars[name].get()
            if widget.get("1.0", "end-1c") != value:
                widget.delete("1.0", "end")
                widget.insert("1.0", value)
                widget.edit_modified(False)

        widget.bind("<<Modified>>", edited)
        self.vars[name].trace_add("write", sync)

    def _content_tab(self, parent):
        ttk.Label(parent, text="What should it share?", style="Heading.TLabel").pack(anchor="w")
        self._combo(parent, "Content type", "content_type", CONTENT_TYPES)
        self.content_forms = {}
        for kind in CONTENT_TYPES:
            form = ttk.Frame(parent)
            self.content_forms[kind] = form
            if kind == "URL":
                self._entry(form, "Website URL", "url")
            elif kind == "Text":
                self._label(form, "Text (including multiple lines)")
                self._text_input(form, "text", height=8)
            elif kind == "Wi-Fi":
                self._entry(form, "Network name (SSID)", "wifi_ssid")
                self._combo(form, "Security (nopass = open)", "wifi_security", ("WPA", "WEP", "nopass"))
                self._entry(form, "Password", "wifi_password", show="\u2022")
                ttk.Checkbutton(form, text="Hidden network", variable=self.vars["wifi_hidden"]).pack(anchor="w", pady=(10, 0))
                ttk.Label(form, text="The password stays in this session; settings and templates do not save it.", style="Small.TLabel", wraplength=305).pack(anchor="w", pady=(12, 0))
            elif kind == "Contact":
                for label, field in (("Full name", "contact_name"), ("Phone", "contact_phone"), ("Email", "contact_email"),
                                     ("Organization", "contact_organization"), ("Address", "contact_address"), ("Website", "contact_url")):
                    self._entry(form, label, field)
            elif kind == "Phone":
                self._entry(form, "Phone number", "phone")
                ttk.Label(form, text="Example: +60 12 345 6789", style="Small.TLabel").pack(anchor="w", pady=(10, 0))
            else:
                self._entry(form, "Recipient email", "email_to")
                self._entry(form, "Subject (optional)", "email_subject")
                self._label(form, "Message (optional)")
                self._text_input(form, "email_body")

    def _refresh_content(self, select=False):
        kind = self.vars["content_type"].get()
        for name, form in self.content_forms.items():
            form.pack_forget()
            if name == kind:
                form.pack(fill="x")
        self.url_entry.configure(textvariable=self.vars[PRIMARY_FIELDS.get(kind, "url")])
        if select and kind != "URL":
            self.notebook.select(self.content_page)

    def _combo(self, parent, label, name, values):
        self._label(parent, label)
        self._combobox(parent, textvariable=self.vars[name], values=values, state="readonly").pack(fill="x")

    def _color_row(self, parent, label, name):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=15).pack(side="left")
        entry = ttk.Entry(row, textvariable=self.vars[name], width=10)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        swatch = tk.Button(row, width=3, relief="flat", cursor="hand2", command=lambda: self._pick_color(name))
        swatch.pack(side="right", ipady=3)
        def update(*_):
            try:
                swatch.configure(bg=self.vars[name].get(), activebackground=self.vars[name].get())
            except tk.TclError:
                swatch.configure(bg=self.palette["line"])
        self.vars[name].trace_add("write", update)
        update()

    def _slider(self, parent, label, name, start, end, suffix="%"):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(12, 2))
        ttk.Label(row, text=label).pack(side="left")
        value = tk.StringVar(self)
        def update(*_):
            try:
                value.set(f"{self.vars[name].get()}{suffix}")
            except tk.TclError:
                pass
        self.vars[name].trace_add("write", update)
        update()
        ttk.Label(row, textvariable=value, style="Muted.TLabel").pack(side="right")
        slider_value = tk.DoubleVar(self, self.vars[name].get())
        def moved(number):
            value = round(float(number))
            if value != self.vars[name].get():
                self.vars[name].set(value)
        ttk.Scale(parent, from_=start, to=end, variable=slider_value, command=moved).pack(fill="x")
        def sync(*_):
            try:
                slider_value.set(self.vars[name].get())
            except tk.TclError:
                pass
        self.vars[name].trace_add("write", sync)

    def _design_tab(self, parent):
        ttk.Label(parent, text="Start with a look", style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
        presets = ttk.Frame(parent)
        presets.pack(fill="x")
        for index, name in enumerate(PRESETS):
            row, col = divmod(index, 3)
            ttk.Button(presets, text=name, command=lambda n=name: self._preset(n)).grid(row=row, column=col, sticky="ew", padx=(0, 5), pady=(0, 5))
            presets.columnconfigure(col, weight=1)
        self._label(parent, "Your templates")
        self.template_combo = self._combobox(parent, textvariable=self.template_var, state="readonly")
        self.template_combo.pack(fill="x")
        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(6, 0))
        for column, (label, command) in enumerate((("Save current", self._save_template), ("Apply", self._apply_template), ("Delete", self._delete_template))):
            ttk.Button(actions, text=label, command=command).grid(row=0, column=column, sticky="ew", padx=(0, 5))
            actions.columnconfigure(column, weight=1)
        self._refresh_templates()
        self._label(parent, "Colors")
        self._color_row(parent, "Primary", "foreground")
        self._color_row(parent, "Secondary", "secondary")
        self._color_row(parent, "Corner / structure", "finder_color")
        self._color_row(parent, "Background", "background")
        self._combo(parent, "Color effect", "gradient", GRADIENTS)
        self._combo(parent, "Module shape", "shape", SHAPES)
        self._combo(parent, "Corner style", "finder_style", ("Square", "Rounded"))
        ttk.Checkbutton(parent, text="Transparent background", variable=self.vars["transparent"]).pack(anchor="w", pady=(12, 0))
        self._slider(parent, "QR opacity", "foreground_opacity", 10, 100)
        self._slider(parent, "Background opacity", "background_opacity", 0, 100)
        ttk.Label(parent, text="Secondary color is used for gradients.\nThe preview surface is for viewing only.", style="Small.TLabel", wraplength=320).pack(anchor="w", pady=(14, 0))

    def _logo_tab(self, parent):
        ttk.Label(parent, text="Make it yours", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(parent, text="Place your logo in the center of the QR code.", style="Muted.TLabel", wraplength=320).pack(anchor="w", pady=(8, 16))
        ttk.Button(parent, text="Choose logo…", style="Accent.TButton", command=self._choose_logo).pack(fill="x")
        ttk.Label(parent, textvariable=self.logo_label, wraplength=320, style="Small.TLabel").pack(anchor="w", pady=(10, 8))
        ttk.Button(parent, text="Remove logo", command=self._remove_logo).pack(fill="x")
        ttk.Label(parent, text="You can also drop an image anywhere in this window.", style="Small.TLabel", wraplength=310).pack(anchor="w", pady=(12, 0))
        self._combo(parent, "Logo framing", "logo_crop", ("Fit", "Center crop", "Circle"))
        self._slider(parent, "Logo inner padding", "logo_padding", 0, 30)
        self._slider(parent, "Logo size", "logo_size", 8, 24)
        self._slider(parent, "Logo opacity", "logo_opacity", 0, 100)
        ttk.Checkbutton(parent, text="Add a solid plate behind the logo", variable=self.vars["logo_plate"]).pack(anchor="w", pady=(18, 6))
        self._color_row(parent, "Plate color", "plate_color")
        self._combo(parent, "Plate shape", "plate_style", ("Rounded", "Square", "Circle"))
        ttk.Label(parent, text="Tip: an 18% logo and a white plate are a good starting point. All codes use high error correction. Test your final design with your phone.", style="Muted.TLabel", wraplength=320).pack(anchor="w", pady=(22, 0))

    def _export_tab(self, parent):
        ttk.Label(parent, text="Ready to share", style="Heading.TLabel").pack(anchor="w")
        self._label(parent, "File format")
        self._combobox(parent, textvariable=self.format_var, values=FORMATS, state="readonly").pack(fill="x")
        self._combo(parent, "Image size (pixels)", "size", (256, 512, 768, 1024, 1536, 2048, 4096))
        self._label(parent, "Quiet margin (modules)")
        ttk.Spinbox(parent, textvariable=self.vars["border"], from_=4, to=12, state="readonly", width=8).pack(fill="x")
        self._combo(parent, "Rotation (clockwise degrees)", "rotation", (0, 90, 180, 270))
        ttk.Label(parent, text="PNG / WebP\nKeep transparency and exact pixel dimensions.\n\nSVG\nVector QR shapes that stay sharp at any size. Your logo is embedded in the file.\n\nJPG\nTransparent areas are flattened onto white.\n\nA quiet margin of at least 4 modules helps scanners find your QR code.", style="Muted.TLabel", wraplength=320, justify="left").pack(anchor="w", pady=(22, 0))
        ttk.Button(parent, text="Export QR code…", style="Accent.TButton", command=self._export).pack(fill="x", pady=(22, 0))

    def _pick_color(self, name):
        try:
            initial = self.vars[name].get()
            self.winfo_rgb(initial)
        except tk.TclError:
            initial = "#172033"
        _, value = colorchooser.askcolor(color=initial, title="Choose a color", parent=self)
        if value:
            self.vars[name].set(value)

    def _edit_snapshot(self):
        return {"options": asdict(self._collect_options()), "format": self.format_var.get(),
                "surface": self.preview_surface.get()}

    def _snapshot(self):
        return {**self._edit_snapshot(), "theme": self.theme_var.get(),
                "native_glass": not self.compatibility_var.get()}

    def _bind_history(self, widget):
        tag = f"QRHistory{id(self)}"
        if widget is self:
            self.bind_class(tag, "<Control-z>", self._undo)
            self.bind_class(tag, "<Control-y>", self._redo)
            self.bind_class(tag, "<Control-Shift-Z>", self._redo)
        widget.bindtags((tag, *widget.bindtags()))
        for child in widget.winfo_children():
            self._bind_history(child)

    def _history_changed(self, *_):
        if self.traces_paused:
            return
        if self.history_pending is not None:
            self.after_cancel(self.history_pending)
        self.history_pending = self.after(400, self._commit_history)
        self.undo_button.configure(state="normal")
        self.redo_button.configure(state="disabled")

    def _format_changed(self, *_):
        self._history_changed()
        self.scan_ok = None
        self.scan_note.set("Scan check: not run")
        self._set_scan_color()

    def _commit_history(self):
        if self.history_pending is not None:
            self.after_cancel(self.history_pending)
            self.history_pending = None
        try:
            self.history.push(self._edit_snapshot())
        except ValueError:
            pass
        self._update_history_buttons()

    def _update_history_buttons(self):
        self.undo_button.configure(state="normal" if self.history.can_undo else "disabled")
        self.redo_button.configure(state="normal" if self.history.can_redo else "disabled")

    def _restore_edit(self, snapshot):
        previous_kind = self.vars["content_type"].get()
        self.traces_paused = True
        try:
            for name, value in asdict(options_from_snapshot(snapshot)).items():
                self.vars[name].set(value)
            self.format_var.set(snapshot["format"])
            self.preview_surface.set(snapshot["surface"])
            path = self.vars["logo_path"].get()
            self.logo_label.set(Path(path).name if path else "No logo selected")
        finally:
            self.traces_paused = False
        self._refresh_content(previous_kind != self.vars["content_type"].get())
        self._update_history_buttons()
        self._schedule(0)

    def _undo(self, _event=None):
        self._commit_history()
        if self.history.can_undo:
            self._restore_edit(self.history.undo())
        return "break"

    def _redo(self, _event=None):
        self._commit_history()
        if self.history.can_redo:
            self._restore_edit(self.history.redo())
        return "break"

    def _store_settings(self):
        try:
            self.settings["last"] = self._snapshot()
            self.settings["last"]["options"]["wifi_password"] = ""
        except ValueError:
            pass  # Keep the previous session if a numeric field is incomplete.
        save_settings(self.settings)

    def _refresh_templates(self):
        names = sorted(self.settings["templates"], key=str.casefold)
        self.template_combo.configure(values=names)
        if self.template_var.get() not in names:
            self.template_var.set(names[0] if names else "")

    def _save_template(self):
        try:
            snapshot = self._snapshot()
        except ValueError as exc:
            messagebox.showerror("Could not save template", str(exc), parent=self)
            return
        name = simpledialog.askstring("Save design template", "Template name:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.settings["templates"] and not messagebox.askyesno("Replace template", f'Replace "{name}"?', parent=self):
            return
        for field_name in CONTENT_FIELDS:
            snapshot["options"].pop(field_name, None)
        snapshot.pop("theme", None)
        snapshot.pop("native_glass", None)
        self.settings["templates"][name] = snapshot
        self.template_var.set(name)
        self._refresh_templates()
        try:
            self._store_settings()
        except OSError as exc:
            messagebox.showerror("Could not save settings", str(exc), parent=self)
            return
        self.status.set(f"Template saved: {name}")

    def _apply_template(self):
        snapshot = self.settings["templates"].get(self.template_var.get())
        if snapshot is None:
            return
        self._commit_history()
        options = asdict(options_from_snapshot(snapshot))
        options.update({name: self.vars[name].get() for name in CONTENT_FIELDS})
        self.traces_paused = True
        try:
            for name, value in options.items():
                self.vars[name].set(value)
            if snapshot.get("format") in FORMATS:
                self.format_var.set(snapshot["format"])
            if snapshot.get("surface") in SURFACES:
                self.preview_surface.set(snapshot["surface"])
            self.logo_label.set(Path(options["logo_path"]).name if options["logo_path"] else "No logo selected")
        finally:
            self.traces_paused = False
        self._schedule(0)
        self._commit_history()

    def _delete_template(self):
        name = self.template_var.get()
        if name not in self.settings["templates"]:
            return
        del self.settings["templates"][name]
        self._refresh_templates()
        try:
            self._store_settings()
        except OSError as exc:
            messagebox.showerror("Could not save settings", str(exc), parent=self)
            return
        self.status.set(f"Template deleted: {name}")

    def _preset(self, name):
        self._commit_history()
        a, b, bg, gradient, shape = PRESETS[name]
        self.traces_paused = True
        for key, value in dict(foreground=a, secondary=b, background=bg, gradient=gradient, shape=shape,
                               finder_color=a, finder_style="Rounded" if shape != "Square" else "Square",
                               foreground_opacity=100, background_opacity=100, transparent=False).items():
            self.vars[key].set(value)
        self.traces_paused = False
        self._schedule()
        self._commit_history()

    def _reset(self):
        self._commit_history()
        content = {name: self.vars[name].get() for name in CONTENT_FIELDS}
        self.traces_paused = True
        defaults = Options(**content)
        for field in fields(defaults):
            self.vars[field.name].set(getattr(defaults, field.name))
        self.logo_label.set("No logo selected")
        self.traces_paused = False
        self._schedule()
        self._commit_history()

    def _choose_logo(self):
        path = filedialog.askopenfilename(parent=self, title="Choose a center logo", filetypes=(
            ("Logo images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("All files", "*.*")))
        if path:
            self._set_logo(path)

    def _set_logo(self, path):
        try:
            with Image.open(path) as image:
                image.verify()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            messagebox.showerror("Could not open logo", "Choose a valid PNG, JPG, WebP, BMP, or GIF image.", parent=self)
            return False
        self._commit_history()
        self.logo_label.set(Path(path).name)
        self.vars["logo_path"].set(str(Path(path).resolve()))
        self._commit_history()
        return True

    def _drop_logo(self, event):
        paths = self.tk.splitlist(event.data)
        if len(paths) != 1:
            self.status.set("Drop one logo image at a time.")
            return "refuse_drop"
        if self._set_logo(paths[0]):
            self.notebook.select(self.logo_page)
            return COPY
        return "refuse_drop"

    def _remove_logo(self):
        self._commit_history()
        self.logo_label.set("No logo selected")
        self.vars["logo_path"].set("")
        self._commit_history()

    def _changed(self, *_):
        if not self.traces_paused:
            self._history_changed()
            self._schedule()

    def _schedule(self, delay=100):
        self.serial += 1
        self.export_button.configure(state="disabled")
        self.copy_button.configure(state="disabled")
        self.check_button.configure(state="disabled")
        self.scan_ok = None
        self.scan_note.set("Scan check: not run")
        self._set_scan_color()
        self.status.set("Updating preview…")
        if self.active_future is not None:
            self.active_future.cancel()
        if self.pending is not None:
            if delay:
                return  # Render the latest values at most once per interval while dragging.
            self.after_cancel(self.pending)
        self.pending = self.after(delay, self._generate)

    def _collect_options(self):
        try:
            return Options(**{name: variable.get() for name, variable in self.vars.items()})
        except tk.TclError as exc:
            raise ValueError("Check the image size and margin values.") from exc

    def _generate(self):
        self.pending = None
        serial = self.serial
        try:
            options = self._collect_options()
        except ValueError as exc:
            self._error(str(exc))
            return
        def render():
            try:
                if self.closed or serial != self.serial:
                    return
                design = build_design(options)
                if self.closed or serial != self.serial:
                    return
                preview = render_image(design, min(options.size, 760))
                if not self.closed:
                    self.events.put(("preview", serial, (design, preview)))
            except Exception as exc:
                self.events.put(("error", serial, str(exc)))
        self.active_future = self.executor.submit(render)

    def _error(self, message):
        self.has_error = True
        self.design = None
        self.design_serial = -1
        self.preview = None
        self.preview_serial = self.serial
        self.details.set("")
        self.url_note.set("Check the content or design settings below.")
        self.advice.set(message)
        self._set_advice_color()
        self.status.set("Check your settings")
        self.export_button.configure(state="disabled")
        self.copy_button.configure(state="disabled")
        self.check_button.configure(state="disabled")
        self._request_paint(0)

    def _valid_design(self):
        return self.design is not None and self.design_serial == self.serial and self.pending is None

    def _update_action_buttons(self):
        valid = self._valid_design()
        for button, busy in ((self.export_button, self.exporting), (self.copy_button, self.copying), (self.check_button, self.checking)):
            button.configure(state="normal" if valid and not busy else "disabled")

    def _copy_image(self):
        if self.copying or not self._valid_design():
            return
        self.copying = True
        self._update_action_buttons()
        self.status.set("Preparing image for the clipboard...")
        design, serial = self.design, self.serial

        def prepare():
            try:
                data = image_formats(render_image(design))
                self.events.put(("clipboard_ready", serial, data))
            except Exception as exc:
                self.events.put(("copy_error", serial, str(exc)))

        self.export_executor.submit(prepare)

    def _finish_copy(self, serial, data, attempt=0):
        self.copy_pending = None
        if self.closed:
            return
        if serial != self.serial:
            self.copying = False
            self.status.set("The design changed. Copy the latest image again.")
            self._update_action_buttons()
            return
        try:
            set_image_clipboard(self.winfo_id(), data)
        except ClipboardBusy as exc:
            if attempt < 5:
                self.copy_pending = self.after(60, lambda: self._finish_copy(serial, data, attempt + 1))
                return
            messagebox.showerror("Could not copy image", str(exc), parent=self)
            self.status.set("Copy failed. Try again.")
        except OSError as exc:
            messagebox.showerror("Could not copy image", str(exc), parent=self)
            self.status.set("Copy failed. Try again.")
        else:
            self.status.set("Image copied. Paste it into your chat or document.")
        self.copying = False
        self._update_action_buttons()

    def _check_scan(self):
        if self.checking or not self._valid_design():
            return
        self.checking = True
        self._update_action_buttons()
        self.scan_note.set("Checking the final exported image...")
        design, serial = self.design, self.serial
        format_name = self.format_var.get()
        extension = {"PNG": ".png", "SVG": ".svg", "WebP": ".webp", "JPG": ".jpg"}[format_name]

        def check():
            try:
                result = check_export(export_bytes(design, extension), extension, design.payload)
                self.events.put(("scan_result", serial, (format_name, result)))
            except Exception as exc:
                self.events.put(("scan_error", serial, (format_name, str(exc))))

        self.export_executor.submit(check)

    def _save_unchecked(self, path, data, serial):
        self.exporting = True
        self._update_action_buttons()

        def save():
            try:
                Path(path).write_bytes(data)
                self.events.put(("saved_unchecked", serial, path))
            except Exception as exc:
                self.events.put(("save_error", serial, str(exc)))

        self.export_executor.submit(save)

    def _poll(self):
        self.poll_pending = None
        if self.closed:
            return
        while True:
            try:
                kind, serial, result = self.events.get_nowait()
            except queue.Empty:
                break
            if kind in ("saved", "saved_unchecked", "save_error"):
                self.exporting = False
                if kind in ("saved", "saved_unchecked"):
                    self.status.set(f"Saved: {result}")
                    if serial == self.serial and kind == "saved":
                        self.scan_ok = True
                        self.scan_note.set("Scan check passed: the saved content matches.")
                        self._set_scan_color()
                else:
                    messagebox.showerror("Could not export", result, parent=self)
                    self.status.set("Export failed. Your design is still available.")
                self._update_action_buttons()
            elif kind == "save_check_failed":
                self.exporting = False
                path, data, message = result
                self.status.set("Scan check failed. The export has not been saved.")
                if serial == self.serial:
                    self.scan_ok = False
                    self.scan_note.set(message)
                    self._set_scan_color()
                if messagebox.askyesno("Scan check failed", message + "\n\nSave this image anyway?", parent=self):
                    self._save_unchecked(path, data, serial)
                self._update_action_buttons()
            elif kind == "clipboard_ready":
                self._finish_copy(serial, result)
            elif kind == "copy_error":
                self.copying = False
                messagebox.showerror("Could not copy image", result, parent=self)
                self._update_action_buttons()
            elif kind in ("scan_result", "scan_error"):
                self.checking = False
                format_name, result = result
                if serial == self.serial and format_name == self.format_var.get():
                    self.scan_ok = result.ok if kind == "scan_result" else False
                    self.scan_note.set(result.message if kind == "scan_result" else "Scan check failed: " + result)
                    self._set_scan_color()
                self._update_action_buttons()
            elif kind == "preview":
                if serial > self.preview_serial:
                    self.preview_serial = serial
                    self.preview = result[1]
                    self._request_paint(0)
                if serial == self.serial:
                    self.has_error = False
                    self.design = result[0]
                    self.design_serial = serial
                    opts = self.design.options
                    self.url_note.set(f"Encoded link: {opts.url}" if opts.content_type == "URL" else content_description(opts) + " - edit details in the Content tab.")
                    self.details.set(f"{opts.size} × {opts.size} px   ·   {len(self.design.matrix)} × {len(self.design.matrix)} modules   ·   High error correction")
                    self.advice.set("\n".join(self.design.warnings) or "Ready to export. Test the finished design with your phone before sharing.")
                    self._set_advice_color()
                    self.status.set("Preview ready • Generated on your computer")
                    self._update_action_buttons()
            elif kind == "error" and serial == self.serial:
                self._error(result)
        self.poll_pending = self.after(25, self._poll)

    def _request_paint(self, delay=30):
        if not self.closed and self.paint_pending is None:
            self.paint_pending = self.after(delay, self._paint_preview)

    def _paint_preview(self):
        self.paint_pending = None
        if self.closed:
            return
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        side = min(width - 28, height - 28)
        self.advice_label.configure(wraplength=max(240, width))
        self.scan_label.configure(wraplength=max(240, width))
        self.details_label.configure(wraplength=max(240, width))
        if side < 30:
            return
        if self.preview is None:
            self.canvas.itemconfigure(self.preview_item, state="hidden")
            self.canvas.coords(self.placeholder_item, width / 2, height / 2)
            self.canvas.itemconfigure(self.placeholder_item, state="normal")
            self._painted_preview = None
            return
        surface = self.preview_surface.get()
        self.canvas.coords(self.preview_item, width / 2, height / 2)
        if self._painted_preview is self.preview and self._paint_key == (side, surface):
            return
        if self._surface_key != (side, surface):
            base_color = "#222b3b" if surface == "Charcoal" else "#ffffff"
            self._surface = Image.new("RGBA", (side, side), base_color)
            if surface == "Checkerboard":
                draw = ImageDraw.Draw(self._surface)
                for y in range(0, side, 14):
                    for x in range(0, side, 14):
                        if (x // 14 + y // 14) % 2:
                            draw.rectangle((x, y, x + 13, y + 13), fill="#e4e9ef")
            self._surface_key = (side, surface)
        qr = self.preview.resize((side, side), Image.Resampling.LANCZOS)
        base = Image.alpha_composite(self._surface, qr)
        if self.native_glass:
            # Pure black is DWM's glass key in the extended client frame.
            # Keep even black QR modules opaque on screen; exports are untouched.
            base = ImageChops.lighter(base, Image.new("RGBA", base.size, (1, 1, 1, 0)))
        self.photo = ImageTk.PhotoImage(base, master=self)
        self.canvas.itemconfigure(self.placeholder_item, state="hidden")
        self.canvas.itemconfigure(self.preview_item, image=self.photo, state="normal")
        self._painted_preview = self.preview
        self._paint_key = (side, surface)

    def _export(self):
        if self.exporting:
            return
        if self.design is None or self.design_serial != self.serial or self.pending is not None or str(self.export_button.cget("state")) == "disabled":
            self.status.set("Wait for a valid preview before exporting.")
            return
        extension = {"PNG": ".png", "SVG": ".svg", "WebP": ".webp", "JPG": ".jpg"}[self.format_var.get()]
        chosen = [("PNG image", "*.png"), ("SVG vector", "*.svg"), ("WebP image", "*.webp"), ("JPEG image", "*.jpg *.jpeg")]
        chosen.sort(key=lambda item: 0 if extension in item[1].split() or "*" + extension in item[1].split() else 1)
        path = filedialog.asksaveasfilename(parent=self, title="Export your QR code", initialfile="my-qr" + extension,
                                          defaultextension=extension, filetypes=chosen)
        if not path:
            return
        self.exporting = True
        self.export_button.configure(state="disabled")
        self.status.set("Exporting…")
        design, serial = self.design, self.serial
        def save():
            try:
                save_design(design, path, verify=True)
                self.events.put(("saved", serial, path))
            except ScanCheckError as exc:
                self.events.put(("save_check_failed", serial, (path, exc.data, str(exc))))
            except Exception as exc:
                self.events.put(("save_error", serial, str(exc)))
        self.export_executor.submit(save)

    def _close(self):
        if self.closed:
            return
        try:
            self._store_settings()
        except OSError as exc:
            messagebox.showwarning("Could not remember settings", str(exc), parent=self)
        self.closed = True
        for callback in (self.pending, self.paint_pending, self.poll_pending, self.theme_pending, self.theme_update_pending, self.history_pending, self.copy_pending):
            if callback is not None:
                self.after_cancel(callback)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.export_executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main(*, safe_rendering=False):
    QRApp(safe_rendering=safe_rendering).mainloop()
