#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FocusTimer v9 — 仅时间面板顺滑拖动/自适应字号 · 壁纸置于数字下方(可不铺满) · 便签保存后清空 · 可打包离线
================================================================================
你关心的三点全部修复：
1) 便签切换保留 v7.7 行为：与音乐控制互不遮挡；“保存到文件”后清空输入框；在设置页可继续勾选显示/隐藏。
2) 仅时间面板：拖动不卡、双击关闭；窗口尺寸变化自动调整**字号**与**排版**；右下角图形化拖拽改变大小；Ctrl+滚轮精细缩放。
3) 壁纸：始终**位于数字下方**（不是最底层），支持**单张或文件夹**；可设置**填充比例(不铺满)**与**对齐方式**；
   使用**平均色采样缓存**先填底色，再居中绘制不铺满图像。

可选依赖（推荐）:
    pip install pillow playsound pystray
打包（Windows 示例，无控制台）：
    pip install pyinstaller
    pyinstaller -F -w FocusTimer_v8.py
"""
from __future__ import annotations
import os, sys, json, time, random, threading
from datetime import datetime, timedelta, date
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser

# === Layout constants ===
# 时间显示位置：相对于窗口中心的偏移量
TIME_X_OFFSET = 0     # 向右为正，向左为负
TIME_Y_OFFSET = -150     # 向下为正，向上为负

# 底部菜单位置
BOTTOM_MENU_X = 270            # 距离窗口左边的像素值
BOTTOM_MENU_Y_OFFSET = -230     # 相对于壁纸底边的纵向偏移量（越大越靠下）

# 壁纸绘制位置：相对于窗口中心的偏移量
WALLPAPER_X_OFFSET = 0        # 向右为正，向左为负
WALLPAPER_Y_OFFSET = 100        # 向下为正，向上为负


# ---- Optional deps ----
try:
    import winsound
except Exception:
    winsound = None
try:
    from playsound import playsound
except Exception:
    playsound = None
try:
    import pystray
    from PIL import Image, ImageTk, ImageOps, ImageDraw
except Exception:
    pystray = None
    Image = None
    ImageTk = None
    ImageOps = None
    ImageDraw = None

APP_NAME = "FocusTimer"
APP_VER  = "v9"
DATA_DIR = os.path.join(os.path.expanduser("~"), f".{APP_NAME.lower()}")
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, "data.json")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a"}

DEFAULT_DATA = {
    # 窗口
    "alpha": 0.98,
    "always_on_top": False,

    # 壁纸(主界面)
    "wallpaper_main_file": None,    # 选单张
    "wallpaper_main_dir": None,     # 选文件夹
    "wallpaper_fit_pct": 92,        # 不铺满比例：图像显示为窗口较短边的 92%
    "wallpaper_align": "center",    # 对齐：left/center/right + top/center/bottom（只做 center, top, bottom 简化）
    "wallpaper_color_cache": {},    # 采样色缓存 {path:"#rrggbb"}

    # 壁纸(仅时间)
    "wallpaper_min_file": None,
    "wallpaper_min_dir": None,
    "wallpaper_min_fit_pct": 92,
    "wallpaper_min_align": "center",

    # 仅时间面板
    "minimal_pos": None,            # [x,y]
    "minimal_size": [560, 260],     # w,h
    "minimal_font_base": 72,        # 基础字号，后续会根据窗口自适应
    "minimal_show_future": True,
    "minimal_show_notes": True,
    "minimal_notes_memory": "",     # 在应用内的持久化草稿
    "notes_save_path": None,        # 便签保存文件路径

    # 提示音/音乐
    "beep": True,
    "sound_file": None,
    "music_dir": None,
    "music_shuffle": True,

    # 任务（合并版）
    "tasks": {"高等数学": {"total": 0, "target": 25*60}, "数学建模": {"total": 0, "target": None}},
    "sessions": [],

    # 未来
    "future_events": [],
    "future_unit": "混合",
    "minimal_future_choice": "nearest",         # 月/天/小时/分钟/秒/混合
    "time_color": "#000000",   # 时间字体颜色
    "ui_tint_dynamic": True    # 根据壁纸自动调整按钮/菜单颜色
}


# --------- data io ---------
def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = DEFAULT_DATA.copy(); save_data(data)
    # 兼容 tasks int -> dict
    if isinstance(data.get("tasks"), dict):
        for k,v in list(data["tasks"].items()):
            if isinstance(v, int):
                data["tasks"][k] = {"total": v, "target": None}
    for k,v in DEFAULT_DATA.items():
        if k not in data: data[k] = v
    return data

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --------- helpers ---------
def human_hms(sec: int) -> str:
    h = sec // 3600; m = (sec % 3600) // 60; s = sec % 60
    if h: return f"{h}小时{m}分{s}秒"
    if m: return f"{m}分{s}秒"
    return f"{s}秒"

def fmt_future_delta(d: date, unit: str) -> str:
    now = datetime.now()
    tgt_dt = datetime.combine(d, datetime.min.time())
    sec = int((tgt_dt - now).total_seconds())
    prefix = "剩余" if sec >= 0 else "已过"
    asec = abs(sec)
    months = asec // (30*86400)
    days   = (asec % (30*86400)) // 86400
    hours  = (asec % 86400) // 3600
    mins   = (asec % 3600) // 60
    secs   = asec % 60
    if unit == "月":    return f"{prefix} {asec // (30*86400)} 月"
    if unit == "天":    return f"{prefix} {asec // 86400} 天"
    if unit == "小时":  return f"{prefix} {asec // 3600} 小时"
    if unit == "分钟":  return f"{prefix} {asec // 60} 分钟"
    if unit == "秒":    return f"{prefix} {asec} 秒"
    parts = []
    if months: parts.append(f"{months}月")
    if days:   parts.append(f"{days}天")
    if hours:  parts.append(f"{hours}小时")
    if mins:   parts.append(f"{mins}分")
    if secs or not parts: parts.append(f"{secs}秒")
    return f"{prefix} " + "".join(parts)

def list_images(dir_or_none):
    if not dir_or_none: return []
    try:
        items = []
        for fn in os.listdir(dir_or_none):
            p = os.path.join(dir_or_none, fn)
            if os.path.splitext(fn)[1].lower() in IMAGE_EXTS and os.path.isfile(p):
                items.append(p)
        return items
    except Exception:
        return []

def avg_color_hex(path, fallback="#f0f0f3", data=None):
    if Image is None or not path or not os.path.exists(path):
        return fallback
    if data is not None:
        cache = data.setdefault("wallpaper_color_cache", {})
        c = cache.get(path)
        if isinstance(c, str):
            return c
    try:
        with Image.open(path) as im:
            im = im.convert("RGB").resize((40, 40))
            px = list(im.getdata())
            r = sum(p[0] for p in px) // len(px)
            g = sum(p[1] for p in px) // len(px)
            b = sum(p[2] for p in px) // len(px)
            hexv = f"#{r:02x}{g:02x}{b:02x}"
            if data is not None:
                data["wallpaper_color_cache"][path] = hexv; save_data(data)
            return hexv
    except Exception:
        return fallback

# --------- main app ---------
class FocusTimerApp(tk.Tk):
    def __init__(self):
        # v9 additions: style/tint helpers are defined below

        super().__init__()
        self.title(f"{APP_NAME} {APP_VER}")
        self.geometry("1140x720")
        self.minsize(980, 600)

        self.data = load_data()
        self.attributes("-alpha", self.data.get("alpha", 0.98))
        self.attributes("-topmost", self.data.get("always_on_top", False))

        # 状态
        self._timer_running = False
        self._timer_paused  = False
        self._mode = tk.StringVar(value="countdown")
        self._countdown_seconds = tk.IntVar(value=25*60)

        # 背景引用
        self._main_bg_img = None
        self._min_bg_img  = None

        # 仅时间
        self.minimal_win = None
        self.minimal_label = None
        self.minimal_info  = None
        self.minimal_bg    = None
        self.minimal_notes = None
        self._drag_off = (0,0)
        self._last_min_wallpaper_size = (0,0)  # 降低重绘频率

        # 音乐
        self._music_thr = None
        self._music_stop = threading.Event()
        self._music_pause = threading.Event()

        # UI
        self._build_ui()
        self._apply_main_wallpaper()

        # 绑定尺寸变化重绘（含节流）
        self._repaint_scheduled = False
        self.layer.bind("<Configure>", self._on_layer_configure)


    # ----- UI Tint helpers -----
    def _hex_to_rgb(self, hx):
        try:
            hx = hx.lstrip("#")
            return tuple(int(hx[i:i+2], 16) for i in (0,2,4))
        except Exception:
            return (240,240,243)

    def _luminance(self, rgb):
        r,g,b = [c/255.0 for c in rgb]
        return 0.2126*r + 0.7152*g + 0.0722*b

    def _contrast_fg(self, bg_rgb):
        return "#000000" if self._luminance(bg_rgb) > 0.6 else "#ffffff"

    def _apply_tint(self, bg_hex):
        try:
            st = ttk.Style()
            rgb = self._hex_to_rgb(bg_hex)
            fg = self._contrast_fg(rgb)
            # base style
            st.configure("TButton", background=bg_hex, foreground=fg)
            st.map("TButton", background=[("active", bg_hex)], foreground=[("active", fg)])
            st.configure("TNotebook", background=bg_hex)
            st.configure("TNotebook.Tab", background=bg_hex, foreground=fg)
            st.configure("Treeview", background="white", foreground="#222")
            # timer label color
            self.timer_label.configure(fg=self.data.get("time_color", "#000000"))
        except Exception:
            pass

    # ----- UI -----
    def _build_ui(self):
        top = ttk.Frame(self); top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=8)
        self._quote = tk.StringVar(value=self._load_random_or_direct_quote())
        ttk.Label(top, textvariable=self._quote, font=("Microsoft YaHei", 12)).pack(side=tk.LEFT)
        ttk.Button(top, text="导出记录", command=self._export_sessions).pack(side=tk.LEFT, padx=6)
        self.topmost_var = tk.BooleanVar(value=self.data.get("always_on_top", False))
        ttk.Checkbutton(top, text="置顶", variable=self.topmost_var, command=self._toggle_topmost).pack(side=tk.LEFT, padx=6)
        self.beep_var = tk.BooleanVar(value=self.data.get("beep", True))
        ttk.Checkbutton(top, text="提示音", variable=self.beep_var, command=self._toggle_beep).pack(side=tk.LEFT, padx=6)

        # 分层容器
        self.layer = tk.Frame(self, bd=0, highlightthickness=0)
        self.layer.pack(fill=tk.BOTH, expand=True)

        # 关键：在“计时器页”内部实现**壁纸在数字下方**的局部分层（不是全窗口最底层）
        self.nb = ttk.Notebook(self.layer); self.nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.page_timer = ttk.Frame(self.nb); self.nb.add(self.page_timer, text="计时器")
        self._build_timer_page(self.page_timer)

        self.page_tasks = ttk.Frame(self.nb); self.nb.add(self.page_tasks, text="待办")
        self._build_tasks_page(self.page_tasks)

        self.page_future = ttk.Frame(self.nb); self.nb.add(self.page_future, text="未来倒计时")
        self._build_future_page(self.page_future)

        self.page_stats = ttk.Frame(self.nb); self.nb.add(self.page_stats, text="统计")
        self._build_stats_page(self.page_stats)

        self.page_settings = ttk.Frame(self.nb); self.nb.add(self.page_settings, text="设置")
        self._build_settings_page(self.page_settings)

        # ----- Quote -----
    def _load_random_or_direct_quote(self):
        p = self.data.get("quote_file")
        if p and os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [ln.strip() for ln in f if ln.strip()]
                if lines: return random.choice(lines)
            except Exception: pass
        return self.data.get("quote", "加油！")

    # ----- Wallpaper helpers (Main) -----
    def _pick_main(self):
        f = self.data.get("wallpaper_main_file")
        if f and os.path.exists(f): return f
        d = self.data.get("wallpaper_main_dir")
        files = list_images(d)
        return random.choice(files) if files else None

    def _apply_main_wallpaper(self):
        """主界面背景：显示在‘计时器页的舞台(stage)’下方（数字上方无其它层）。"""
        # 只在计时器页做局部壁纸
        self._draw_timer_wallpaper()

    def _on_layer_configure(self, e):
        if not self._repaint_scheduled:
            self._repaint_scheduled = True
            self.after(50, self._apply_main_wallpaper)

    # ----- Timer Page with staged wallpaper under digits -----
    def _build_timer_page(self, parent):
        # 舞台（独立容器）：内部用 Canvas 画平均色底+不铺满图片；其上再放时间/控件
        self.stage = tk.Canvas(parent, highlightthickness=0, bd=0)
        self.stage.pack(fill=tk.BOTH, expand=True)

        # 顶部控制条
        topbar = ttk.Frame(self.stage)
        self.stage.create_window(10, 10, window=topbar, anchor="nw")

        # 任务下拉（用于记录到指定任务）
        ttk.Label(topbar, text="任务:").pack(side=tk.LEFT, padx=(0,4))
        task_names = list(self.data.get("tasks", {}).keys()) or ["默认任务"]
        if "默认任务" not in self.data.get("tasks", {}):
            self.data.setdefault("tasks", {})["默认任务"] = {"total": 0, "target": None}
        self.task_var = tk.StringVar(value=task_names[0])
        self.task_box = ttk.Combobox(topbar, state="readonly", values=task_names, textvariable=self.task_var, width=12)
        self.task_box.pack(side=tk.LEFT, padx=(0,10))

        ttk.Label(topbar, text="模式:").pack(side=tk.LEFT)
        self._mode.set("countdown")
        ttk.Radiobutton(topbar, text="倒计时", value="countdown", variable=self._mode).pack(side=tk.LEFT)
        ttk.Radiobutton(topbar, text="正计时", value="countup",    variable=self._mode).pack(side=tk.LEFT)

        ttk.Button(topbar, text="仅时间显示", command=self._toggle_minimal).pack(side=tk.RIGHT)

        # 中央时间
        self.timer_label = tk.Label(self.stage, text="00:00:00", font=("Segoe UI", 64, "bold"), fg=self.data.get("time_color", "#000000"), bg="#ffffff")
        self.stage_time_id = self.stage.create_window(0, 0, window=self.timer_label, anchor="center")

        # 预设与控制
        bottom = ttk.Frame(self.stage); self.stage.create_window(10, 0, window=bottom, anchor="sw")
        for m in (25, 35):
            ttk.Button(bottom, text=f"{m}分钟", command=lambda mm=m: self._set_preset(mm)).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="自定义", command=self._custom_time).pack(side=tk.LEFT, padx=4)
        self.btn_start = ttk.Button(bottom, text="开始", command=self.start_timer)
        self.btn_pause = ttk.Button(bottom, text="暂停", command=self.pause_timer, state=tk.DISABLED)
        self.btn_stop  = ttk.Button(bottom, text="停止/记录", command=self.stop_timer, state=tk.DISABLED)
        for b in (self.btn_start, self.btn_pause, self.btn_stop): b.pack(side=tk.LEFT, padx=6)

        # 舞台尺寸变化时重排与重绘
        self.stage.bind("<Configure>", self._layout_timer_stage)

    def _layout_timer_stage(self, e=None):
        w = max(1, self.stage.winfo_width()); h = max(1, self.stage.winfo_height())
        # 顶部条摆放
        self.stage.coords(1, 10, 10)   # 顶部条 window item id=1（创建顺序）
        # 中央时间位置
        self.stage.coords(self.stage_time_id, w//2 + TIME_X_OFFSET, h//2 + TIME_Y_OFFSET)
        # 底部条靠左下
        self.stage.coords(3, BOTTOM_MENU_X, min(h-10, int(getattr(self, "_main_img_bottom", int(h*0.75))) + BOTTOM_MENU_Y_OFFSET)) # bottom window id=3（创建顺序）
        # 背景重绘
        self._draw_timer_wallpaper()
        # 自适应字号（根据舞台高度以及字符长度）
        self._autoscale_timer_font(w, h)

    def _draw_timer_wallpaper(self):
        w = max(1, self.stage.winfo_width()); h = max(1, self.stage.winfo_height())
        if Image is None or ImageTk is None:
            # 无PIL时仅填底色
            self.stage.configure(bg="#f0f0f3"); return
        path = self._pick_main()
        if not path:
            self.stage.configure(bg="#f0f0f3"); self.stage.delete("bg");
            self._main_img_bottom = max(0, self.stage.winfo_height() - 40)
            return
        # 采样色打底
        avg = avg_color_hex(path, data=self.data)
        self.stage.configure(bg=avg)
        if self.data.get("ui_tint_dynamic", True):
            self._apply_tint(avg)
        self.stage.delete("bg")
        # 不铺满：按短边 fit_pct 缩放，保持居中
        fit_pct = int(self.data.get("wallpaper_fit_pct", 92))
        w = max(1, self.stage.winfo_width()); h = max(1, self.stage.winfo_height())
        short = min(w, h) * max(10, min(fit_pct, 100)) // 100
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                im = ImageOps.contain(im, (short, short))  # 等比，短边=short
                self._main_bg_img = ImageTk.PhotoImage(im)
            # 计算放置位置（仅 center / top / bottom 三种对齐）
            align = (self.data.get("wallpaper_align") or "center").lower()
            cx, cy = w//2, h//2
            if "top" in align: cy = short//2 + 20
            elif "bottom" in align: cy = h - short//2 - 20
            # 在 Canvas 上绘制图片 (置于数字下方：使用tag 'bg'，且先画背景后续 create_window 的时间Label自然在上层)
            cx += WALLPAPER_X_OFFSET

            cy += WALLPAPER_Y_OFFSET

            self.stage.create_image(cx, cy, image=self._main_bg_img, tags=("bg",))
        except Exception:
            pass

    def _autoscale_timer_font(self, w, h):
        txt = self.timer_label.cget("text")
        base = int(self.data.get("minimal_font_base", 72))
        # 根据高度和字符数综合估计
        k = max(28, int(min(h*0.28, w*0.12 / max(1,len(txt)))))
        size = max(28, min(160, int((base + k) * 0.5)))
        self.timer_label.configure(font=("Segoe UI", size, "bold"))

    # ----- Tasks -----
    def _build_tasks_page(self, parent):
        bar = ttk.Frame(parent); bar.pack(fill=tk.X, pady=6)
        ttk.Button(bar, text="新增任务", command=self._add_task).pack(side=tk.LEFT)
        ttk.Button(bar, text="删除任务", command=self._del_task).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="设置目标", command=self._set_task_target).pack(side=tk.LEFT, padx=6)

        cols = ("name","target","total","remain")
        self.tasks_tree = ttk.Treeview(parent, columns=cols, show="headings", height=14)
        for c,t in zip(cols, ("任务","目标","累计","剩余/倒计时")):
            self.tasks_tree.heading(c, text=t)
        self.tasks_tree.column("name", width=260, anchor=tk.W)
        self.tasks_tree.pack(fill=tk.BOTH, expand=True)

        self._refresh_tasks()

    def _refresh_tasks(self):
        if not hasattr(self, "tasks_tree"): return
        for i in self.tasks_tree.get_children(): self.tasks_tree.delete(i)
        # 普通任务
        for name, info in self.data.get("tasks", {}).items():
            tgt = info.get("target"); tot = int(info.get("total",0))
            rem = (tgt - tot) if isinstance(tgt,int) else None
            v_tgt = human_hms(tgt) if isinstance(tgt,int) else "-"
            v_tot = human_hms(tot)
            if isinstance(rem,int):
                v_rem = (human_hms(rem) if rem>=0 else "超出"+human_hms(-rem))
            else:
                v_rem = "-"
            self.tasks_tree.insert("", tk.END, values=(name, v_tgt, v_tot, v_rem))
        # 未来映射
        for ev in self.data.get("future_events", []):
            try:
                d = datetime.strptime(ev["date"], "%Y-%m-%d").date()
                remain_txt = fmt_future_delta(d, self.data.get("future_unit","混合"))
                self.tasks_tree.insert("", tk.END, values=(f"【未来】{ev['title']}", "-", "-", remain_txt))
            except Exception:
                continue

    def _add_task(self):
        name = self._prompt_text("新增任务", "输入任务名称")
        if not name: return
        if name in self.data.get("tasks", {}):
            messagebox.showwarning("提示","该任务已存在"); return
        self.data["tasks"][name] = {"total":0, "target": None}
        save_data(self.data); self._refresh_tasks()

    def _del_task(self):
        sel = self.tasks_tree.selection()
        if not sel: return
        name = self.tasks_tree.item(sel[0], "values")[0]
        if name.startswith("【未来】"): return
        self.data["tasks"].pop(name, None); save_data(self.data); self._refresh_tasks()

    def _set_task_target(self):
        sel = self.tasks_tree.selection()
        if not sel: return
        name = self.tasks_tree.item(sel[0], "values")[0]
        if name.startswith("【未来】"): return
        cur_tgt = int(self.data["tasks"][name].get("target") or 0)
        w = tk.Toplevel(self); w.title(f"设置目标 - {name}")
        tk.Label(w, text="目标(分钟)").pack(side=tk.LEFT, padx=8, pady=8)
        v = tk.IntVar(value=cur_tgt//60)
        tk.Spinbox(w, from_=0, to=100000, textvariable=v, width=10).pack(side=tk.LEFT, padx=8)
        ttk.Button(w, text="确定", command=lambda: self._apply_task_target(w, name, v.get()*60)).pack(side=tk.LEFT, padx=8)

    def _apply_task_target(self, w, name, tgt_sec):
        self.data["tasks"][name]["target"] = int(tgt_sec); save_data(self.data); self._refresh_tasks(); w.destroy()

    # ----- Future -----
    def _build_future_page(self, parent):
        bar = ttk.Frame(parent); bar.pack(fill=tk.X, pady=6)
        ttk.Button(bar, text="添加事件", command=self._add_future).pack(side=tk.LEFT)
        ttk.Button(bar, text="删除事件", command=self._del_future).pack(side=tk.LEFT, padx=6)
        ttk.Label(bar, text="单位:").pack(side=tk.LEFT, padx=(12,2))
        self.future_unit_var = tk.StringVar(value=self.data.get("future_unit","混合"))
        cb = ttk.Combobox(bar, state="readonly", textvariable=self.future_unit_var,
                          values=["月","天","小时","分钟","秒","混合"]); cb.pack(side=tk.LEFT)
        cb.bind("<<ComboboxSelected>>", lambda e: (self._save_future_unit(), self._refresh_future(), self._refresh_tasks()))

        self.future_tree = ttk.Treeview(parent, columns=("event","date","remain"), show="headings", height=12)
        for c,t in (("event","事件"),("date","日期"),("remain","剩余")):
            self.future_tree.heading(c, text=t)
        self.future_tree.column("event", width=260, anchor=tk.W)
        self.future_tree.pack(fill=tk.BOTH, expand=True)
        self._refresh_future()

    def _save_future_unit(self):
        self.data["future_unit"] = self.future_unit_var.get(); save_data(self.data)

    def _refresh_future(self):
        if not hasattr(self,"future_tree"): return
        for i in self.future_tree.get_children(): self.future_tree.delete(i)
        for ev in self.data.get("future_events", []):
            try:
                d = datetime.strptime(ev["date"], "%Y-%m-%d").date()
                self.future_tree.insert("", tk.END, values=(ev["title"], ev["date"], fmt_future_delta(d, self.data.get("future_unit","混合"))))
            except Exception:
                continue

    def _add_future(self):
        d0 = date.today() + timedelta(days=3)
        w = tk.Toplevel(self); w.title("添加未来事件")
        frm = ttk.Frame(w); frm.pack(padx=10, pady=10)
        y = tk.IntVar(value=d0.year); m = tk.IntVar(value=d0.month); d = tk.IntVar(value=d0.day)
        ttk.Label(frm, text="年").grid(row=0, column=0); tk.Spinbox(frm, from_=1970, to=2100, textvariable=y, width=6).grid(row=0, column=1)
        ttk.Label(frm, text="月").grid(row=0, column=2); tk.Spinbox(frm, from_=1, to=12, textvariable=m, width=4).grid(row=0, column=3)
        ttk.Label(frm, text="日").grid(row=0, column=4); tk.Spinbox(frm, from_=1, to=31, textvariable=d, width=4).grid(row=0, column=5)
        e_title = ttk.Entry(frm, width=30); e_title.grid(row=1, column=0, columnspan=6, pady=8); e_title.insert(0, "事件名称")
        def ok():
            try:
                dt = date(int(y.get()), int(m.get()), int(d.get()))
            except Exception:
                messagebox.showerror("格式错误","日期无效"); return
            title = e_title.get().strip() or "未来事件"
            self.data.setdefault("future_events", []).append({"title": title, "date": dt.isoformat()})
            save_data(self.data); self._refresh_future(); self._refresh_tasks(); w.destroy()
        ttk.Button(frm, text="确定", command=ok).grid(row=2, column=0, columnspan=6, pady=6)

    def _del_future(self):
        sel = self.future_tree.selection()
        if not sel: return
        idx = self.future_tree.index(sel[0])
        if 0 <= idx < len(self.data.get("future_events", [])):
            self.data["future_events"].pop(idx); save_data(self.data); self._refresh_future(); self._refresh_tasks()

    # ----- Stats -----
    def _build_stats_page(self, parent):
        box = ttk.Frame(parent); box.pack(fill=tk.X, pady=6)
        self.stats_summary = ttk.Label(box, text=""); self.stats_summary.pack(side=tk.LEFT)
        self.sessions_tree = ttk.Treeview(parent, columns=("task","dur","start","end"), show="headings")
        for c,t in zip(("task","dur","start","end"), ("任务","时长","开始","结束")):
            self.sessions_tree.heading(c, text=t)
        self.sessions_tree.pack(fill=tk.BOTH, expand=True, pady=6)
        bar = ttk.Frame(parent); bar.pack(fill=tk.X)
        ttk.Button(bar, text="刷新", command=self._update_stats_summary).pack(side=tk.LEFT)
        ttk.Button(bar, text="清空记录(谨慎)", command=self._clear_sessions).pack(side=tk.LEFT, padx=6)
        self._update_stats_summary()

    def _update_stats_summary(self):
        today = date.today(); start_week = today - timedelta(days=today.weekday()); start_month = today.replace(day=1)
        daily = weekly = monthly = 0; count_today = 0
        for s in self.data.get("sessions", []):
            end_dt = datetime.fromisoformat(s["end_iso"]).date()
            if end_dt == today: daily += s["seconds"]; count_today += 1
            if end_dt >= start_week: weekly += s["seconds"]
            if end_dt >= start_month: monthly += s["seconds"]
        self.stats_summary.config(text=f"今日 {daily//60} 分 | 本周 {weekly//60} 分 | 本月 {monthly//60} 分 | 今日次数 {count_today}")
        for i in self.sessions_tree.get_children(): self.sessions_tree.delete(i)
        for s in reversed(self.data.get("sessions", [])[-500:]):
            self.sessions_tree.insert("", tk.END, values=(s["task"], human_hms(s["seconds"]), s["start_iso"], s["end_iso"]))

    def _clear_sessions(self):
        if messagebox.askyesno("确认","确定清空所有历史会话记录？累计总时长会保留。"):
            self.data["sessions"] = []; save_data(self.data); self._update_stats_summary()

    # ----- Settings -----
    def _build_settings_page(self, parent):
        p = ttk.Notebook(parent); p.pack(fill=tk.BOTH, expand=True)

        # 壁纸
        tab_wp = ttk.Frame(p); p.add(tab_wp, text="壁纸")
        fm1 = ttk.LabelFrame(tab_wp, text="主界面壁纸"); fm1.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(fm1, text="选择单张", command=lambda: self._choose_wallpaper(True, "main")).pack(side=tk.LEFT, padx=6, pady=6)
        ttk.Button(fm1, text="选择文件夹", command=lambda: self._choose_wallpaper(False, "main")).pack(side=tk.LEFT, padx=6)
        ttk.Label(fm1, text="不铺满%").pack(side=tk.LEFT, padx=(18,2))
        self.fit_main = tk.IntVar(value=int(self.data.get("wallpaper_fit_pct", 92)))
        tk.Spinbox(fm1, from_=50, to=100, textvariable=self.fit_main, width=5,
                   command=lambda: self._apply_fit_pct("main", self.fit_main.get())).pack(side=tk.LEFT)
        ttk.Label(fm1, text="对齐").pack(side=tk.LEFT, padx=(12,2))
        self.align_main = tk.StringVar(value=self.data.get("wallpaper_align","center"))
        ttk.Combobox(fm1, state="readonly", textvariable=self.align_main, values=["top","center","bottom"],
                     width=7).pack(side=tk.LEFT)
        ttk.Button(fm1, text="应用", command=lambda: self._apply_align_and_fit("main")).pack(side=tk.LEFT, padx=8)
        ttk.Label(fm1, text="支持：.jpg/.jpeg/.png/.webp/.bmp/.gif").pack(side=tk.LEFT, padx=10)

        fm2 = ttk.LabelFrame(tab_wp, text="仅时间壁纸"); fm2.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(fm2, text="选择单张", command=lambda: self._choose_wallpaper(True, "min")).pack(side=tk.LEFT, padx=6, pady=6)
        ttk.Button(fm2, text="选择文件夹", command=lambda: self._choose_wallpaper(False, "min")).pack(side=tk.LEFT, padx=6)
        ttk.Label(fm2, text="不铺满%").pack(side=tk.LEFT, padx=(18,2))
        self.fit_min = tk.IntVar(value=int(self.data.get("wallpaper_min_fit_pct", 92)))
        tk.Spinbox(fm2, from_=50, to=100, textvariable=self.fit_min, width=5,
                   command=lambda: self._apply_fit_pct("min", self.fit_min.get())).pack(side=tk.LEFT)
        ttk.Label(fm2, text="对齐").pack(side=tk.LEFT, padx=(12,2))
        self.align_min = tk.StringVar(value=self.data.get("wallpaper_min_align","center"))
        ttk.Combobox(fm2, state="readonly", textvariable=self.align_min, values=["top","center","bottom"],
                     width=7).pack(side=tk.LEFT)
        ttk.Button(fm2, text="应用", command=lambda: self._apply_align_and_fit("min")).pack(side=tk.LEFT, padx=8)

        # 仅时间
        tab_min = ttk.Frame(p); p.add(tab_min, text="仅时间")
        fm_m1 = ttk.LabelFrame(tab_min, text="显示内容"); fm_m1.pack(fill=tk.X, padx=10, pady=8)
        self.show_future_var = tk.BooleanVar(value=self.data.get("minimal_show_future", True))
        self.show_notes_var  = tk.BooleanVar(value=self.data.get("minimal_show_notes", True))
        ttk.Checkbutton(fm_m1, text="显示未来倒计时", variable=self.show_future_var, command=self._save_minimal_toggles).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(fm_m1, text="显示便签",   variable=self.show_notes_var, command=self._save_minimal_toggles).pack(side=tk.LEFT, padx=6)

        fm_m_sel = ttk.LabelFrame(tab_min, text="未来倒计时显示"); fm_m_sel.pack(fill=tk.X, padx=10, pady=8)
        ttk.Label(fm_m_sel, text="显示事件:").pack(side=tk.LEFT, padx=6)
        self.minimal_future_choice_var = tk.StringVar(value="最近一个(自动)")
        self.minimal_future_choice_cb = ttk.Combobox(fm_m_sel, state="readonly", textvariable=self.minimal_future_choice_var, values=[])
        self.minimal_future_choice_cb.pack(side=tk.LEFT, padx=6)
        self.minimal_future_choice_cb.bind("<<ComboboxSelected>>", lambda e: self._save_minimal_future_choice())
        self._refresh_minimal_future_choice()
        ttk.Label(fm_m_sel, text="显示格式：事件名 + 剩余时间").pack(side=tk.LEFT, padx=12)
        fm_m2 = ttk.LabelFrame(tab_min, text="便签与路径"); fm_m2.pack(fill=tk.X, padx=10, pady=8)
        # 外观
        tab_appearance = ttk.Frame(p); p.add(tab_appearance, text="显示样式")
        sec = ttk.LabelFrame(tab_appearance, text="时间字体与主题色"); sec.pack(fill=tk.X, padx=10, pady=8)
        ttk.Label(sec, text="时间字体颜色").pack(side=tk.LEFT, padx=6, pady=6)
        ttk.Button(sec, text="选择颜色", command=self._choose_time_color).pack(side=tk.LEFT, padx=6)
        self.time_color_demo = tk.Label(sec, text="预览 12:34:56", font=("Segoe UI", 16, "bold"),
                                        fg=self.data.get("time_color", "#000000"), bg="#ffffff")
        self.time_color_demo.pack(side=tk.LEFT, padx=12)

        sec2 = ttk.LabelFrame(tab_appearance, text="动态换肤"); sec2.pack(fill=tk.X, padx=10, pady=8)
        self.tint_var = tk.BooleanVar(value=self.data.get("ui_tint_dynamic", True))
        ttk.Checkbutton(sec2, text="根据壁纸平均色自动调整按钮/菜单颜色", variable=self.tint_var, command=self._save_tint_toggle).pack(side=tk.LEFT, padx=6, pady=6)

        ttk.Button(fm_m2, text="选择便签保存文件", command=self._choose_notes_path).pack(side=tk.LEFT, padx=6, pady=6)
        self.notes_path_var = tk.StringVar(value=self.data.get("notes_save_path") or "")
        ttk.Entry(fm_m2, textvariable=self.notes_path_var, width=48, state="readonly").pack(side=tk.LEFT, padx=6)

    def _apply_fit_pct(self, which, val):
        val = int(val); val = max(50, min(100, val))
        if which=="main":
            self.data["wallpaper_fit_pct"] = val; save_data(self.data); self._apply_main_wallpaper()
        else:
            self.data["wallpaper_min_fit_pct"] = val; save_data(self.data); self._apply_min_wallpaper()

    def _apply_align_and_fit(self, which):
        if which=="main":
            self.data["wallpaper_align"] = self.align_main.get(); save_data(self.data); self._apply_main_wallpaper()
        else:
            self.data["wallpaper_min_align"] = self.align_min.get(); save_data(self.data); self._apply_min_wallpaper()

    def _choose_wallpaper(self, single: bool, which: str):
        if single:
            pth = filedialog.askopenfilename(title="选择图片", filetypes=[("Image","*.jpg *.jpeg *.png *.bmp *.gif *.webp")])
            if not pth: return
            if which=="main": self.data["wallpaper_main_file"] = pth
            else: self.data["wallpaper_min_file"] = pth
        else:
            d = filedialog.askdirectory(title="选择图片文件夹")
            if not d: return
            if which=="main": self.data["wallpaper_main_dir"] = d
            else: self.data["wallpaper_min_dir"] = d
        try:
            self._refresh_minimal_future_choice()
        except Exception:
            pass

        save_data(self.data)
        if which=="main": self._apply_main_wallpaper()
        else: self._apply_min_wallpaper()

    def _save_minimal_toggles(self):
        self.data["minimal_show_future"] = self.show_future_var.get()
        self.data["minimal_show_notes"]  = self.show_notes_var.get()
        save_data(self.data)

    def _refresh_minimal_future_choice(self):
        events = self.data.get("future_events", [])
        options = ["最近一个(自动)"] + [f"{ev.get('title','未命名')}（{ev.get('date','')}）" for ev in events]
        try: self.minimal_future_choice_cb["values"] = options
        except Exception: pass
        cur = self.data.get("minimal_future_choice", "nearest")
        if cur == "nearest":
            val = "最近一个(自动)"
        else:
            val = None
            for ev in events:
                if ev.get("title") == cur:
                    val = f"{ev.get('title','未命名')}（{ev.get('date','')}）"; break
            if not val: val = "最近一个(自动)"
        try: self.minimal_future_choice_var.set(val)
        except Exception: pass

    def _save_minimal_future_choice(self):
        try: v = self.minimal_future_choice_var.get()
        except Exception: v = "最近一个(自动)"
        if v.startswith("最近一个"):
            self.data["minimal_future_choice"] = "nearest"
        else:
            title = v.split("（",1)[0].split(" (",1)[0].strip()
            self.data["minimal_future_choice"] = title or "nearest"
        save_data(self.data)
        try: self._update_minimal_nearest_future()
        except Exception: pass

    def _choose_notes_path(self):
        p = filedialog.asksaveasfilename(title="选择/创建便签保存文件", defaultextension=".txt",
                                         filetypes=[("Text","*.txt"),("All","*.*")])
        if not p: return
        self.data["notes_save_path"] = p; save_data(self.data); self.notes_path_var.set(p)


    def _choose_time_color(self):
        c = colorchooser.askcolor(color=self.data.get("time_color", "#000000"), title="选择时间字体颜色")
        if c and c[1]:
            self.data["time_color"] = c[1]; save_data(self.data)
            # 应用到主/仅时间标签与预览
            try:
                self.timer_label.configure(fg=c[1])
            except Exception:
                pass
            try:
                if self.minimal_label: self.minimal_label.configure(fg=c[1])
            except Exception:
                pass
            try:
                if hasattr(self, "time_color_demo"): self.time_color_demo.configure(fg=c[1])
            except Exception:
                pass

    def _save_tint_toggle(self):
        self.data["ui_tint_dynamic"] = bool(self.tint_var.get()); save_data(self.data)
        # 立即重绘一次以生效/失效
        self._apply_main_wallpaper()
        if self.minimal_win: self._draw_min_wallpaper(force=True)

    # ----- Timer Core -----
    def _set_preset(self, minutes: int):
        self._countdown_seconds.set(minutes*60); self._mode.set("countdown"); self._render_time(self._countdown_seconds.get())

    def _custom_time(self):
        w = tk.Toplevel(self); w.title("自定义时长")
        tk.Label(w, text="分钟").pack(side=tk.RIGHT, padx=6)
        val = tk.IntVar(value=max(1, self._countdown_seconds.get()//60))
        tk.Spinbox(w, from_=1, to=600, textvariable=val, width=10).pack(side=tk.RIGHT)
        ttk.Button(w, text="确定", command=lambda: self._apply_custom_time(w, val.get())).pack(pady=6)
    def _apply_custom_time(self, w, m):
        self._countdown_seconds.set(int(m)*60); self._mode.set("countdown"); self._render_time(self._countdown_seconds.get()); w.destroy()

    def _render_time(self, sec):
        self.timer_label.config(text=time.strftime("%H:%M:%S", time.gmtime(max(0, sec))), fg=self.data.get("time_color", "#000000"))
        # 自适应字号（舞台尺寸可能改变）
        self._autoscale_timer_font(self.stage.winfo_width() or 800, self.stage.winfo_height() or 400)
        # 更新仅时间
        if self.minimal_label is not None:
            self.minimal_label.config(text=self.timer_label.cget("text"))
        if self.minimal_info is not None and self.data.get("minimal_show_future", True):
            self._update_minimal_nearest_future()

    def start_timer(self):
        if self._timer_running: return
        self._timer_running = True; self._timer_paused = False
        self.btn_start.config(state=tk.DISABLED); self.btn_pause.config(state=tk.NORMAL); self.btn_stop.config(state=tk.NORMAL)
        if self._mode.get()=="countdown":
            total = self._countdown_seconds.get(); self._render_time(total)
            def run():
                remain = total
                while self._timer_running and remain>0:
                    if not self._timer_paused:
                        remain -= 1
                        self.after(0, lambda r=remain: self._render_time(r))
                        time.sleep(1)
                    else:
                        time.sleep(0.1)
                self.after(0, lambda: self._finish_session(total-remain))
            threading.Thread(target=run, daemon=True).start()
        else:
            def run():
                t0 = time.time()
                while self._timer_running:
                    if not self._timer_paused:
                        sec = int(time.time()-t0)
                        self.after(0, lambda s=sec: self._render_time(s))
                        time.sleep(1)
                    else:
                        time.sleep(0.1)
            threading.Thread(target=run, daemon=True).start()

    def pause_timer(self):
        if not self._timer_running: return
        self._timer_paused = not self._timer_paused
        self.btn_pause.config(text="继续" if self._timer_paused else "暂停")

    def stop_timer(self):
        if not self._timer_running: return
        shown = self.timer_label.cget("text"); h,m,s = map(int, shown.split(":"))
        used = h*3600+m*60+s
        if self._mode.get()=="countdown": used = self._countdown_seconds.get()-used
        self._finish_session(max(0, used))

    def _finish_session(self, used_seconds: int):
        self._timer_running = False; self._timer_paused = False
        self.btn_start.config(state=tk.NORMAL); self.btn_pause.config(text="暂停", state=tk.DISABLED); self.btn_stop.config(state=tk.DISABLED)
        if self.data.get("beep", True): self._play_alarm()
        if used_seconds>0 and self.data.get("tasks"):
            # 记录到第一个任务（或可扩展为下拉选择）
            k = self.task_var.get() if hasattr(self, "task_var") and self.task_var.get() in self.data["tasks"] else next(iter(self.data["tasks"].keys()))
            self.data["tasks"][k]["total"] = int(self.data["tasks"][k].get("total",0)) + used_seconds
            now = datetime.now()
            self.data.setdefault("sessions", []).append({
                "task": k,
                "seconds": used_seconds,
                "start_iso": (now - timedelta(seconds=used_seconds)).isoformat(timespec="seconds"),
                "end_iso": now.isoformat(timespec="seconds")
            })
            save_data(self.data); self._refresh_tasks()
        self._render_time(0)

    def _play_alarm(self):
        def worker():
            sf = self.data.get("sound_file")
            try:
                if sf and os.path.exists(sf):
                    ext = os.path.splitext(sf)[1].lower()
                    if winsound and ext==".wav": winsound.PlaySound(sf, winsound.SND_FILENAME | winsound.SND_ASYNC); return
                    if playsound: playsound(sf); return
                if winsound: winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC); return
            except Exception:
                pass
            try:
                for _ in range(2): self.bell(); time.sleep(0.12)
            except Exception: pass
        threading.Thread(target=worker, daemon=True).start()

    # ----- Minimal (Time-only) -----
    def _toggle_minimal(self):
        if self.minimal_win is None: self._open_minimal()
        else: self._close_minimal()

    def _pick_min(self):
        f = self.data.get("wallpaper_min_file")
        if f and os.path.exists(f): return f
        files = list_images(self.data.get("wallpaper_min_dir"))
        return random.choice(files) if files else None

    def _open_minimal(self):
        if self.minimal_win is not None: return
        self.minimal_win = tk.Toplevel(self)
        self.minimal_win.overrideredirect(True)
        self.minimal_win.attributes("-topmost", True)
        self.minimal_win.configure(bg="white")
        mw,mh = self.data.get("minimal_size", [560,260])
        sw,sh = self.winfo_screenwidth(), self.winfo_screenheight()
        pos = self.data.get("minimal_pos") or [(sw-mw)//2, (sh-mh)//2]
        self.minimal_win.geometry(f"{mw}x{mh}+{int(pos[0])}+{int(pos[1])}")

        # 背景容器
        self.minimal_bg = tk.Canvas(self.minimal_win, highlightthickness=0, bd=0, bg="white")
        self.minimal_bg.place(x=0,y=0,relwidth=1,relheight=1)

        # 顶部：最近未来倒计时（可选）
        if self.data.get("minimal_show_future", True):
            self.minimal_info = tk.Label(self.minimal_win, text="", font=("Segoe UI", 10), fg="#333", bg="#ffffff")
            self.minimal_info.pack(anchor=tk.NW, padx=8, pady=(6,0))
            self._update_minimal_nearest_future()

        # 中部：时间
        self.minimal_label = tk.Label(self.minimal_win, text=self.timer_label.cget("text"),
                                      font=("Segoe UI", self._auto_font_minimal(mh), "bold"), fg=self.data.get("time_color", "#000000"), bg="#ffffff")
        self.minimal_label.pack(expand=True, fill=tk.BOTH)

        # 底部区域：便签
        bottom = tk.Frame(self.minimal_win, bg="#ffffff")
        bottom.pack(fill=tk.X, padx=8, pady=6)


        if self.data.get("minimal_show_notes", True):
            nbox = tk.Frame(bottom, bg="#ffffff"); nbox.pack(side=tk.RIGHT, fill=tk.X, expand=True)
            self.minimal_notes = tk.Text(nbox, height=2, wrap=tk.WORD, bg="#fffffe")
            self.minimal_notes.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.minimal_notes.insert("1.0", self.data.get("minimal_notes_memory",""))
            sb = ttk.Scrollbar(nbox, command=self.minimal_notes.yview); sb.pack(side=tk.RIGHT, fill=tk.Y)
            self.minimal_notes.configure(yscrollcommand=sb.set)
            # 保存按钮：写入文件（若设置），写入后**清空输入框**，但应用内内存不清空
            ttk.Button(bottom, text="保存到文件", command=self._save_notes_to_file).pack(side=tk.RIGHT, padx=8)

        
            # 右侧浮动保存按钮
            try:
                self._btn_min_save = ttk.Button(self.minimal_win, text="保存", command=self._save_notes_to_file)
                self._btn_min_save.place(relx=1.0, rely=0.5, anchor="e", x=-6,y=100)
            except Exception:
                pass
# 事件：双击关闭、拖动顺滑、Ctrl滚轮缩放、右下角图形化拖拽（Sizegrip）
        self.minimal_win.bind("<Double-1>", lambda e: self._close_minimal())
        self.minimal_win.bind("<Button-1>", self._start_drag)
        self.minimal_win.bind("<B1-Motion>", self._on_drag_smooth)
        self.minimal_win.bind("<ButtonRelease-1>", self._save_minimal_pos)
        self.minimal_win.bind("<ButtonRelease-1>", lambda e: self._recalc_font_after_move())
        self.minimal_win.bind("<Control-MouseWheel>", self._ctrl_wheel_resize_min)
        self.sizegrip = ttk.Sizegrip(self.minimal_win); self.sizegrip.place(relx=1.0, rely=1.0, anchor="se")
        self.minimal_win.bind("<Configure>", self._on_minimal_configure)

        # 初次壁纸绘制
        self._draw_min_wallpaper(force=True)

    def _close_minimal(self):
        if self.minimal_win:
            try: self._save_minimal_pos()
            except Exception: pass
            self.minimal_win.destroy()
        self.minimal_win=None; self.minimal_label=None; self.minimal_info=None; self.minimal_bg=None; self.minimal_notes=None

    def _update_minimal_nearest_future(self):
        if self.minimal_info is None: return
        today = datetime.now().date()
        events = []
        for ev in self.data.get("future_events", []):
            try:
                d = datetime.strptime(ev.get("date",""), "%Y-%m-%d").date()
                events.append((d, ev))
            except Exception:
                continue
        upcoming = sorted([(d,ev) for d,ev in events if d >= today], key=lambda x: x[0])
        if not upcoming:
            self.minimal_info.config(text="")
            return
        pref = self.data.get("minimal_future_choice", "nearest")
        chosen = None
        if pref not in (None, "", "nearest"):
            for d, ev in upcoming:
                if ev.get("title") == pref:
                    chosen = (d, ev); break
        if not chosen:
            chosen = upcoming[0]
        d, ev = chosen
        text = f"{ev.get('title', '未来事件')} · " + fmt_future_delta(d, self.data.get("future_unit","混合"))
        self.minimal_info.config(text=text)

    def _start_drag(self, e): self._drag_off = (e.x, e.y)
    def _on_drag_smooth(self, e):
        if self.minimal_win is None: return
        nx = self.minimal_win.winfo_x() + (e.x - self._drag_off[0])
        ny = self.minimal_win.winfo_y() + (e.y - self._drag_off[1])
        self.minimal_win.geometry(f"+{nx}+{ny}")

    def _save_minimal_pos(self, _=None):
        if self.minimal_win is None: return
        self.data["minimal_pos"] = [self.minimal_win.winfo_x(), self.minimal_win.winfo_y()]; save_data(self.data)

    
        try:
            fs = self._auto_font_minimal_by_wh(self.minimal_win.winfo_width(), self.minimal_win.winfo_height(), self.minimal_label.cget("text"))
            if self.minimal_label:
                self.minimal_label.configure(font=("Segoe UI", fs, "bold"))
        except Exception:
            pass
# 图形化/滚轮缩放：调整窗口并自适应字号
    def _ctrl_wheel_resize_min(self, e):
        step = 20 if e.delta>0 else -20
        mw, mh = self.data.get("minimal_size", [560,260])
        mw = max(280, mw + step)
        mh = max(160, mh + int(step*0.5))
        self.data["minimal_size"] = [mw, mh]; save_data(self.data)
        self.minimal_win.geometry(f"{mw}x{mh}+{self.minimal_win.winfo_x()}+{self.minimal_win.winfo_y()}")

    def _on_minimal_configure(self, e):

# 防抖：仅在高度变化时调整字号，避免拖动位置导致字体颤动
        if not hasattr(self, "_last_min_h"): self._last_min_h = 0
        if e.height == self._last_min_h:
            pass
        else:
            self._last_min_h = e.height
            if self.minimal_label:
                fs = self._auto_font_minimal_by_wh(e.width, e.height, self.minimal_label.cget("text"))
                self.minimal_label.configure(font=("Segoe UI", fs, "bold"))

                # 背景壁纸节流重绘
                self._draw_min_wallpaper()

    def _auto_font_minimal(self, h):
        base = int(self.data.get("minimal_font_base", 72))
        return max(24, min(200, int(h*0.45)))

    def _draw_min_wallpaper(self, force=False):
        if self.minimal_bg is None or Image is None or ImageTk is None: return
        path = self._pick_min()
        w = max(1, self.minimal_win.winfo_width()); h = max(1, self.minimal_win.winfo_height())
        if not force and (w,h) == self._last_min_wallpaper_size:
            return
        self._last_min_wallpaper_size = (w,h)
        # 采样底色
        if not path:
            self.minimal_bg.configure(bg="#ffffff"); self.minimal_bg.delete("bg"); return
        avg = avg_color_hex(path, data=self.data)
        self.minimal_bg.configure(bg=avg); self.minimal_bg.delete("bg")
        if self.data.get("ui_tint_dynamic", True):
            self._apply_tint(avg)
        try:
            fit_pct = int(self.data.get("wallpaper_min_fit_pct", 92))
            short = min(w, h) * max(10, min(fit_pct, 100)) // 100
            with Image.open(path) as im:
                im = im.convert("RGB")
                im = ImageOps.contain(im, (short, short))
                self._min_bg_img = ImageTk.PhotoImage(im)
            cx, cy = w//2, h//2
            align = (self.data.get("wallpaper_min_align") or "center").lower()
            if "top" in align: cy = im.height//2 + 20
            elif "bottom" in align: cy = h - im.height//2 - 20
            self.minimal_bg.create_image(cx, cy, image=self._min_bg_img, tags=("bg",))
        except Exception:
            pass

    # ----- Music -----
    def _choose_music_dir(self):
        d = filedialog.askdirectory(title="选择音乐文件夹")
        if not d: return
        self.data["music_dir"] = d; save_data(self.data)

    def _toggle_music(self):
        if self._music_thr and self._music_thr.is_alive():
            if self._music_pause.is_set():
                self._music_pause.clear(); messagebox.showinfo("音乐", "继续播放")
            else:
                self._music_pause.set(); messagebox.showinfo("音乐", "暂停(当前曲目结束后生效)")
            return
        self._music_stop.clear(); self._music_pause.clear()
        self._music_thr = threading.Thread(target=self._music_loop, daemon=True); self._music_thr.start()

    def _next_music(self):
        self._music_stop.set(); time.sleep(0.2)
        self._music_stop.clear(); self._music_thr = threading.Thread(target=self._music_loop, daemon=True); self._music_thr.start()

    def _music_loop(self):
        d = self.data.get("music_dir"); tracks = []
        try:
            for fn in os.listdir(d or ""):
                if os.path.splitext(fn)[1].lower() in AUDIO_EXTS:
                    tracks.append(os.path.join(d, fn))
        except Exception: pass
        if self.data.get("music_shuffle", True): random.shuffle(tracks)
        for p in tracks:
            if self._music_stop.is_set(): break
            try:
                if winsound and p.lower().endswith(".wav"):
                    winsound.PlaySound(p, winsound.SND_FILENAME)
                elif playsound:
                    playsound(p)
                else:
                    for _ in range(2): self.bell(); time.sleep(0.12)
            except Exception:
                continue
            while self._music_pause.is_set() and not self._music_stop.is_set():
                time.sleep(0.2)

    # ----- notes save -----
    def _save_notes_to_file(self):
        if self.minimal_notes is None: return
        txt = self.minimal_notes.get("1.0", tk.END).strip()
        self.data["minimal_notes_memory"] = txt
        save_data(self.data)
        p = self.data.get("notes_save_path")
        if p:
            try:
                with open(p, "a", encoding="utf-8") as f:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{ts}]\n{txt}\n\n")
                # 保存后清空输入框（保留内存草稿，可在设置页切换开关时仍可加载）
                self.minimal_notes.delete("1.0", tk.END)
            except Exception as e:
                messagebox.showerror("便签","写入失败："+str(e))
        else:
            messagebox.showwarning("便签","未设置保存文件（设置→仅时间→便签与路径）")

    # ----- Common -----
    def _export_sessions(self):
        path = filedialog.asksaveasfilename(title="导出JSON", defaultextension=".json", filetypes=[("JSON","*.json")])
        if not path: return
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"sessions": self.data.get("sessions", []), "tasks": self.data.get("tasks", {}),
                       "future_events": self.data.get("future_events", [])}, f, ensure_ascii=False, indent=2)
        messagebox.showinfo("完成", f"已导出到 {path}")

    def _prompt_text(self, title, tip):
        w = tk.Toplevel(self); w.title(title)
        tk.Label(w, text=tip).pack(padx=10, pady=8)
        v = tk.StringVar(); e = ttk.Entry(w, textvariable=v, width=28); e.pack(padx=10); e.focus_set()
        res = {"ok": False}
        ttk.Button(w, text="确定", command=lambda: (res.update(ok=True), w.destroy())).pack(pady=8)
        w.grab_set(); w.wait_window(); return v.get().strip() if res["ok"] else None

    def _toggle_topmost(self):
        v = self.topmost_var.get(); self.attributes("-topmost", v); self.data["always_on_top"] = v; save_data(self.data)
    def _toggle_beep(self):
        self.data["beep"] = self.beep_var.get(); save_data(self.data)

# ---- entry ----
    def _auto_font_minimal_by_wh(self, w, h, text):
        """根据宽高与字符数估算字号，避免卡在最大值。"""
        n = max(1, len(text or "00:00:00"))
        by_h = h * 0.45
        by_w = (w * 0.80) / n
        size = int(min(by_h, by_w))
        return max(24, min(280, size))

    def _recalc_font_after_move(self):
        if getattr(self, "minimal_win", None) is None or getattr(self, "minimal_label", None) is None:
            return
        w = max(1, self.minimal_win.winfo_width())
        h = max(1, self.minimal_win.winfo_height())
        fs = self._auto_font_minimal_by_wh(w, h, self.minimal_label.cget("text"))
        self.minimal_label.configure(font=("Segoe UI", fs, "bold"))
        try:
            print(f"[Minimal] font size after move -> {fs}")
        except Exception:
            pass

if __name__ == "__main__":
    app = FocusTimerApp()
    app.mainloop()