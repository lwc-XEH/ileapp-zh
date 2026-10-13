# -*- coding: utf-8 -*-
"""iLEAPP 中文工作台 —— 统一入口。

把「跑 iLEAPP」和「汉化报告」合成一件事：
    选检材 -> 自动跑 iLEAPP -> 自动出中文报告 -> 自动打开

编排逻辑放在 process() 里，与界面解耦，方便脱离界面测试。
"""

import json
import os
import pathlib
import queue
import re
import subprocess
import sys
import threading
import time
import traceback

# 窗口标题：沿用原版 iLEAPP 的 "iLEAPP version X" 格式，只把 version 换成汉化版。
APP_TITLE = "iLEAPP 汉化版 2026.4.4"

# 原版 iLEAPP 界面的三色（ileappGUI.py 里硬编码）：深棕 / 中棕 / 琥珀黄。
# 复刻外观时统一从这里取值，别再往控件上散写色号。
THEME_BG = "#2c2825"
THEME_INPUT = "#705e52"
THEME_FG = "#fdcb52"
THEME_MUTED = "#b8a888"   # 深色底上的次级说明文字


def _fatal_no_tkinter(exc):
    """缺 tkinter 时给出看得见的提示，而不是静默退出。

    pythonw 没有控制台：直接抛 ImportError 退出的话，用户双击之后只会看到
    "什么都没发生"。这里用 Windows 原生消息框（ctypes，不依赖 tkinter）
    把原因和解决方向说清楚。

    设了 ILEAPP_ZH_NO_DIALOG=1 就只打印不弹窗——自动化测试和 CI 用。
    """
    msg = (
        "这个工具需要带 tkinter 的 Python 3.10+，但当前解释器没有 tkinter。\n\n"
        f"当前解释器：\n{sys.executable}\n\n"
        f"错误：{exc}\n\n"
        "python.org 的官方安装包自带 tkinter；部分精简版、嵌入式版本，\n"
        "以及某些虚拟环境不带。请换一个 Python 运行 workbench.py，\n"
        "或在重新安装时勾选 tcl/tk 组件。"
    )
    if not os.environ.get("ILEAPP_ZH_NO_DIALOG"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, APP_TITLE, 0x10)
        except Exception:  # noqa: BLE001 - 非 Windows 或 ctypes 不可用
            pass
    try:
        print(msg, file=sys.stderr)
    except Exception:  # noqa: BLE001 - pythonw 下 sys.stderr 是 None
        pass
    raise SystemExit(1)


try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError as _exc:  # pragma: no cover - 只在环境缺 tkinter 时走到
    _fatal_no_tkinter(_exc)

HERE = pathlib.Path(__file__).resolve().parent
CONFIG_PATH = HERE / "工作台配置.json"

# 输入类型：显示名 -> iLEAPP 的 -t 取值
INPUT_TYPES = [
    ("文件夹（已提取的文件系统）", "fs"),
    ("zip 压缩包", "zip"),
    ("tar 压缩包（含 .tar.xz）", "tar"),
    ("gz 压缩包", "gz"),
    ("iTunes / Finder 备份", "itunes"),
    ("磁盘镜像（E01 / img / dd / dmg 等）", "raw"),
    ("单个文件", "file"),
]

MODE_LABELS = [("智能组合（覆盖率最高）", "smart"), ("仅精确匹配（最保守）", "exact")]

PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)\]")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ----------------------------------------------------------------- 配置读写
def load_config():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    except Exception:
        pass


