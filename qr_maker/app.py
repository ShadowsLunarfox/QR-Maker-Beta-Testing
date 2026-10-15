"""A local desktop QR designer built with Tkinter."""

from __future__ import annotations

import queue
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

from .render import GRADIENTS, PRESETS, SHAPES, Options, build_design, render_image, save_design

BG = "#f2f5f8"
INK = "#172033"
MUTED = "#657287"
ACCENT = "#087f8c"
LINE = "#dce4ed"


class QRApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QR Studio • Local QR Maker")
        self.geometry("1190x830")
        self.minsize(990, 730)
        self.configure(background=BG)
        self.option_add("*Font", "{Segoe UI} 10")
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qr-render")
        self.events = queue.Queue()
        self.serial = 0
        self.pending = None
        self.active_future = None
        self.design = None
        self.preview = None
        self.photo = None
        self.closed = False
        self.exporting = False
        self.traces_paused = True
        defaults = Options()
        self.vars = {}
        for field in fields(defaults):
            value = getattr(defaults, field.name)
            cls = tk.BooleanVar if isinstance(value, bool) else tk.IntVar if isinstance(value, int) else tk.StringVar
            self.vars[field.name] = cls(self, value=value)
        self.format_var = tk.StringVar(self, "PNG")
        self.preview_surface = tk.StringVar(self, "Checkerboard")
        self.status = tk.StringVar(self, "Preparing your preview…")
        self.url_note = tk.StringVar(self, "Add your link. Changes appear automatically.")
        self.details = tk.StringVar(self, "")
        self.advice = tk.StringVar(self, "")
        self.logo_label = tk.StringVar(self, "No logo selected")
        self._styles()
        self._build()
        for variable in self.vars.values():
            variable.trace_add("write", self._changed)
        self.preview_surface.trace_add("write", lambda *_: self._paint_preview())
        self.traces_paused = False
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Control-s>", lambda _: self._export())
        self.bind("<Return>", lambda _: self._schedule(0))
        self.after(80, self._poll)
        self._schedule(0)

    def _styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Card.TLabel", background="white", foreground=INK)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("CardMuted.TLabel", background="white", foreground=MUTED)
        style.configure("Heading.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Small.TLabel", font=("Segoe UI", 9), foreground=MUTED)
        style.configure("TButton", padding=(12, 8), background="white", foreground=INK, bordercolor=LINE)
        style.map("TButton", background=[("active", "#edf4f6")])
        style.configure("Accent.TButton", background=ACCENT, foreground="white", font=("Segoe UI", 10, "bold"), borderwidth=0, padding=(18, 11))
        style.map("Accent.TButton", background=[("disabled", "#a8bec5"), ("active", "#086a75")], foreground=[("disabled", "#f4f8fa")])
        style.configure("TEntry", padding=8, fieldbackground="white", bordercolor=LINE)
        style.configure("TCombobox", padding=6, fieldbackground="white", background="white", bordercolor=LINE)
        style.map("TCombobox", fieldbackground=[("readonly", "white")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 10), background="#e6ecf2", foreground=MUTED)
        style.map("TNotebook.Tab", background=[("selected", "white")], foreground=[("selected", INK)])
        style.configure("TCheckbutton", background=BG, foreground=INK, padding=(0, 5))
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("Horizontal.TScale", background=BG, troughcolor="#dce6ed")

    def _build(self):
        header = tk.Frame(self, bg="white", height=78)
        header.pack(fill="x")
        mark = tk.Canvas(header, width=44, height=44, bg=ACCENT, highlightthickness=0)
        mark.pack(side="left", padx=(26, 14), pady=17)
        for x, y in ((8, 8), (25, 8), (8, 25)):
            mark.create_rectangle(x, y, x + 10, y + 10, outline="white", width=2)
        mark.create_rectangle(25, 25, 29, 29, fill="white", outline="")
        mark.create_rectangle(32, 32, 36, 36, fill="white", outline="")
        title = tk.Frame(header, bg="white")
        title.pack(side="left")
        tk.Label(title, text="QR Studio", font=("Segoe UI", 20, "bold"), fg=INK, bg="white").pack(anchor="w")
        tk.Label(title, text="Your link. Your style.", font=("Segoe UI", 10), fg=MUTED, bg="white").pack(anchor="w")
        tk.Label(header, text="LOCAL CREATION  •  NO UPLOADS", bg="white", fg=ACCENT, font=("Segoe UI", 9, "bold")).pack(side="right", padx=28)

        main = ttk.Frame(self, padding=(26, 18, 26, 10))
        main.pack(fill="both", expand=True)
        link_card = ttk.Frame(main, style="Card.TFrame", padding=(18, 14))
        link_card.pack(fill="x", pady=(0, 18))
        ttk.Label(link_card, text="WEBSITE URL", style="CardMuted.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        line = ttk.Frame(link_card, style="Card.TFrame")
        line.pack(fill="x", pady=(8, 5))
        self.url_entry = ttk.Entry(line, textvariable=self.vars["url"], font=("Segoe UI", 12))
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ttk.Button(line, text="Generate", style="Accent.TButton", command=lambda: self._schedule(0)).pack(side="right")
        ttk.Label(link_card, textvariable=self.url_note, style="CardMuted.TLabel").pack(anchor="w")

        body = ttk.Frame(main)
        body.pack(fill="both", expand=True)
        sidebar = ttk.Frame(body, width=395)
        sidebar.pack(side="left", fill="y", padx=(0, 20))
        sidebar.pack_propagate(False)
        notebook = ttk.Notebook(sidebar)
        notebook.pack(fill="both", expand=True)
        for name, builder in (("Design", self._design_tab), ("Logo", self._logo_tab), ("Export", self._export_tab)):
            outer = ttk.Frame(notebook)
            notebook.add(outer, text=name)
            scroll = tk.Canvas(outer, background=BG, highlightthickness=0)
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
        ttk.Button(sidebar, text="Reset design", command=self._reset).pack(fill="x", pady=(14, 0))

        preview_card = ttk.Frame(body, style="Card.TFrame", padding=20)
        preview_card.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(preview_card, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Live preview", style="Card.TLabel", font=("Segoe UI", 13, "bold")).pack(side="left")
        ttk.Combobox(top, textvariable=self.preview_surface, values=("Checkerboard", "White", "Charcoal"), state="readonly", width=13).pack(side="right")
        self.canvas = tk.Canvas(preview_card, background="#f0f3f7", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=(16, 12))
        self.canvas.bind("<Configure>", lambda _: self._paint_preview())
        ttk.Label(preview_card, textvariable=self.details, style="CardMuted.TLabel").pack(anchor="w")
        self.advice_label = ttk.Label(preview_card, textvariable=self.advice, style="CardMuted.TLabel", wraplength=480)
        self.advice_label.pack(anchor="w", fill="x", pady=(10, 12))
        self.export_button = ttk.Button(preview_card, text="Export QR code", style="Accent.TButton", command=self._export, state="disabled")
        self.export_button.pack(fill="x")
        footer = ttk.Frame(self, padding=(26, 5, 26, 12))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status, style="Small.TLabel").pack(side="left")
        ttk.Label(footer, text="Ctrl+S to export", style="Small.TLabel").pack(side="right")
        self.url_entry.focus_set()

    def _label(self, parent, text):
        ttk.Label(parent, text=text, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 6))

    def _combo(self, parent, label, name, values):
        self._label(parent, label)
        ttk.Combobox(parent, textvariable=self.vars[name], values=values, state="readonly").pack(fill="x")

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
                swatch.configure(bg=LINE)
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
            self.vars[name].set(round(float(number)))
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
        self._slider(parent, "Logo size", "logo_size", 8, 24)
        self._slider(parent, "Logo opacity", "logo_opacity", 0, 100)
        ttk.Checkbutton(parent, text="Add a solid plate behind the logo", variable=self.vars["logo_plate"]).pack(anchor="w", pady=(18, 6))
        self._color_row(parent, "Plate color", "plate_color")
        self._combo(parent, "Plate shape", "plate_style", ("Rounded", "Square", "Circle"))
        ttk.Label(parent, text="Tip: an 18% logo and a white plate are a good starting point. All codes use high error correction. Test your final design with your phone.", style="Muted.TLabel", wraplength=320).pack(anchor="w", pady=(22, 0))

    def _export_tab(self, parent):
        ttk.Label(parent, text="Ready to share", style="Heading.TLabel").pack(anchor="w")
        self._label(parent, "File format")
        ttk.Combobox(parent, textvariable=self.format_var, values=("PNG", "SVG", "WebP", "JPG"), state="readonly").pack(fill="x")
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

    def _preset(self, name):
        a, b, bg, gradient, shape = PRESETS[name]
        self.traces_paused = True
        for key, value in dict(foreground=a, secondary=b, background=bg, gradient=gradient, shape=shape,
                               finder_color=a, finder_style="Rounded" if shape != "Square" else "Square",
                               foreground_opacity=100, background_opacity=100, transparent=False).items():
            self.vars[key].set(value)
        self.traces_paused = False
        self._schedule()

    def _reset(self):
        url = self.vars["url"].get()
        self.traces_paused = True
        defaults = Options(url=url)
        for field in fields(defaults):
            self.vars[field.name].set(getattr(defaults, field.name))
        self.logo_label.set("No logo selected")
        self.traces_paused = False
        self._schedule()

    def _choose_logo(self):
        path = filedialog.askopenfilename(parent=self, title="Choose a center logo", filetypes=(
            ("Logo images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("All files", "*.*")))
        if path:
            self.logo_label.set(Path(path).name)
            self.vars["logo_path"].set(path)

    def _remove_logo(self):
        self.logo_label.set("No logo selected")
        self.vars["logo_path"].set("")

    def _changed(self, *_):
        if not self.traces_paused:
            self._schedule()

    def _schedule(self, delay=280):
        self.serial += 1
        self.export_button.configure(state="disabled")
        self.status.set("Updating preview…")
        if self.pending is not None:
            self.after_cancel(self.pending)
        if self.active_future is not None:
            self.active_future.cancel()
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
                design = build_design(options)
                preview = render_image(design, min(options.size, 760))
                self.events.put(("preview", serial, (design, preview)))
            except Exception as exc:
                self.events.put(("error", serial, str(exc)))
        self.active_future = self.executor.submit(render)

    def _error(self, message):
        self.design = None
        self.preview = None
        self.details.set("")
        self.url_note.set("Check your URL or design settings below.")
        self.advice.set(message)
        self.advice_label.configure(foreground="#a13b3b")
        self.status.set("Check your settings")
        self.export_button.configure(state="disabled")
        self._paint_preview()

    def _poll(self):
        if self.closed:
            return
        while True:
            try:
                kind, serial, result = self.events.get_nowait()
            except queue.Empty:
                break
            if kind in ("saved", "save_error"):
                self.exporting = False
                if kind == "saved":
                    self.status.set(f"Saved: {result}")
                else:
                    messagebox.showerror("Could not export", result, parent=self)
                    self.status.set("Export failed. Your design is still available.")
                if self.design is not None and self.pending is None and serial == self.serial:
                    self.export_button.configure(state="normal")
            elif serial == self.serial:
                if kind == "error":
                    self._error(result)
                elif kind == "preview":
                    self.design, self.preview = result
                    opts = self.design.options
                    self.url_note.set(f"Encoded link: {opts.url}")
                    self.details.set(f"{opts.size} × {opts.size} px   ·   {len(self.design.matrix)} × {len(self.design.matrix)} modules   ·   High error correction")
                    self.advice.set("\n".join(self.design.warnings) or "Ready to export. Test the finished design with your phone before sharing.")
                    self.advice_label.configure(foreground="#97620b" if self.design.warnings else MUTED)
                    self.status.set("Preview ready • Generated on your computer")
                    if not self.exporting:
                        self.export_button.configure(state="normal")
                    self._paint_preview()
        self.after(80, self._poll)

    def _paint_preview(self):
        if self.closed:
            return
        self.canvas.delete("all")
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        side = min(width - 28, height - 28)
        self.advice_label.configure(wraplength=max(240, width))
        if side < 30:
            return
        if self.preview is None:
            self.canvas.create_text(width / 2, height / 2, text="Your QR code will appear here", fill=MUTED, font=("Segoe UI", 12))
            return
        surface = self.preview_surface.get()
        base_color = "#ffffff" if surface != "Charcoal" else "#222b3b"
        base = Image.new("RGBA", (side, side), base_color)
        if surface == "Checkerboard":
            draw = ImageDraw.Draw(base)
            for y in range(0, side, 14):
                for x in range(0, side, 14):
                    if (x // 14 + y // 14) % 2:
                        draw.rectangle((x, y, x + 13, y + 13), fill="#e4e9ef")
        qr = self.preview.resize((side, side), Image.Resampling.LANCZOS)
        base = Image.alpha_composite(base, qr)
        self.photo = ImageTk.PhotoImage(base, master=self)
        self.canvas.create_image(width / 2, height / 2, image=self.photo)

    def _export(self):
        if self.exporting:
            return
        if self.design is None or self.pending is not None or str(self.export_button.cget("state")) == "disabled":
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
                save_design(design, path)
                self.events.put(("saved", serial, path))
            except Exception as exc:
                self.events.put(("save_error", serial, str(exc)))
        self.executor.submit(save)

    def _close(self):
        self.closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main():
    QRApp().mainloop()
