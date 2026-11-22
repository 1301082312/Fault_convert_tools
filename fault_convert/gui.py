"""Tkinter front end: three tabs (概率叠加 / 转 SEG-Y / TS 转标签), progress bar and a coloured log."""
import os
import queue
import re
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

import numpy as np

from .dnd_win import enable_drop
from .grid import Grid, grid_from_metadata
from .jobs import job_labels, job_overlay, job_segy
from .segy import non_ascii_paths

# palette
BG, CARD, LINE = "#eef2f7", "#ffffff", "#d7dee8"
TEXT, MUTED = "#1f2a37", "#6b7785"
ACCENT, ACCENT_DARK, ACCENT_LIGHT = "#2563eb", "#1d4ed8", "#dbe7ff"
HEADER, HEADER_SUB = "#16233a", "#9fb3cf"
LOG_BG, LOG_FG = "#141b26", "#d6deea"
OK, WARN, ERR = "#34c77b", "#f5a524", "#ff5d5d"

PROGRESS = re.compile(r"(?:inline|\[)\s*(\d+)\s*/\s*(\d+)")


def _dpi_aware():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001 - cosmetic only
            pass


class App(tk.Tk):
    def __init__(self):
        _dpi_aware()
        super().__init__()
        self.title("Fault_convert_tools · 断层数据转换")
        sh = self.winfo_screenheight()
        self.geometry(f"1000x{min(960, sh - 80)}+40+20")
        self.minsize(880, 720)
        self.configure(bg=BG)
        self.msgs = queue.Queue()
        self.busy = False
        self.v, self.info_labels, self.last_out, self.drop_targets = {}, {}, None, []
        self._style()
        self._header()
        body = ttk.Frame(self, style="Bg.TFrame", padding=(16, 12, 16, 0))
        body.pack(fill="both", expand=True)
        nb = ttk.Notebook(body, style="Main.TNotebook")
        nb.pack(fill="x")
        self._overlay_tab(nb)
        self._segy_tab(nb)
        self._labels_tab(nb)
        self._log_panel(body)
        self._status_bar()
        self.after(100, self._drain)
        self.after(200, self._enable_drops)

    # ---------------- drag and drop ----------------
    def _enable_drops(self):
        ok = 0
        for entry, key, kind, types in self.drop_targets:
            ok += enable_drop(entry, lambda paths, k=key, kd=kind, t=types: self._dropped(k, kd, t, paths))
        if ok:
            self.log(f"可以把文件或文件夹直接拖到输入框里")

    def _dropped(self, key, kind, types, paths):
        if not paths:
            return
        p = [Path(x) for x in paths]
        if kind == "dir":  # a dropped file means its folder (e.g. a few .ts files -> their folder)
            value = str(p[0] if p[0].is_dir() else p[0].parent)
        elif kind == "opens":
            files = []
            for x in p:
                files += sorted(str(y) for y in x.glob("*.npy")) if x.is_dir() else [str(x)]
            value = ";".join(files)
        elif kind == "save" and p[0].is_dir():  # dropped a folder for an output file
            value = str(p[0] / "overlay_p05.npy")
        else:
            value = str(p[0])
            ext = types[0][1].lstrip("*")
            if kind == "open" and not value.lower().endswith(ext):
                self.log(f"警告：拖入的不是 {ext} 文件：{value}")
        self.v[key].set(value)
        self.log(f"已填入：{value if len(value) < 160 else value[:160] + '…'}")

    # ---------------- look ----------------
    def _style(self):
        family = "Microsoft YaHei UI" if "Microsoft YaHei UI" in tkfont.families() else "TkDefaultFont"
        self.f_base = (family, 10)
        self.f_bold = (family, 10, "bold")
        self.f_title = (family, 17, "bold")
        self.f_small = (family, 9)
        self.f_mono = ("Consolas", 10)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tkfont.nametofont(name).configure(family=family, size=10)
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT, font=self.f_base, bordercolor=LINE)
        s.configure("Bg.TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("Card.TLabelframe", background=CARD, bordercolor=LINE, relief="solid", borderwidth=1)
        s.configure("Card.TLabelframe.Label", background=CARD, foreground=ACCENT, font=self.f_bold)
        s.configure("Card.TLabel", background=CARD, foreground=TEXT)
        s.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=self.f_small)
        s.configure("Info.TLabel", background=CARD, foreground=ACCENT, font=self.f_small)
        s.configure("Bad.TLabel", background=CARD, foreground=ERR, font=self.f_small)
        s.configure("Card.TCheckbutton", background=CARD, indicatorbackground="white", indicatorforeground=ACCENT)
        s.configure("Card.TRadiobutton", background=CARD, indicatorbackground="white", indicatorforeground=ACCENT)
        s.map("Card.TCheckbutton", background=[("active", CARD)])
        s.map("Card.TRadiobutton", background=[("active", CARD)])
        s.configure("TEntry", fieldbackground="#f8fafc", bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=5)
        s.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
        s.configure("TButton", padding=(10, 5), background="#f3f6fa", bordercolor=LINE)
        s.map("TButton", background=[("active", ACCENT_LIGHT)])
        s.configure("Accent.TButton", font=self.f_bold, foreground="white", background=ACCENT,
                    bordercolor=ACCENT, padding=(22, 8))
        s.map("Accent.TButton", background=[("disabled", "#9db6ea"), ("active", ACCENT_DARK)])
        s.configure("Main.TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        s.configure("Main.TNotebook.Tab", padding=(20, 9), font=self.f_bold, background="#dde4ee",
                    foreground=MUTED, borderwidth=0)
        s.map("Main.TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", ACCENT)])
        s.configure("Accent.Horizontal.TProgressbar", background=ACCENT, troughcolor="#dde4ee",
                    bordercolor="#dde4ee", lightcolor=ACCENT, darkcolor=ACCENT, thickness=8)
        s.configure("Status.TLabel", background=BG, foreground=MUTED, font=self.f_small)

    def _header(self):
        h = tk.Frame(self, bg=HEADER, height=74)
        h.pack(fill="x")
        h.pack_propagate(False)
        tk.Label(h, text="断层数据转换工具", bg=HEADER, fg="white", font=self.f_title).pack(anchor="w", padx=20, pady=(12, 0))
        tk.Label(h, text="概率叠加  ·  npy → SEG-Y（Petrel）  ·  Petrel TS → 二值 / 实例标签",
                 bg=HEADER, fg=HEADER_SUB, font=self.f_small).pack(anchor="w", padx=21)

    def _tab(self, nb, title):
        outer = ttk.Frame(nb, style="Card.TFrame", padding=(14, 10))
        nb.add(outer, text=title)
        return outer

    def _card(self, parent, title):
        c = ttk.LabelFrame(parent, text=f"  {title}  ", style="Card.TLabelframe", padding=(12, 4, 12, 8))
        c.pack(fill="x", pady=(0, 8))
        c.columnconfigure(1, weight=1)
        return c

    # ---------------- widgets ----------------
    def _var(self, key, value=""):
        self.v[key] = tk.StringVar(value=value)
        return self.v[key]

    def _path_row(self, f, r, label, key, kind="open", types=(("npy", "*.npy"),), show_shape=True):
        ttk.Label(f, text=label, style="Card.TLabel", width=16).grid(row=2 * r, column=0, sticky="w", pady=(4, 0))
        var = self._var(key)
        entry = ttk.Entry(f, textvariable=var)
        entry.grid(row=2 * r, column=1, sticky="we", pady=(4, 0))
        ttk.Button(f, text="浏览…", command=lambda: self._browse(key, kind, types)).grid(row=2 * r, column=2, padx=(8, 0), pady=(4, 0))
        info = ttk.Label(f, text="可拖入文件 / 文件夹", style="Muted.TLabel")
        info.grid(row=2 * r + 1, column=1, sticky="w")
        self.info_labels[key] = info
        var.trace_add("write", lambda *_: self._describe(key, kind, show_shape))
        self.drop_targets.append((entry, key, kind, types))

    def _describe(self, key, kind, show_shape):
        lab, text = self.info_labels[key], self.v[key].get().strip()
        if not text:
            lab.configure(text="可拖入文件 / 文件夹", style="Muted.TLabel")
            return
        paths = [p for p in text.split(";") if p]
        try:
            if kind in ("open", "opens") and show_shape:
                parts = []
                for p in paths[:3]:
                    a = np.load(p, mmap_mode="r")
                    parts.append(f"{Path(p).name}: {' × '.join(map(str, a.shape))}  {a.dtype}")
                more = f"  （共 {len(paths)} 个文件）" if len(paths) > 3 else ""
                lab.configure(text="   ".join(parts) + more, style="Info.TLabel")
            elif kind == "dir" and key.endswith("ts"):
                n = len(list(Path(text).glob("*.ts")))
                lab.configure(text=f"{n} 个 .ts 文件" if n else "这个文件夹里没有 .ts 文件",
                              style="Info.TLabel" if n else "Bad.TLabel")
            else:
                lab.configure(text="", style="Muted.TLabel")
        except Exception:  # noqa: BLE001 - feedback only
            lab.configure(text="读不到这个文件", style="Bad.TLabel")

    def _browse(self, key, kind, types):
        if kind == "open":
            p = filedialog.askopenfilename(filetypes=list(types) + [("all", "*.*")])
        elif kind == "opens":
            p = ";".join(filedialog.askopenfilenames(filetypes=list(types) + [("all", "*.*")]))
        elif kind == "save":
            p = filedialog.asksaveasfilename(filetypes=list(types), defaultextension=types[0][1][1:])
        else:
            p = filedialog.askdirectory()
        if p:
            self.v[key].set(p)

    def _small_entry(self, parent, label, key, value, width=8, hint=None):
        box = ttk.Frame(parent, style="Card.TFrame")
        box.pack(side="left", padx=(0, 18))
        ttk.Label(box, text=label, style="Card.TLabel").pack(anchor="w")
        ttk.Entry(box, textvariable=self._var(key, value), width=width).pack(anchor="w")
        if hint:
            ttk.Label(box, text=hint, style="Muted.TLabel").pack(anchor="w")
        return box

    def _grid_card(self, parent, prefix, near_key):
        c = self._card(parent, "空间位置（导出 SEG-Y 和转标签必须用同一组）")
        row = ttk.Frame(c, style="Card.TFrame")
        row.grid(row=0, column=0, columnspan=3, sticky="w")
        self._small_entry(row, "起点 inline, xline, sample", prefix + "origin", "0,0,0", 20, "第一个体素在原始数据体中的下标")
        self._small_entry(row, "采样间隔 (ms)", prefix + "dt", "2", 8)
        self._small_entry(row, "道距 (m)", prefix + "bin", "25", 8)
        b = ttk.Frame(row, style="Card.TFrame")
        b.pack(side="left", anchor="n", pady=(18, 0))
        ttk.Button(b, text="从 metadata 读取", command=lambda: self._read_meta(prefix, near_key)).pack()

    def _actions(self, parent, command, open_key=None):
        a = ttk.Frame(parent, style="Card.TFrame")
        a.pack(fill="x", pady=(2, 0))
        btn = ttk.Button(a, text="开始转换", style="Accent.TButton", command=command)
        btn.pack(side="right")
        ttk.Button(a, text="打开输出文件夹", command=lambda: self._open_out(open_key)).pack(side="right", padx=10)
        self.run_buttons.append(btn)

    # ---------------- tabs ----------------
    def _overlay_tab(self, nb):
        self.run_buttons = getattr(self, "run_buttons", [])
        t = self._tab(nb, "  ① 概率叠加  ")
        c = self._card(t, "输入与输出")
        self._path_row(c, 0, "地震 npy", "ov_seis")
        self._path_row(c, 1, "概率 npy", "ov_prob")
        self._path_row(c, 2, "输出 overlay npy", "ov_out", "save", show_shape=False)
        p = self._card(t, "叠加参数")
        row = ttk.Frame(p, style="Card.TFrame")
        row.grid(row=0, column=0, sticky="w")
        self._small_entry(row, "概率阈值", "ov_thr", "0.5", 8, "≥ 阈值写成 +1")
        self._small_entry(row, "裁剪百分位", "ov_clip", "99", 8, "|振幅| 的百分位")
        self._small_entry(row, "缩放", "ov_scale", "0.6", 8, "地震缩放到 ±缩放")
        self.v["ov_segy"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(p, text="同时输出 SEG-Y（与 overlay npy 同名 .sgy）", style="Card.TCheckbutton",
                        variable=self.v["ov_segy"]).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._grid_card(t, "ov_", "ov_seis")
        self._actions(t, self._run_overlay, "ov_out")

    def _segy_tab(self, nb):
        t = self._tab(nb, "  ② npy 转 SEG-Y  ")
        c = self._card(t, "输入与输出")
        self._path_row(c, 0, "npy 文件（可多选）", "sg_npy", "opens")
        self._path_row(c, 1, "输出文件夹", "sg_out", "dir")
        self._grid_card(t, "sg_", "sg_npy")
        h = self._card(t, "Petrel 导入设置")
        ttk.Label(h, text="SEG-Y · 3D ·  X / Y 坐标字节 181 / 185 ·  Line detection：Trace header fields ·  "
                          "Inline 189 · Crossline 193", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(h, text="SEG-Y 请放在纯英文路径下；路径含中文时开始前会提示。", style="Muted.TLabel").grid(row=1, column=0, sticky="w")
        self._actions(t, self._run_segy, "sg_out")

    def _labels_tab(self, nb):
        t = self._tab(nb, "  ③ TS 转标签  ")
        c = self._card(t, "输入与输出")
        self._path_row(c, 0, "TS 文件夹", "lb_ts", "dir")
        self._path_row(c, 1, "地震 npy（定尺寸）", "lb_seis")
        self._path_row(c, 2, "输出文件夹", "lb_out", "dir")
        p = self._card(t, "标签选项")
        row = ttk.Frame(p, style="Card.TFrame")
        row.grid(row=0, column=0, sticky="w")
        box = ttk.Frame(row, style="Card.TFrame")
        box.pack(side="left", padx=(0, 24), anchor="n")
        ttk.Label(box, text="输出", style="Card.TLabel").pack(anchor="w")
        self.v["lb_mode"] = tk.StringVar(value="both")
        modes = ttk.Frame(box, style="Card.TFrame")
        modes.pack(anchor="w")
        for text, val in (("二值 + 实例", "both"), ("仅二值", "binary"), ("仅实例", "instance")):
            ttk.Radiobutton(modes, text=text, value=val, variable=self.v["lb_mode"], style="Card.TRadiobutton").pack(side="left", padx=(0, 8))
        self._small_entry(row, "起始编号", "lb_start", "1", 8, "按文件名自然顺序编号")
        self._small_entry(row, "只保留 inline（可空）", "lb_il", "", 12, "如 220,232；空 = 整个地震体")
        self.v["lb_copy"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(p, text="同时把地震复制成 seismic.npy", style="Card.TCheckbutton",
                        variable=self.v["lb_copy"]).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._grid_card(t, "lb_", "lb_seis")
        ttk.Label(t, text="TS 需在本工具导出的 SEG-Y 上解释（同一组起点 / 采样间隔 / 道距）",
                  style="Muted.TLabel").pack(anchor="w")
        self._actions(t, self._run_labels, "lb_out")

    def _log_panel(self, parent):
        bar = ttk.Frame(parent, style="Bg.TFrame")
        bar.pack(fill="x", pady=(12, 4))
        ttk.Label(bar, text="运行日志", font=self.f_bold).pack(side="left")
        ttk.Button(bar, text="清空", command=lambda: self.log_box.delete("1.0", "end")).pack(side="right")
        ttk.Button(bar, text="复制", command=self._copy_log).pack(side="right", padx=6)
        frame = tk.Frame(parent, bg=LOG_BG, highlightthickness=1, highlightbackground=LINE)
        frame.pack(fill="both", expand=True)
        self.log_box = tk.Text(frame, bg=LOG_BG, fg=LOG_FG, insertbackground=LOG_FG, relief="flat",
                               font=self.f_mono, wrap="word", padx=10, pady=8, height=7)
        sb = ttk.Scrollbar(frame, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.tag_configure("ok", foreground=OK)
        self.log_box.tag_configure("warn", foreground=WARN)
        self.log_box.tag_configure("err", foreground=ERR)
        self.log_box.tag_configure("dim", foreground="#7d8aa0")

    def _status_bar(self):
        s = ttk.Frame(self, style="Bg.TFrame", padding=(16, 8))
        s.pack(fill="x")
        self.status = ttk.Label(s, text="就绪", style="Status.TLabel", width=28)
        self.status.pack(side="left")
        self.bar = ttk.Progressbar(s, style="Accent.Horizontal.TProgressbar", mode="determinate", maximum=100)
        self.bar.pack(side="left", fill="x", expand=True, padx=(8, 0))

    # ---------------- helpers ----------------
    def _read_meta(self, prefix, near_key):
        near = self.v[near_key].get().split(";")[0]
        g = grid_from_metadata(near) if near else None
        if g is None:
            messagebox.showinfo("起点", "输入文件旁边没有带 origin 的 metadata.json / info.json，请手动填写。")
            return
        self.v[prefix + "origin"].set(",".join(map(str, g.origin)))
        self.v[prefix + "dt"].set(f"{g.dt_ms:g}")
        self.log(f"读取起点 {g.origin}，采样间隔 {g.dt_ms:g} ms")

    def _grid(self, prefix):
        return Grid(Grid.parse_origin(self.v[prefix + "origin"].get()), float(self.v[prefix + "dt"].get()),
                    float(self.v[prefix + "bin"].get()))

    def _open_out(self, key):
        p = Path(self.v[key].get().strip()) if key and self.v[key].get().strip() else None
        if p is not None and p.suffix:
            p = p.parent
        if p is None or not p.exists():
            messagebox.showinfo("输出文件夹", "输出文件夹还不存在")
            return
        os.startfile(str(p)) if os.name == "nt" else None

    def _copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.log_box.get("1.0", "end"))

    # ---------------- running ----------------
    def log(self, text):
        self.msgs.put(str(text))

    def _drain(self):
        while not self.msgs.empty():
            text = self.msgs.get()
            m = PROGRESS.search(text)
            if m and int(m.group(2)):
                self.bar.configure(value=100 * int(m.group(1)) / int(m.group(2)))
                if "inline" in text and not text.startswith("["):
                    self.status.configure(text=text)
                    continue  # per-inline progress goes to the status bar, not the log
            tag = ("err" if text.startswith(("出错", "Traceback")) else "warn" if text.startswith("警告")
                   else "ok" if text.startswith(("完成", "wrote", "check")) else "dim" if text.startswith("  ") else "")
            self.log_box.insert("end", text + "\n", tag)
            self.log_box.see("end")
        self.after(100, self._drain)

    def _set_busy(self, busy, status):
        self.busy = busy
        for b in self.run_buttons:
            b.state(["disabled"] if busy else ["!disabled"])
        self.status.configure(text=status)
        if busy:
            self.bar.configure(value=0)

    def _start(self, fn):
        if self.busy:
            messagebox.showinfo("请稍候", "上一个任务还在运行")
            return
        self._set_busy(True, "运行中…")

        def work():
            ok = False
            try:
                fn()
                ok = True
                self.log("完成")
            except Exception as e:  # noqa: BLE001 - shown to the user
                self.log("出错：" + str(e))
                self.log(traceback.format_exc())
            finally:
                self.after(0, lambda: (self._set_busy(False, "完成" if ok else "出错，详见日志"),
                                       self.bar.configure(value=100 if ok else 0)))
        threading.Thread(target=work, daemon=True).start()

    def _need(self, *keys):
        if any(not self.v[k].get().strip() for k in keys):
            messagebox.showerror("缺少输入", "请先填写所有路径")
            return False
        return True

    def _segy_paths_ok(self, paths):
        """Ask before writing SEG-Y to a path with Chinese / non-ASCII characters."""
        bad = non_ascii_paths(paths)
        if not bad:
            return True
        shown = "\n".join(bad[:5]) + ("\n…" if len(bad) > 5 else "")
        return messagebox.askyesno(
            "SEG-Y 路径含中文",
            "以下 SEG-Y 输出路径含中文或其他非英文字符，导入 Petrel 时会出错：\n\n" + shown +
            "\n\n建议改到纯英文路径、用英文文件名。\n\n仍然按这个路径输出吗？", icon="warning", default="no")

    def _run_overlay(self):
        if not self._need("ov_seis", "ov_prob", "ov_out"):
            return
        out = self.v["ov_out"].get()
        segy = str(Path(out).with_suffix(".sgy")) if self.v["ov_segy"].get() else None
        if segy and not self._segy_paths_ok([segy]):
            return
        grid = self._grid("ov_") if segy else None
        self._start(lambda: job_overlay(self.v["ov_seis"].get(), self.v["ov_prob"].get(), out,
                                        float(self.v["ov_thr"].get()), float(self.v["ov_clip"].get()),
                                        float(self.v["ov_scale"].get()), segy, grid, log=self.log))

    def _run_segy(self):
        if not self._need("sg_npy", "sg_out"):
            return
        files = [p for p in self.v["sg_npy"].get().split(";") if p]
        out_dir = Path(self.v["sg_out"].get())
        if not self._segy_paths_ok([out_dir / (Path(p).stem + ".sgy") for p in files]):
            return
        grid = self._grid("sg_")
        self._start(lambda: job_segy(files, self.v["sg_out"].get(), grid, log=self.log))

    def _run_labels(self):
        if not self._need("lb_ts", "lb_seis", "lb_out"):
            return
        il = self.v["lb_il"].get().strip()
        rng = Grid.parse_origin(il)[:2] if il else None
        grid = self._grid("lb_")
        self._start(lambda: job_labels(self.v["lb_ts"].get(), self.v["lb_seis"].get(), self.v["lb_out"].get(),
                                       grid, self.v["lb_mode"].get(), int(self.v["lb_start"].get()), rng,
                                       self.v["lb_copy"].get(), log=self.log))


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