# ------------------------------------------------------- 查找 iLEAPP 主程序
def find_ileapp():
    """按 配置 -> 同级目录 iLEAPP-*/ 的顺序找 ileapp.exe。"""
    cands = []
    saved = load_config().get("ileapp")
    if saved:
        cands.append(pathlib.Path(saved))
    for base in (HERE, HERE.parent):
        cands.append(base / "iLEAPP-2026.4.4" / "ileapp.exe")
        try:
            cands.extend(sorted(base.glob("iLEAPP*/ileapp.exe")))
            cands.extend(sorted(base.glob("iLEAPP*/*/ileapp.exe")))
        except OSError:
            pass
    seen = set()
    for c in cands:
        try:
            key = str(c).lower()
            if key in seen:
                continue
            seen.add(key)
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def find_ileapp_icon():
    """找原版 iLEAPP 自带的图标，用来做窗口图标。

    便携版把它放在 ileapp.exe 同级或上一级的 assets/ 或 _internal/assets/。
    找不到就返回 None——图标只是外观，绝不能让工作台因此起不来。
    """
    cands = []
    saved = load_config().get("ileapp")
    if saved:
        exe_dir = pathlib.Path(saved).parent
        cands += [exe_dir / "assets" / "icon.png",
                  exe_dir / "_internal" / "assets" / "icon.png"]
    for base in (HERE, HERE.parent):
        for sub in ("assets", "_internal/assets"):
            cands.append(base / sub / "icon.png")
        try:
            for d in sorted(base.glob("iLEAPP*/")):
                cands += [d / "assets" / "icon.png",
                          d / "_internal" / "assets" / "icon.png"]
        except OSError:
            pass
    seen = set()
    for c in cands:
        try:
            key = str(c).lower()
            if key in seen:
                continue
            seen.add(key)
            if c.is_file():
                return c
        except OSError:
            continue
    return None


# ------------------------------------------------------------ 编排（可测试）
def run_ileapp(exe, itype, inp, outdir, password=None, log=None, on_progress=None):
    """调用 ileapp.exe 解析检材，返回退出码。"""
    emit = log or (lambda m: None)
    if not exe:
        raise ValueError("没有指定 ileapp.exe 路径。请在上方选择 iLEAPP 主程序。")
    exe = pathlib.Path(exe).resolve()
    if not exe.is_file():
        raise FileNotFoundError(f"ileapp.exe 不存在: {exe}")
    # 一律转绝对路径：下面把 cwd 切到了 exe 所在目录，相对路径会解析错地方。
    # 图形界面走文件对话框本来就是绝对路径，但命令行调用时这条很关键。
    inp = pathlib.Path(inp).resolve()
    outdir = pathlib.Path(outdir).resolve()
    if not inp.exists():
        raise FileNotFoundError(f"检材路径不存在: {inp}")
    outdir.mkdir(parents=True, exist_ok=True)

    cmd = [str(exe), "-t", itype, "-i", str(inp), "-o", str(outdir)]
    if itype == "itunes" and password:
        cmd += ["--itunes_password", password]

    emit("$ " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env, cwd=str(exe.parent),
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=NO_WINDOW,
    )
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        m = PROGRESS_RE.match(line)
        if m and on_progress:
            on_progress(int(m.group(1)), int(m.group(2)), line)
        else:
            emit(line)
    proc.wait()
    return proc.returncode


def newest_report(outdir, since=None):
    """在输出目录里找最新的 iLEAPP_Output_* 报告目录。"""
    outdir = pathlib.Path(outdir)
    if not outdir.is_dir():
        return None
    dirs = [p for p in outdir.glob("iLEAPP_Output_*") if p.is_dir()]
    if not dirs:
        return None
    if since is not None:
        fresh = [p for p in dirs if p.stat().st_mtime >= since]
        if fresh:
            dirs = fresh
    return max(dirs, key=lambda p: p.stat().st_mtime)


def process(exe, itype, inp, outdir, do_localize=True, mode="smart",
            password=None, log=None, on_progress=None, should_stop=None):
    """完整流程：跑 iLEAPP -> 找报告 -> 汉化。

    返回 dict：report_dir / zh_dir / report_html / rc
    """
    emit = log or (lambda m: None)
    outdir = pathlib.Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    started = time.time() - 2
    emit("=" * 62)
    emit("开始解析检材…")
    rc = run_ileapp(exe, itype, inp, outdir, password=password,
                    log=log, on_progress=on_progress)
    if should_stop and should_stop():
        emit("已停止。")
        return {"rc": rc, "report_dir": None, "zh_dir": None, "report_html": None}
    if rc != 0:
        raise RuntimeError(f"iLEAPP 返回非零退出码 {rc}，解析可能失败。")

    report_dir = newest_report(outdir, since=started)
    if report_dir is None:
        raise RuntimeError(f"在 {outdir} 下没找到 iLEAPP_Output_* 报告目录。")
    emit(f"报告目录: {report_dir}")

    report_html = report_dir / "index.html"
    zh_dir = None
    if do_localize:
        emit("")
        emit("=" * 62)
        emit("开始汉化报告…")
        sys.path.insert(0, str(HERE))
        import ileapp_zh
        res = ileapp_zh.localize_report(report_dir, mode=mode, log=emit)
        zh_dir = pathlib.Path(res["out_dir"])
        t = res["totals"]
        emit(f"处理 HTML 文件: {res['files']}")
        emit(f"  精确匹配 {t['exact'] + t['ui_label']} · 句式 {t['pattern']} · "
             f"标题前后缀 {t['affix']} · 术语组合 {t['composed']}")
        emit(f"  保留原文 {t['unchanged']} · 跳过原始列名 {t['skipped_raw_column']}")
        emit(f"中文报告: {zh_dir}")
        report_html = zh_dir / "index.html"

    # 对外统一返回 str，调用方可直接展示或写进 JSON
    return {"rc": rc, "report_dir": str(report_dir),
            "zh_dir": str(zh_dir) if zh_dir else None,
            "report_html": str(report_html)}


# --------------------------------------------------------------------- 界面
class App:
    def __init__(self, root):
        self.root = root
        self.worker = None
        self.proc = None
        self.logq = queue.Queue()
        self.stop_flag = False
        self.last_html = None
        self.last_outdir = None

        cfg = load_config()
        root.title(APP_TITLE)
        root.geometry("940x720")
        root.minsize(890, 750)

        self._set_window_icon()
        self._setup_style()
        self._build(cfg)
        self.root.after(120, self._drain_log)

    # ---------------------------------------------------------- 外观
    def _set_window_icon(self):
        """用原版 iLEAPP 的 icon.png 做窗口图标；失败静默跳过。"""
        icon = find_ileapp_icon()
        if not icon:
            return
        try:
            self._icon_img = tk.PhotoImage(file=str(icon))
            self.root.iconphoto(True, self._icon_img)
        except Exception:  # noqa: BLE001 - 图标不是功能，出错不影响使用
            pass

    def _setup_style(self):
        # 配色按原版 iLEAPP：深棕底 + 琥珀黄字。
        self.root.configure(bg=THEME_BG)
        for name in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei"):
            try:
                self.root.option_add("*Font", (name, 9))
                break
            except tk.TclError:
                continue
        st = ttk.Style()
        try:
            st.theme_use("default")   # 原版用的就是 default，配色才能自己说了算
        except tk.TclError:
            pass
        st.configure(".", background=THEME_BG, foreground=THEME_FG)
        for cls in ("TFrame", "TLabelframe", "TLabelframe.Label", "TCheckbutton"):
            st.configure(cls, background=THEME_BG, foreground=THEME_FG)
        st.configure("TLabelframe", bordercolor=THEME_MUTED)
        st.configure("TLabel", background=THEME_BG, foreground=THEME_FG)
        # 按钮：常态是琥珀黄底 / 深色字，悬停反相成深底 / 黄字（照原版 TButton 的映射）
        st.configure("TButton", background=THEME_FG, foreground=THEME_BG)
        st.map("TButton",
               background=[("active", "black"), ("!disabled", THEME_FG),
                           ("disabled", "#4a4038")],
               foreground=[("active", THEME_FG), ("!disabled", THEME_BG),
                           ("disabled", "#8a7a68")])
        st.configure("TEntry", fieldbackground=THEME_INPUT, foreground=THEME_FG,
                     insertcolor=THEME_FG, highlightthickness=0)
        st.configure("TCombobox", fieldbackground=THEME_INPUT, foreground=THEME_FG,
                     arrowcolor=THEME_FG,
                     selectforeground=THEME_FG, selectbackground=THEME_INPUT)
        st.map("TCombobox",
               fieldbackground=[("active", THEME_INPUT), ("readonly", THEME_INPUT)],
               foreground=[("readonly", THEME_FG)])
        # 下拉列表是 Tk 自己的控件，只能通过 option 数据库上色
        self.root.option_add("*TCombobox*Listbox.background", THEME_INPUT)
        self.root.option_add("*TCombobox*Listbox.foreground", THEME_FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", THEME_FG)
        self.root.option_add("*TCombobox*Listbox.selectForeground", THEME_BG)
        # 滚动条照原版：黄滑块 / 棕槽。default 主题下 thumb 取的是
        # lightcolor/darkcolor，只设 background 不生效，得整套给全。
        for sb_cls in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
            st.configure(sb_cls, background=THEME_FG, troughcolor=THEME_INPUT,
                         arrowcolor="black", bordercolor=THEME_INPUT,
                         lightcolor=THEME_FG, darkcolor=THEME_FG)
        # 复选框指示器在 default 主题下不跟随样式配色，单独点一下；
        # 有些 Tk 版本不认这些选项，认不出就当外观降级，不能因此崩掉。
        try:
            st.configure("TCheckbutton", indicatorcolor=THEME_FG,
                         indicatorbackground=THEME_INPUT,
                         indicatorforeground=THEME_FG)
        except tk.TclError:
            pass
        # 原版进度条：细条、深绿；边框与槽同色，免得深色底上留一条亮线
        st.configure("TProgressbar", thickness=4, background="DarkGreen",
                     troughcolor=THEME_INPUT, bordercolor=THEME_INPUT,
                     lightcolor=THEME_INPUT, darkcolor=THEME_INPUT)

    def _build(self, cfg):
        pad = {"padx": 8, "pady": 4}

        head = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        head.pack(fill="x")
        ttk.Label(head, text=APP_TITLE,
                  font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")
        ttk.Label(head, text="选检材 → 自动跑 iLEAPP → 自动出中文报告",
                  foreground=THEME_MUTED).pack(anchor="w", pady=(2, 0))

        # ---------------- 1. 程序与检材
        f1 = ttk.LabelFrame(self.root, text=" 1. 程序与检材 ", padding=10)
        f1.pack(fill="x", padx=12, pady=(10, 0))

        ttk.Label(f1, text="iLEAPP 程序").grid(row=0, column=0, sticky="w", **pad)
        self.v_exe = tk.StringVar(value=str(find_ileapp() or ""))
        ttk.Entry(f1, textvariable=self.v_exe).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(f1, text="浏览…", command=self._pick_exe).grid(row=0, column=2, **pad)

        ttk.Label(f1, text="检材类型").grid(row=1, column=0, sticky="w", **pad)
        self.v_type = tk.StringVar(value=INPUT_TYPES[0][0])
        ttk.Combobox(f1, textvariable=self.v_type, state="readonly",
                     values=[t[0] for t in INPUT_TYPES]).grid(
            row=1, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(f1, text="检材路径").grid(row=2, column=0, sticky="w", **pad)
        self.v_in = tk.StringVar(value=cfg.get("input", ""))
        ttk.Entry(f1, textvariable=self.v_in).grid(row=2, column=1, sticky="ew", **pad)
        box = ttk.Frame(f1)
        box.grid(row=2, column=2, sticky="e")
        ttk.Button(box, text="选文件", width=8,
                   command=self._pick_input_file).pack(side="left")
        ttk.Button(box, text="选文件夹", width=9,
                   command=self._pick_input_dir).pack(side="left", padx=(4, 0))

        ttk.Label(f1, text="输出目录").grid(row=3, column=0, sticky="w", **pad)
        self.v_out = tk.StringVar(value=cfg.get("outdir", ""))
        ttk.Entry(f1, textvariable=self.v_out).grid(row=3, column=1, sticky="ew", **pad)
        ttk.Button(f1, text="浏览…", command=self._pick_out).grid(row=3, column=2, **pad)

        ttk.Label(f1, text="备份密码").grid(row=4, column=0, sticky="w", **pad)
        self.v_pwd = tk.StringVar()
        ttk.Entry(f1, textvariable=self.v_pwd, show="•").grid(
            row=4, column=1, sticky="ew", **pad)
        ttk.Label(f1, text="（仅加密的 iTunes 备份需要填）",
                  foreground=THEME_MUTED).grid(row=4, column=2, sticky="w", **pad)
        f1.columnconfigure(1, weight=1)

        # ---------------- 2. 选项
        f2 = ttk.LabelFrame(self.root, text=" 2. 选项 ", padding=10)
        f2.pack(fill="x", padx=12, pady=(10, 0))
        self.v_loc = tk.BooleanVar(value=cfg.get("do_localize", True))
        self.v_open = tk.BooleanVar(value=cfg.get("open_after", True))
        ttk.Checkbutton(f2, text="完成后自动汉化报告",
                        variable=self.v_loc).pack(side="left", padx=(0, 18))
        ttk.Checkbutton(f2, text="完成后自动打开报告",
                        variable=self.v_open).pack(side="left", padx=(0, 18))
        ttk.Label(f2, text="汉化模式").pack(side="left")
        saved_mode = cfg.get("mode", "smart")
        self.v_mode = tk.StringVar(
            value=next(lbl for lbl, val in MODE_LABELS if val == saved_mode))
        ttk.Combobox(f2, textvariable=self.v_mode, state="readonly", width=24,
                     values=[m[0] for m in MODE_LABELS]).pack(side="left", padx=(6, 0))

        # ---------------- 3. 操作
        f3 = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        f3.pack(fill="x")
        self.btn_run = ttk.Button(f3, text="▶  开始处理", command=self._start)
        self.btn_run.pack(side="left")
        self.btn_stop = ttk.Button(f3, text="■  停止", command=self._stop,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=(8, 0))
        self.btn_open = ttk.Button(f3, text="打开中文报告", command=self._open_report,
                                   state="disabled")
        self.btn_open.pack(side="left", padx=(8, 0))
        self.btn_dir = ttk.Button(f3, text="打开输出目录", command=self._open_outdir,
                                  state="disabled")
        self.btn_dir.pack(side="left", padx=(8, 0))

        self.pb = ttk.Progressbar(self.root, mode="determinate", maximum=100)
        self.pb.pack(fill="x", padx=12, pady=(8, 0))
        self.v_status = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.v_status,
                  foreground=THEME_MUTED).pack(anchor="w", padx=14, pady=(2, 0))

        # ---------------- 日志
        f4 = ttk.LabelFrame(self.root, text=" 运行日志 ", padding=6)
        f4.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        # ScrolledText 自带的是经典 Tk 滚动条，不吃 ttk 配色，永远是一根亮条。
        # 原版 iLEAPP 用的是 ttk.Scrollbar，这里照做：Text + ttk 滚动条手工组。
        self.log = tk.Text(f4, height=16, wrap="none",
                           font=("Consolas", 9),
                           background=THEME_BG, foreground=THEME_FG,
                           insertbackground=THEME_FG,
                           borderwidth=0, highlightthickness=0,
                           relief="flat")
        vsb = ttk.Scrollbar(f4, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.configure(state="disabled")

    # ------------------------------------------------------------ 选择器
    def _pick_exe(self):
        p = filedialog.askopenfilename(title="选择 ileapp.exe",
                                       filetypes=[("可执行文件", "*.exe"), ("全部", "*.*")])
        if p:
            self.v_exe.set(p)

    def _pick_input_file(self):
        p = filedialog.askopenfilename(title="选择检材文件")
        if p:
            self.v_in.set(p)
            self._guess_type(p)

    def _pick_input_dir(self):
        p = filedialog.askdirectory(title="选择检材文件夹")
        if p:
            self.v_in.set(p)
            self._guess_type(p)

    def _pick_out(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.v_out.set(p)

    def _guess_type(self, path):
        """按扩展名/结构猜检材类型，省得手动选。"""
        p = pathlib.Path(path)
        if p.is_dir():
            # iTunes 备份有 Manifest.db / Info.plist + 一堆哈希文件名
            if (p / "Manifest.db").exists() or (p / "Manifest.plist").exists():
                self.v_type.set("iTunes / Finder 备份")
            else:
                self.v_type.set("文件夹（已提取的文件系统）")
            return
        ext = p.suffix.lower()
        if ext == ".zip":
            self.v_type.set("zip 压缩包")
        elif ext in (".tar", ".xz"):
            self.v_type.set("tar 压缩包（含 .tar.xz）")
        elif ext == ".gz":
            self.v_type.set("gz 压缩包")
        elif ext in (".e01", ".ex01", ".s01", ".l01", ".ad1", ".aff", ".aff4",
                     ".dmg", ".img", ".dd", ".bin", ".vhd", ".vhdx", ".vmdk", ".qcow2"):
            self.v_type.set("磁盘镜像（E01 / img / dd / dmg 等）")
        else:
            self.v_type.set("单个文件")

    # ---------------------------------------------------------------- 运行
    def _log(self, msg):
        self.logq.put(str(msg))

    def _drain_log(self):
        try:
            while True:
                msg = self.logq.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", msg + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(120, self._drain_log)

    def _progress(self, done, total, line):
        pct = int(done * 100 / total) if total else 0
        self.pb.configure(value=pct)
        self.v_status.set(f"解析中 {done}/{total}（{pct}%）  {line[:70]}")

    def _set_running(self, running):
        self.btn_run.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")

    def _start(self):
        exe = self.v_exe.get().strip()
        inp = self.v_in.get().strip()
        outdir = self.v_out.get().strip()

        if not exe or not pathlib.Path(exe).is_file():
            messagebox.showerror(APP_TITLE, "请先指定有效的 ileapp.exe 路径。")
            return
        if not inp or not pathlib.Path(inp).exists():
            messagebox.showerror(APP_TITLE, "检材路径不存在，请重新选择。")
            return
        if not outdir:
            messagebox.showerror(APP_TITLE, "请指定输出目录。")
            return
        itype = dict((t[0], t[1]) for t in INPUT_TYPES)[self.v_type.get()]
        mode = dict((m[0], m[1]) for m in MODE_LABELS)[self.v_mode.get()]

        save_config({"ileapp": exe, "input": inp, "outdir": outdir,
                     "do_localize": self.v_loc.get(),
                     "open_after": self.v_open.get(), "mode": mode})

        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.pb.configure(value=0)
        self.last_html = None
        self.last_outdir = outdir
        self.btn_open.configure(state="disabled")
        self.btn_dir.configure(state="disabled")
        self.stop_flag = False
        self._set_running(True)
        self.v_status.set("正在启动…")

        self.worker = threading.Thread(
            target=self._work, daemon=True,
            args=(exe, itype, inp, outdir, self.v_loc.get(), mode,
                  self.v_pwd.get() or None))
        self.worker.start()

    def _stop(self):
        self.stop_flag = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self._log("…… 已请求停止")
        self.v_status.set("正在停止…")

    def _work(self, exe, itype, inp, outdir, do_loc, mode, pwd):
        try:
            res = process(exe, itype, inp, outdir, do_localize=do_loc, mode=mode,
                          password=pwd, log=self._log, on_progress=self._progress,
                          should_stop=lambda: self.stop_flag)
            self.last_html = res["report_html"]
            self.root.after(0, lambda: self._finish(res))
        except Exception as exc:
            self._log("")
            self._log("!! 出错: " + str(exc))
            for line in traceback.format_exc().splitlines()[-4:]:
                self._log("   " + line)
            self.root.after(0, lambda: self._fail(str(exc)))

    def _finish(self, res):
        self._set_running(False)
        self.pb.configure(value=100)
        if res["zh_dir"]:
            self.v_status.set("完成 —— 中文报告已生成")
        elif res["report_dir"]:
            self.v_status.set("完成 —— 英文报告已生成（未汉化）")
        else:
            self.v_status.set("已停止")
        if self.last_html and pathlib.Path(self.last_html).is_file():
            self.btn_open.configure(state="normal")
        if self.last_outdir:
            self.btn_dir.configure(state="normal")
        if self.v_open.get() and self.last_html:
            self._open_report()

    def _fail(self, msg):
        self._set_running(False)
        self.v_status.set("失败：" + msg[:60])
        if self.last_outdir:
            self.btn_dir.configure(state="normal")
        messagebox.showerror(APP_TITLE, msg)

    def _open_report(self):
        if self.last_html and pathlib.Path(self.last_html).is_file():
            os.startfile(str(self.last_html))

    def _open_outdir(self):
        if self.last_outdir and pathlib.Path(self.last_outdir).is_dir():
            os.startfile(str(self.last_outdir))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
