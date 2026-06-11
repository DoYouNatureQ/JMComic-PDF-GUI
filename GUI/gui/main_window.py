import os
import json
import base64
import threading
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
from tkinter import messagebox

from core.client import ComicClient
from core.auth import Authenticator
from core.parser import MangaParser
from core.downloader import Downloader
from core.pdf_maker import PdfMaker
from config import (BASE_DIR, DOWNLOAD_DIR, FAVORITES_CACHE,
                    load_settings, save_settings, encode_pwd, decode_pwd)

import re as _re
def _mask_ip(text: str) -> str:
    if not isinstance(text, str):
        return text
    ipv4 = r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
    ipv6 = r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b'
    text = _re.sub(ipv4, '[IP_REDACTED]', text)
    text = _re.sub(ipv6, '[IP_REDACTED]', text)
    return text

WINDOW_STATE_FILE = os.path.join(BASE_DIR, "window_state.json")

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

PINK = "#FB7299"
PINK_HOVER = "#FC8BAA"
PINK_LIGHT = "#FFF0F4"
BLUE = "#00A1D6"
BLUE_HOVER = "#00B5E5"
BLUE_LIGHT = "#E6F7FC"
BG_WHITE = "#FFFFFF"
BG_GRAY = "#F6F7F8"
BG_CARD = "#FFFFFF"
BORDER = "#E3E5E7"
TEXT_DARK = "#18191C"
TEXT_GRAY = "#9499A0"
TEXT_LIGHT = "#61666D"
SUCCESS = "#00AEEC"
WARN = "#FFB027"
DANGER = "#ED5B5B"
FONT_FAMILY = "Microsoft YaHei UI"


class CanvasMangaList(ctk.CTkFrame):
    """高性能虚拟化漫画列表 - 使用Canvas直接绘制文本，零Widget开销"""
    ITEM_HEIGHT = 52
    _REDRAW_DELAY = 16
    _RESIZE_DELAY = 200

    def __init__(self, master, on_select=None, **kw):
        super().__init__(master, fg_color=BG_GRAY, corner_radius=8, **kw)
        self._on_select_cb = on_select
        self.items = []
        self.selected_index = -1
        self._redraw_pending = None
        self._resize_pending = None
        self._visible_indices = set()

        self.canvas = tk.Canvas(
            self, highlightthickness=0, bg=BG_GRAY, bd=0,
            yscrollincrement=30,
        )
        self.canvas.pack(side="left", fill="both", expand=True)

        self.scrollbar = tk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview,
            bg=BG_GRAY, troughcolor=BG_GRAY,
            activebackground=PINK, width=6,
        )
        self.canvas.configure(yscrollcommand=self._on_scroll_cmd)

        self.canvas.bind("<Configure>", self._on_configure)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-1>", self._on_click)

    def _on_scroll_cmd(self, *args):
        self.scrollbar.set(*args)

    def set_items(self, items):
        self.items = list(items)
        self.selected_index = -1
        self._visible_indices.clear()
        self.canvas.yview_moveto(0)
        self._update_scroll()
        self._redraw()

    def clear(self):
        self.items = []
        self.selected_index = -1
        self._visible_indices.clear()
        self.canvas.yview_moveto(0)
        self.canvas.delete("all")
        self.scrollbar.pack_forget()
        self.canvas.configure(scrollregion=(0, 0, 0, 0))

    def select_by_id(self, item_id):
        for i, item in enumerate(self.items):
            if item["id"] == item_id:
                self.selected_index = i
                self._redraw()
                return

    def _on_configure(self, event):
        if self._resize_pending:
            self.after_cancel(self._resize_pending)
        self._resize_pending = self.after(self._RESIZE_DELAY, self._do_configure)

    def _do_configure(self):
        self._resize_pending = None
        w = self.canvas.winfo_width() or 300
        h = self.canvas.winfo_height() or 1
        if w == getattr(self, "_last_canvas_w", 0) and h == getattr(self, "_last_canvas_h", 0):
            return
        if not self.winfo_viewable():
            return
        self._last_canvas_w = w
        self._last_canvas_h = h
        self._update_scroll()
        self._redraw()

    def _update_scroll(self):
        total_h = max(len(self.items) * self.ITEM_HEIGHT + 8, 1)
        w = self.canvas.winfo_width() or 300
        self.canvas.configure(scrollregion=(0, 0, w, total_h))
        canvas_h = self.canvas.winfo_height() or 1
        if total_h > canvas_h:
            self.scrollbar.pack(side="right", fill="y")
        else:
            self.scrollbar.pack_forget()

    def _visible_range(self):
        if not self.items:
            return 0, 0
        y0 = int(self.canvas.canvasy(0))
        h = max(self.canvas.winfo_height(), 1)
        first = max(0, y0 // self.ITEM_HEIGHT)
        last = min(len(self.items), (y0 + h) // self.ITEM_HEIGHT + 2)
        return first, last

    def _redraw(self):
        if not self.items:
            self.canvas.delete("all")
            self._visible_indices.clear()
            return
        first, last = self._visible_range()
        w = max(self.canvas.winfo_width(), 300)
        new_visible = set(range(first, min(last, len(self.items))))

        for i in sorted(new_visible):
            if i >= len(self.items):
                break
            item = self.items[i]
            y = i * self.ITEM_HEIGHT + 4

            bg = PINK_LIGHT if i == self.selected_index else ""

            title = (item.get("title") or f"#{item['id']}")[:40]
            meta = f"#{item['id']}"
            author = item.get("author", "")
            if author:
                meta += f"  ·  {author[:16]}"
            ch = item.get("chapter_count", 0)
            if ch:
                meta += f"  ·  {ch}话"

            if i in self._visible_indices:
                rect_items = self.canvas.find_withtag(f"r{i}")
                if rect_items:
                    self.canvas.coords(rect_items[0], 4, y, w - 4, y + self.ITEM_HEIGHT - 4)
                    self.canvas.itemconfig(rect_items[0], fill=bg)
                text_items = self.canvas.find_withtag(f"t{i}")
                if len(text_items) >= 2:
                    self.canvas.coords(text_items[0], 14, y + 8)
                    self.canvas.itemconfig(text_items[0], text=title)
                    self.canvas.coords(text_items[1], 14, y + 30)
                    self.canvas.itemconfig(text_items[1], text=meta)
                elif len(text_items) == 1:
                    self.canvas.coords(text_items[0], 14, y + 8)
                    self.canvas.itemconfig(text_items[0], text=title)
            else:
                self.canvas.create_rectangle(
                    4, y, w - 4, y + self.ITEM_HEIGHT - 4,
                    fill=bg, outline="", tags=("item", f"r{i}"),
                )
                self.canvas.create_text(
                    14, y + 8, text=title, anchor="nw",
                    font=(FONT_FAMILY, 13, "bold"), fill=TEXT_DARK,
                    tags=("item", f"t{i}"),
                )
                self.canvas.create_text(
                    14, y + 30, text=meta, anchor="nw",
                    font=(FONT_FAMILY, 10), fill=TEXT_GRAY,
                    tags=("item", f"t{i}"),
                )

        for i in self._visible_indices - new_visible:
            self.canvas.delete(f"r{i}", f"t{i}")

        self._visible_indices = new_visible

    def _on_click(self, event):
        if not self.items:
            return
        canvas_y = self.canvas.canvasy(event.y)
        idx = int(canvas_y // self.ITEM_HEIGHT)
        if 0 <= idx < len(self.items):
            self.selected_index = idx
            self._redraw()
            if self._on_select_cb:
                item = self.items[idx]
                self._on_select_cb(item["id"], item)

    def _on_mousewheel(self, event):
        total_h = len(self.items) * self.ITEM_HEIGHT + 8
        if total_h <= self.canvas.winfo_height():
            return
        delta = -1 * (event.delta // 120)
        self.canvas.yview_scroll(delta, "units")
        if self._redraw_pending:
            self.after_cancel(self._redraw_pending)
        self._redraw_pending = self.after(self._REDRAW_DELAY, self._do_redraw_from_scroll)

    def _do_redraw_from_scroll(self):
        self._redraw_pending = None
        self._redraw()


class JMComicApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("JMComic-PDF")
        self.geometry("1180x760")
        self.minsize(800, 540)
        self.configure(fg_color=BG_GRAY)

        self.settings = load_settings()
        self.download_dir = self.settings.get("download_dir", DOWNLOAD_DIR)
        os.makedirs(self.download_dir, exist_ok=True)

        self._load_window_state()

        self._init_variables()
        self._build_ui()

        saved_user = self.settings.get("username", "")
        saved_pwd = decode_pwd(self.settings.get("password", ""))
        if saved_user:
            self.username_var.set(saved_user)
        if saved_pwd:
            self.password_var.set(saved_pwd)

        self.client = ComicClient()
        self.auth = Authenticator(self.client)
        self.parser = MangaParser(self.client)
        self.downloader = Downloader(self.client)
        self.pdf_maker = PdfMaker()

        self.downloader.on_progress(self._on_download_progress)
        self.downloader.on_status(self._on_status_message)

        self.after(100, lambda: self._log(f"网络引擎: {ComicClient.ENGINE}, 代理: {_mask_ip(self.client.proxy) if self.client.proxy else '直连'}"))
        self.after(200, self._try_auto_login)
        self.after(300, self._apply_responsive_layout)
        self.bind("<Configure>", self._on_window_configure)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_window_state(self):
        try:
            with open(WINDOW_STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            geo = state.get("geometry", "")
            if geo:
                self.geometry(geo)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _on_close(self):
        try:
            with open(WINDOW_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"geometry": self.wm_geometry()}, f)
        except OSError:
            pass
        self.destroy()

    def _on_window_configure(self, event=None):
        if getattr(self, "_resize_pending", False):
            return
        self._resize_pending = True
        self.after(80, self._do_window_configure)

    def _do_window_configure(self):
        self._resize_pending = False
        w = self.winfo_width()
        if w < 200:
            return
        if w == getattr(self, "_last_win_width", 0):
            return
        self._last_win_width = w
        left_w = max(220, int(w * 0.23))
        info_w = max(220, int((w - 40 - left_w) * 0.32))
        if hasattr(self, "left_panel_card"):
            self.left_panel_card.configure(width=left_w)
        if hasattr(self, "info_card"):
            self.info_card.configure(width=info_w)

    def _apply_responsive_layout(self):
        self._do_window_configure()

    def _init_variables(self):
        self.username_var = ctk.StringVar()
        self.password_var = ctk.StringVar()
        self.search_var = ctk.StringVar()
        self.favorites_data = []
        self.chapter_data = []
        self.manga_check_vars = {}
        self.selected_manga_id = None
        self.chapter_check_vars = {}
        self.auto_pdf_var = ctk.BooleanVar(value=False)
        self.download_running = False
        self.download_thread = None
        self._refreshing = False
        self._searching = False
        # Progress debounce
        self._progress_dirty = False
        self._pending_ch_progress = 0.0
        self._pending_detail = ""
        # Chapter batch render
        self._chapter_render_idx = 0
        self._chapter_render_gen = 0
        self._chapter_batch_size = 30
        self.manga_detail = {}
        # Log batch
        self._log_queue = []
        self._log_pending = False

    def _bind_cursor_visibility(self, entry, text_var):
        def _on_var_change(*_):
            entry.configure(insertwidth=2 if text_var.get() else 0)
        def _on_focus_in(_):
            entry.configure(insertwidth=2 if text_var.get() else 0)
        def _on_focus_out(_):
            entry.configure(insertwidth=0)
        text_var.trace_add("write", _on_var_change)
        entry.bind("<FocusIn>", _on_focus_in)
        entry.bind("<FocusOut>", _on_focus_out)
        entry.configure(insertwidth=0)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_navbar()
        self._build_content()
        self._build_footer()

    def _build_navbar(self):
        navbar = ctk.CTkFrame(self, fg_color=PINK, corner_radius=0, height=52)
        navbar.grid(row=0, column=0, sticky="ew")
        navbar.grid_columnconfigure(0, weight=0)
        navbar.grid_columnconfigure(1, weight=0)
        navbar.grid_columnconfigure(2, weight=1)
        navbar.grid_columnconfigure(3, weight=0)
        navbar.grid_columnconfigure(4, weight=1)
        navbar.grid_propagate(False)

        ctk.CTkLabel(
            navbar, text="📚 JMComic-PDF",
            font=ctk.CTkFont(size=20, weight="bold", family=FONT_FAMILY),
            text_color="white",
        ).grid(row=0, column=0, padx=(20, 8), pady=10)

        ctk.CTkLabel(
            navbar, text="v2.0",
            font=ctk.CTkFont(size=11, family=FONT_FAMILY),
            text_color="white",
        ).grid(row=0, column=1, sticky="w", pady=10)

        search_frame = ctk.CTkFrame(navbar, fg_color="transparent")
        search_frame.grid(row=0, column=2, padx=10, pady=8, sticky="ew")
        search_frame.grid_columnconfigure(0, weight=1)
        search_frame.grid_columnconfigure(1, weight=0)

        self.entry_search = ctk.CTkEntry(
            search_frame,
            placeholder_text="搜索漫画...",
            height=30,
            textvariable=self.search_var,
            fg_color="white",
            border_width=0,
            corner_radius=15,
            font=ctk.CTkFont(size=13, family=FONT_FAMILY),
        )
        self.entry_search.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.entry_search.bind("<Return>", lambda e: self._do_search())
        self._bind_cursor_visibility(self.entry_search, self.search_var)

        self.btn_search = ctk.CTkButton(
            search_frame, text="搜索",
            width=64, height=30,
            command=self._do_search,
            fg_color="white", hover_color=PINK_LIGHT,
            text_color=PINK,
            corner_radius=15,
            font=ctk.CTkFont(size=13, weight="bold", family=FONT_FAMILY),
        )
        self.btn_search.grid(row=0, column=1)

        path_frame = ctk.CTkFrame(navbar, fg_color="transparent")
        path_frame.grid(row=0, column=3, padx=(6, 10), sticky="e")

        self.btn_choose_path = ctk.CTkButton(
            path_frame, text="📁", width=30, height=30,
            command=self._choose_download_path,
            fg_color="white", hover_color=PINK_LIGHT,
            text_color=PINK,
            corner_radius=15,
            font=ctk.CTkFont(size=14),
        )
        self.btn_choose_path.pack(side="left", padx=(0, 4))

        display_path = self.download_dir
        if len(display_path) > 28:
            display_path = "..." + display_path[-25:]
        self.lbl_path = ctk.CTkLabel(
            path_frame, text=display_path,
            font=ctk.CTkFont(size=10, family=FONT_FAMILY),
            text_color="white",
        )
        self.lbl_path.pack(side="left")

        login_frame = ctk.CTkFrame(navbar, fg_color="transparent")
        login_frame.grid(row=0, column=4, padx=(10, 20), sticky="ew")
        login_frame.grid_columnconfigure(0, weight=0)
        login_frame.grid_columnconfigure(1, weight=1)
        login_frame.grid_columnconfigure(2, weight=0)
        login_frame.grid_columnconfigure(3, weight=1)
        login_frame.grid_columnconfigure(4, weight=0)
        login_frame.grid_columnconfigure(5, weight=0)

        ctk.CTkLabel(
            login_frame, text="账号",
            font=ctk.CTkFont(size=12, weight="bold", family=FONT_FAMILY),
            text_color=TEXT_DARK,
        ).grid(row=0, column=0, padx=(0, 4))

        self.entry_user = ctk.CTkEntry(
            login_frame, placeholder_text="输入用户名",
            height=30,
            textvariable=self.username_var,
            fg_color="white", border_width=0,
            corner_radius=15,
            font=ctk.CTkFont(size=13, family=FONT_FAMILY),
        )
        self.entry_user.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self._bind_cursor_visibility(self.entry_user, self.username_var)

        ctk.CTkLabel(
            login_frame, text="密码",
            font=ctk.CTkFont(size=12, weight="bold", family=FONT_FAMILY),
            text_color=TEXT_DARK,
        ).grid(row=0, column=2, padx=(0, 4))

        self.entry_pass = ctk.CTkEntry(
            login_frame, placeholder_text="输入密码",
            height=30,
            show="●",
            textvariable=self.password_var,
            fg_color="white", border_width=0,
            corner_radius=15,
            font=ctk.CTkFont(size=13, family=FONT_FAMILY),
        )
        self.entry_pass.grid(row=0, column=3, sticky="ew", padx=(0, 6))
        self.entry_pass.bind("<Return>", lambda e: self._do_login())
        self._bind_cursor_visibility(self.entry_pass, self.password_var)

        self.btn_login = ctk.CTkButton(
            login_frame, text="登录",
            width=64, height=30,
            command=self._do_login,
            fg_color="white", hover_color=PINK_LIGHT,
            text_color=PINK,
            corner_radius=15,
            font=ctk.CTkFont(size=13, weight="bold", family=FONT_FAMILY),
        )
        self.btn_login.grid(row=0, column=4, padx=(0, 4))

        self.lbl_status = ctk.CTkLabel(
            login_frame, text="未登录",
            font=ctk.CTkFont(size=12, weight="bold", family=FONT_FAMILY),
            text_color=TEXT_DARK,
        )
        self.lbl_status.grid(row=0, column=5)

    def _build_content(self):
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew", padx=14, pady=(10, 4))
        content.grid_columnconfigure(0, weight=0)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)
        self._build_left_panel(content)
        self._build_right_panel(content)

    def _build_left_panel(self, parent):
        self.left_panel_card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=12)
        self.left_panel_card.grid(row=0, column=0, sticky="ns", padx=(0, 6))
        self.left_panel_card.grid_propagate(False)
        self.left_panel_card.grid_columnconfigure(0, weight=1)
        self.left_panel_card.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self.left_panel_card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header, text="📋 漫画列表",
            font=ctk.CTkFont(size=16, weight="bold", family=FONT_FAMILY),
            text_color=TEXT_DARK,
        ).grid(row=0, column=0)

        actions = ctk.CTkFrame(self.left_panel_card, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))

        self.lbl_manga_hint = ctk.CTkLabel(
            actions, text="👆 点击漫画名查看章节",
            font=ctk.CTkFont(size=11, family=FONT_FAMILY),
            text_color=TEXT_GRAY,
        )
        self.lbl_manga_hint.pack(side="left")

        self.btn_refresh = ctk.CTkButton(
            actions, text="刷 新 收 藏", width=90, height=26,
            font=ctk.CTkFont(size=12, family=FONT_FAMILY),
            fg_color=PINK_LIGHT, hover_color=PINK,
            text_color=PINK, command=self._load_favorites,
        )
        self.btn_refresh.pack(side="right")

        self.manga_list = CanvasMangaList(
            self.left_panel_card, on_select=self._on_manga_select,
        )
        self.manga_list.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 12))

    def _build_right_panel(self, parent):
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=12)
        card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        card.grid_columnconfigure(0, weight=0)
        card.grid_columnconfigure(1, weight=1)
        card.grid_rowconfigure(0, weight=1)

        # ---- 左侧 固定宽度: 漫画信息 ----
        info_card = ctk.CTkFrame(card, fg_color=BG_GRAY, corner_radius=8)
        info_card.grid(row=0, column=0, sticky="ns", padx=(14, 7), pady=12)
        info_card.grid_propagate(False)
        info_card.grid_columnconfigure(0, weight=1)
        self.info_card = info_card

        ctk.CTkLabel(
            info_card, text="📋 漫画信息",
            font=ctk.CTkFont(size=14, weight="bold", family=FONT_FAMILY),
            text_color=TEXT_DARK,
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 8))

        self.lbl_manga_name = ctk.CTkLabel(
            info_card, text="",
            font=ctk.CTkFont(size=13, weight="bold", family=FONT_FAMILY),
            text_color=TEXT_DARK,
            wraplength=190, justify="left",
        )
        self.lbl_manga_name.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 2))

        self.lbl_manga_id = ctk.CTkLabel(
            info_card, text="",
            font=ctk.CTkFont(size=11, family=FONT_FAMILY),
            text_color=TEXT_GRAY,
        )
        self.lbl_manga_id.grid(row=2, column=0, sticky="w", padx=12, pady=(0, 2))

        self.lbl_manga_author = ctk.CTkLabel(
            info_card, text="",
            font=ctk.CTkFont(size=11, family=FONT_FAMILY),
            text_color=TEXT_LIGHT,
        )
        self.lbl_manga_author.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            info_card, text="简介",
            font=ctk.CTkFont(size=12, weight="bold", family=FONT_FAMILY),
            text_color=TEXT_DARK,
        ).grid(row=4, column=0, sticky="w", padx=12, pady=(0, 4))

        self.lbl_manga_desc = ctk.CTkLabel(
            info_card, text="",
            font=ctk.CTkFont(size=11, family=FONT_FAMILY),
            text_color=TEXT_GRAY,
            wraplength=190, justify="left",
        )
        self.lbl_manga_desc.grid(row=5, column=0, sticky="nw", padx=12, pady=(0, 8))

        self.lbl_manga_ch_count = ctk.CTkLabel(
            info_card, text="",
            font=ctk.CTkFont(size=12, weight="bold", family=FONT_FAMILY),
            text_color=PINK,
        )
        self.lbl_manga_ch_count.grid(row=6, column=0, sticky="w", padx=12, pady=(4, 10))

        info_card.grid_rowconfigure(5, weight=1)

        # ---- 右侧 70%: 章节列表 ----
        ch_card = ctk.CTkFrame(card, fg_color="transparent")
        ch_card.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=12)
        ch_card.grid_columnconfigure(0, weight=1)
        ch_card.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(ch_card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="📖 章节列表",
            font=ctk.CTkFont(size=16, weight="bold", family=FONT_FAMILY),
            text_color=TEXT_DARK,
        ).grid(row=0, column=0, sticky="w")

        self.lbl_chapter_count = ctk.CTkLabel(
            header, text="",
            font=ctk.CTkFont(size=12, family=FONT_FAMILY),
            text_color=TEXT_GRAY,
        )
        self.lbl_chapter_count.grid(row=0, column=1, sticky="e")

        self.chapter_list_frame = ctk.CTkScrollableFrame(
            ch_card, fg_color=BG_GRAY, corner_radius=8,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BLUE,
        )
        self.chapter_list_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 6))

        ch_actions = ctk.CTkFrame(ch_card, fg_color="transparent")
        ch_actions.grid(row=2, column=0, sticky="ew", pady=(0, 4))

        ctk.CTkButton(
            ch_actions, text="全选章节", width=74, height=26,
            font=ctk.CTkFont(size=12, family=FONT_FAMILY),
            fg_color=BLUE_LIGHT, hover_color=BLUE,
            text_color=BLUE, command=self._select_all_chapters,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            ch_actions, text="取消全选", width=74, height=26,
            font=ctk.CTkFont(size=12, family=FONT_FAMILY),
            fg_color=BG_GRAY, hover_color=BORDER,
            text_color=TEXT_GRAY, command=self._deselect_all_chapters,
        ).pack(side="left", padx=(0, 4))

        self.chk_auto_pdf = ctk.CTkCheckBox(
            ch_actions, text="每章下载完自动生成PDF",
            variable=self.auto_pdf_var,
            checkbox_width=16, checkbox_height=16,
            border_color=BORDER, hover_color=BLUE,
            fg_color=BLUE,
            font=ctk.CTkFont(size=12, family=FONT_FAMILY),
        )
        self.chk_auto_pdf.pack(side="left", padx=(8, 0))

        prog_card = ctk.CTkFrame(ch_card, fg_color=BG_GRAY, corner_radius=8)
        prog_card.grid(row=3, column=0, sticky="ew", pady=(2, 4))
        prog_card.grid_columnconfigure(0, weight=1)

        self.lbl_progress_title = ctk.CTkLabel(
            prog_card, text="等待下载...",
            font=ctk.CTkFont(size=12, family=FONT_FAMILY),
            text_color=TEXT_GRAY,
        )
        self.lbl_progress_title.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 1))

        self.progress_chapter = ctk.CTkProgressBar(prog_card, height=4,
                                                    progress_color=BLUE, fg_color=BORDER)
        self.progress_chapter.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 1))
        self.progress_chapter.set(0)

        self.lbl_progress_detail = ctk.CTkLabel(
            prog_card, text="",
            font=ctk.CTkFont(size=10, family=FONT_FAMILY),
            text_color=TEXT_GRAY,
        )
        self.lbl_progress_detail.grid(row=2, column=0, sticky="w", padx=8)

        self.progress_total = ctk.CTkProgressBar(prog_card, height=4,
                                                  progress_color=PINK, fg_color=BORDER)
        self.progress_total.grid(row=3, column=0, sticky="ew", padx=8, pady=(4, 1))
        self.progress_total.set(0)

        self.lbl_total_progress = ctk.CTkLabel(
            prog_card, text="",
            font=ctk.CTkFont(size=10, family=FONT_FAMILY),
            text_color=TEXT_GRAY,
        )
        self.lbl_total_progress.grid(row=4, column=0, sticky="w", padx=8, pady=(0, 4))

        btn_frame = ctk.CTkFrame(ch_card, fg_color="transparent")
        btn_frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))

        self.btn_download_sel = ctk.CTkButton(
            btn_frame, text="⬇ 下载选中章节", height=34,
            font=ctk.CTkFont(size=12, weight="bold", family=FONT_FAMILY),
            fg_color=PINK, hover_color=PINK_HOVER,
            command=self._start_download,
        )
        self.btn_download_sel.pack(side="left", padx=(0, 4))

        self.btn_download_all = ctk.CTkButton(
            btn_frame, text="⬇⬇ 下载全部", height=34,
            font=ctk.CTkFont(size=12, weight="bold", family=FONT_FAMILY),
            fg_color=PINK_HOVER, hover_color=PINK,
            command=self._start_download_all,
        )
        self.btn_download_all.pack(side="left", padx=(0, 4))

        self.btn_stop = ctk.CTkButton(
            btn_frame, text="停止", height=34, state="disabled",
            font=ctk.CTkFont(size=13, family=FONT_FAMILY),
            fg_color=DANGER, hover_color="#E57373",
            command=self._stop_download,
        )
        self.btn_stop.pack(side="left", padx=(0, 4))

        self.btn_pdf_chapter = ctk.CTkButton(
            btn_frame, text="📄 分章节PDF", height=34,
            font=ctk.CTkFont(size=12, family=FONT_FAMILY),
            fg_color=BLUE, hover_color=BLUE_HOVER,
            command=self._make_pdf_by_chapter,
        )
        self.btn_pdf_chapter.pack(side="left", padx=(0, 4))

        self.btn_pdf_full = ctk.CTkButton(
            btn_frame, text="📕 完整版PDF", height=34,
            font=ctk.CTkFont(size=12, family=FONT_FAMILY),
            fg_color=BLUE, hover_color=BLUE_HOVER,
            command=self._make_pdf_full,
        )
        self.btn_pdf_full.pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            btn_frame, text="📁", width=34, height=34,
            font=ctk.CTkFont(size=14),
            fg_color=BG_GRAY, hover_color=BORDER,
            text_color=TEXT_GRAY,
            command=self._open_pdf_dir,
        ).pack(side="left")

    def _build_footer(self):
        card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=12)
        card.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 10))
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        log_header = ctk.CTkFrame(card, fg_color="transparent")
        log_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(8, 4))

        ctk.CTkLabel(
            log_header, text="📜 运行日志",
            font=ctk.CTkFont(size=14, weight="bold", family=FONT_FAMILY),
            text_color=TEXT_DARK,
        ).pack(side="left")

        ctk.CTkButton(
            log_header, text="清空", width=48, height=24,
            font=ctk.CTkFont(size=11, family=FONT_FAMILY),
            fg_color=BG_GRAY, hover_color=BORDER,
            text_color=TEXT_GRAY,
            command=self._clear_log,
        ).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            card,
            font=ctk.CTkFont(size=11, family="Consolas"),
            fg_color=BG_GRAY, corner_radius=8,
            border_width=0, wrap="word",
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 10))

    def _log(self, message):
        self._log_queue.append(_mask_ip(message))
        if not self._log_pending:
            self._log_pending = True
            self.after(16, self._flush_log)

    def _flush_log(self):
        self._log_pending = False
        if not self._log_queue:
            return
        self.log_box.configure(state="normal")
        for msg in self._log_queue:
            self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self._log_queue.clear()

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _choose_download_path(self):
        path = filedialog.askdirectory(title="选择下载目录", initialdir=self.download_dir)
        if not path:
            return
        self.download_dir = path
        os.makedirs(self.download_dir, exist_ok=True)
        self.settings["download_dir"] = path
        save_settings(self.settings)
        display_path = path
        if len(display_path) > 28:
            display_path = "..." + display_path[-25:]
        self.lbl_path.configure(text=display_path)
        self._log(f"下载路径已更新: {path}")

    def _try_auto_login(self):
        self._log("正在检查登录状态...")
        def worker():
            success, msg = self.auth.try_auto_login()
            self.after(0, lambda: self._on_auto_login_result(success, msg))
        threading.Thread(target=worker, daemon=True).start()

    def _on_auto_login_result(self, success, msg):
        self._log(f"[{'✓' if success else '✗'}] {msg}")
        if success:
            self._set_login_state(True)
            self._load_favorites()

    def _do_login(self):
        if self.auth.is_logged_in:
            self._do_logout()
            return
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        if not username or not password:
            messagebox.showinfo("提示", "请输入用户名和密码")
            return
        self.btn_login.configure(state="disabled", text="登录中...")
        self._log("正在登录...")

        def worker():
            success, msg = self.auth.login(username, password)
            self.after(0, lambda: self._on_login_result(success, msg))
        threading.Thread(target=worker, daemon=True).start()

    def _on_login_result(self, success, msg):
        self.btn_login.configure(state="normal")
        self._log(f"[{'✓' if success else '✗'}] {msg}")
        if success:
            username = self.username_var.get().strip()
            password = self.password_var.get().strip()
            self.settings["username"] = username
            self.settings["password"] = encode_pwd(password) if password else ""
            save_settings(self.settings)
            self._set_login_state(True)
            self._load_favorites()
        else:
            self.btn_login.configure(text="登录")
            messagebox.showerror("登录失败", msg)

    def _do_logout(self):
        self.auth.logout()
        self._set_login_state(False)
        self._log("已退出登录")
        self._clear_lists()

    def _set_login_state(self, logged_in):
        if logged_in:
            username = self.auth.username or ""
            self.lbl_status.configure(text=f"已登录: {username}")
            self.btn_login.configure(state="normal", text="退出登录")
        else:
            self.lbl_status.configure(text="未登录")
            self.btn_login.configure(state="normal", text="登录")

    def _save_favorites_cache(self, favs):
        valid = [item for item in favs if item.get("title", "").strip()]
        try:
            with open(FAVORITES_CACHE, "w", encoding="utf-8") as f:
                json.dump(valid, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _ensure_favorites_cache(self):
        if not os.path.exists(FAVORITES_CACHE):
            try:
                with open(FAVORITES_CACHE, "w", encoding="utf-8") as f:
                    json.dump([], f)
            except OSError:
                pass

    def _load_favorites_cache(self):
        self._ensure_favorites_cache()
        try:
            with open(FAVORITES_CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [item for item in data if item.get("title", "").strip()]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _load_favorites(self):
        if not self.auth.is_logged_in:
            messagebox.showinfo("提示", "请先登录")
            return
        if self._refreshing:
            self._log("收藏列表正在刷新中，请稍候...")
            return

        self._refreshing = True
        self.btn_refresh.configure(state="disabled", text="加载中...")
        self.btn_search.configure(state="disabled")
        username = self.auth.username or ""
        self._log("正在加载收藏列表...")
        if username:
            self._log(f"收藏地址: https://18comic.vip/user/***/favorite/albums")
        else:
            self._log("收藏地址: https://18comic.vip/user/favorite")

        self._clear_manga_list()
        self._log("正在从服务器获取最新收藏数据...")

        def worker():
            try:
                if not self.auth.verify_session_valid():
                    self.after(0, lambda: self._log("会话已过期，请重新登录后再刷新收藏列表"))
                    self.after(0, lambda: self._on_favorites_loaded([]))
                    return
                favs = self.parser.parse_all_favorites(username=self.auth.username or "")
                if not favs:
                    self.after(0, lambda: threading.Thread(target=self._diagnose_favorites_failure, daemon=True).start())
                self.after(0, lambda: self._on_favorites_loaded(favs))
            except Exception as e:
                self.after(0, lambda: self._log(f"加载失败: {e}"))
                self.after(0, lambda: self._on_favorites_loaded([]))
        threading.Thread(target=worker, daemon=True).start()

    def _diagnose_favorites_failure(self):
        try:
            import re, os, tempfile
            username = self.auth.username or ""
            if username:
                urls = [
                    f"https://18comic.vip/user/{username}/favorite/albums",
                    f"https://18comic.vip/user/favorite/albums",
                    f"https://18comic.vip/user/favorite",
                ]
            else:
                urls = [
                    "https://18comic.vip/user/favorite",
                ]
            for u in urls:
                resp = self.client.get(u)
                lines = []
                lines.append(f"[诊断] 请求URL: {u}")
                lines.append(f"[诊断] HTTP状态: {resp.status_code}, 跳转后URL: {resp.url}")
                lines.append(f"[诊断] 页面长度: {len(resp.text)} 字符")
                title_m = re.search(r'<title>(.*?)</title>', resp.text, re.I | re.S)
                if title_m:
                    lines.append(f"[诊断] 页面标题: {title_m.group(1).strip()}")
                link_count = len(re.findall(r'href=["\'][^"\']*/(album|photo|comic|manga|book|detail)/\d+[^"\']*["\']', resp.text, re.I))
                lines.append(f"[诊断] 找到 {link_count} 个漫画链接")
                is_login = "login" in resp.text[:3000].lower() or "login" in resp.url.lower()
                if is_login or link_count == 0:
                    lines.append("[诊断] 页面含 'login': " + str('login' in resp.text[:3000].lower()))
                    lines.append("[诊断] 页面含 '收藏': " + str('收藏' in resp.text[:5000]))
                    is_member_page = 'member' in resp.text[:3000] or 'album' in resp.text[:3000].lower()
                    lines.append(f"[诊断] 页面含 member/album: {is_member_page}")
                    body_preview = re.sub(r'<[^>]+>', ' ', resp.text[:3000])
                    body_preview = re.sub(r'\s+', ' ', body_preview).strip()[:300]
                    lines.append(f"[诊断] 正文预览: {body_preview}")
                    dump_path = os.path.join(tempfile.gettempdir(), f"jmpdf_debug_fav_{urls.index(u)}.html")
                    try:
                        with open(dump_path, "w", encoding="utf-8") as f:
                            f.write(resp.text[:80000])
                        lines.append(f"[诊断] 调试文件: {dump_path}")
                    except Exception:
                        pass
                for line in lines:
                    self.after(0, lambda msg=line: self._log(msg))
                if link_count > 0 and not is_login:
                    self.after(0, lambda url=u: self._log(f"[诊断] URL {url} 似乎有效（找到 {link_count} 个链接），但解析器未提取到条目，请检查解析器选择器"))
                    break
                elif link_count > 0:
                    self.after(0, lambda url=u: self._log(f"[诊断] URL {url} 找到链接但页面可能是登录页"))
        except Exception as e:
            self.after(0, lambda: self._log(f"[诊断] 失败: {e}"))

    def _on_favorites_loaded(self, favs):
        self._refreshing = False
        self.btn_refresh.configure(state="normal", text="刷 新 收 藏")
        self.btn_search.configure(state="normal")
        if not favs:
            cached = self._load_favorites_cache()
            if cached:
                self.manga_list.set_items(cached)
                self.favorites_data = cached
                self._log("刷新失败，已恢复为本地缓存数据")
                self._log("提示: 请尝试重新登录。如问题持续，检查 %TEMP%/jmpdf_debug_fav_*.html")
                messagebox.showwarning("刷新失败", "无法从服务器获取最新收藏数据，已恢复为本地缓存。\n请尝试重新登录后再试。")
            else:
                self._log("收藏列表为空（请确认已登录且已收藏漫画）")
                self._log("提示: 诊断信息已写入上方日志。调试文件: %TEMP%/jmpdf_debug_fav_*.html")
                messagebox.showerror("刷新失败", "无法获取收藏列表。\n请确认已登录且已收藏漫画。")
            return
        self._save_favorites_cache(favs)
        self._clear_manga_list()
        self.favorites_data = favs
        self.manga_list.set_items(favs)
        self._log(f"已从服务器同步 {len(favs)} 部收藏漫画")

    def _do_search(self):
        keyword = self.search_var.get().strip()
        if not keyword:
            return
        if self._searching:
            self._log("搜索正在进行中，请稍候...")
            return
        if keyword.isdigit():
            self._search_by_id(keyword)
            return
        self._searching = True
        self.btn_search.configure(state="disabled", text="搜索中...")
        self.btn_refresh.configure(state="disabled")
        self._log(f"搜索: {keyword}")
        self._clear_manga_list()

        def worker():
            try:
                results = []
                for p in range(1, 5):
                    r, has_next = self.parser.find_manga(keyword, p)
                    results.extend(r)
                    if not has_next or not r:
                        break
                self.after(0, lambda: self._on_search_results(results))
            except Exception as e:
                self.after(0, lambda: self._log(f"搜索失败: {e}"))
            finally:
                self.after(0, lambda: self._on_search_finished())
        threading.Thread(target=worker, daemon=True).start()

    def _on_search_finished(self):
        self._searching = False
        self.btn_search.configure(state="normal", text="搜索")
        self.btn_refresh.configure(state="normal")

    def _on_search_results(self, results):
        self.favorites_data = results
        self.manga_list.set_items(results)
        self._log(f"搜索到 {len(results)} 部漫画")

    def _search_by_id(self, manga_id):
        self._searching = True
        self.btn_search.configure(state="disabled", text="搜索中...")
        self.btn_refresh.configure(state="disabled")
        self._log(f"搜索ID: {manga_id}")
        self._clear_chapters()

        def worker():
            try:
                detail = self.parser.parse_manga_detail(manga_id)
                self.after(0, lambda: self._on_id_search_result(manga_id, detail))
            except Exception as e:
                self.after(0, lambda: self._on_id_search_failed(manga_id, e))
            finally:
                self.after(0, lambda: self._on_search_finished())
        threading.Thread(target=worker, daemon=True).start()

    def _on_id_search_result(self, manga_id, detail):
        self.selected_manga_id = manga_id
        total = len(detail.get("chapters", []))
        item = {
            "id": manga_id,
            "title": detail.get("title", ""),
            "cover": "",
            "url": manga_id,
            "author": detail.get("author", ""),
            "chapter_count": total,
        }
        self.favorites_data = [item]
        self.manga_list.set_items([item])
        self._on_chapters_loaded(detail)
        self._log(f"ID搜索: {detail.get('title', '')} (共{total}话)")

    def _on_id_search_failed(self, manga_id, e):
        self._log(f"未搜索到ID为 {manga_id} 的漫画")
        self.favorites_data = []
        self.manga_list.clear()
        self.selected_manga_id = None
        self.manga_check_vars.clear()
        self.lbl_manga_name.configure(text="没有符合的漫画")
        self.lbl_manga_id.configure(text=f"ID: {manga_id}")
        self.lbl_manga_author.configure(text="")
        self.lbl_manga_desc.configure(text="")
        self.lbl_manga_ch_count.configure(text="")

    def _on_manga_select(self, item_id, _item):
        self.selected_manga_id = item_id
        self._load_chapters(item_id)

    def _clear_manga_list(self):
        self.favorites_data = []
        self.manga_check_vars.clear()
        self.selected_manga_id = None
        self.manga_list.clear()
        self._clear_chapters()

    def _select_all_chapters(self):
        for v in self.chapter_check_vars.values():
            v.set(True)

    def _deselect_all_chapters(self):
        for v in self.chapter_check_vars.values():
            v.set(False)

    def _load_chapters(self, manga_id):
        self._clear_chapters()
        info = next((m for m in self.favorites_data if m["id"] == manga_id), None)
        if not info:
            return
        self._log(f"加载章节: {info['title']}")

        def worker():
            try:
                detail = self.parser.parse_manga_detail(info["url"])
                self.after(0, lambda: self._on_chapters_loaded(detail))
            except Exception as e:
                self.after(0, lambda: self._log(f"加载章节失败: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def _on_chapters_loaded(self, detail):
        self.chapter_data = detail.get("chapters", [])
        total = len(self.chapter_data)
        self.lbl_chapter_count.configure(text=f"共 {total} 话")
        self.chapter_check_vars.clear()

        self.lbl_manga_name.configure(text=detail.get("title", ""))
        self.lbl_manga_id.configure(text=f"ID: {self.selected_manga_id}" if self.selected_manga_id else "")
        self.lbl_manga_author.configure(text=f"作者: {detail.get('author', '')}" if detail.get("author") else "")
        desc = detail.get("description", "")
        self.lbl_manga_desc.configure(text=desc[:200] if desc else "暂无简介")
        self.lbl_manga_ch_count.configure(text=f"共 {total} 话")

        if self.selected_manga_id:
            info = next((m for m in self.favorites_data if m["id"] == self.selected_manga_id), None)
            if info:
                info["chapter_count"] = total
                author = detail.get("author", "") or info.get("author", "")
                if author:
                    info["author"] = author
                update_time = detail.get("update_time", "")
                if update_time:
                    info["update_time"] = update_time

        self._chapter_render_idx = 0
        self._chapter_render_gen += 1
        if total > 0:
            self._render_chapter_batch(self._chapter_render_gen)

    def _render_chapter_batch(self, gen):
        if gen != self._chapter_render_gen:
            return
        start = self._chapter_render_idx
        end = min(start + self._chapter_batch_size, len(self.chapter_data))

        for i in range(start, end):
            ch = self.chapter_data[i]
            var = ctk.BooleanVar(value=False)
            self.chapter_check_vars[ch["id"]] = var
            cb = ctk.CTkCheckBox(
                self.chapter_list_frame,
                text=f"  [{i + 1:03d}]  {ch['title'][:38]}",
                variable=var,
                checkbox_width=16, checkbox_height=16,
                border_color=BORDER, hover_color=BLUE,
                fg_color=BLUE,
                font=ctk.CTkFont(size=13, family=FONT_FAMILY),
                text_color=TEXT_LIGHT,
            )
            cb.pack(fill="x", padx=4, pady=1, anchor="w")

        self._chapter_render_idx = end
        if end < len(self.chapter_data):
            self.after(1, self._render_chapter_batch, gen)
        else:
            self._log(f"加载 {len(self.chapter_data)} 个章节")

    def _clear_chapters(self):
        self.chapter_data.clear()
        self.chapter_check_vars.clear()
        self.lbl_chapter_count.configure(text="")
        self.lbl_manga_name.configure(text="")
        self.lbl_manga_id.configure(text="")
        self.lbl_manga_author.configure(text="")
        self.lbl_manga_desc.configure(text="")
        self.lbl_manga_ch_count.configure(text="")
        self._chapter_render_idx = 0
        self._chapter_render_gen += 1
        for c in self.chapter_list_frame.winfo_children():
            c.destroy()

    def _clear_lists(self):
        self._clear_manga_list()

    def _start_download(self):
        self._do_download(all_chapters=False)

    def _start_download_all(self):
        self._do_download(all_chapters=True)

    def _do_download(self, all_chapters=False):
        if self.download_running:
            messagebox.showinfo("提示", "下载任务正在进行中")
            return
        if not self.selected_manga_id:
            messagebox.showinfo("提示", "请先在左侧点击选择一部漫画")
            return

        info = next((m for m in self.favorites_data if m["id"] == self.selected_manga_id), None)
        if not info:
            messagebox.showinfo("提示", "未找到选中的漫画信息")
            return

        if not all_chapters:
            selected_chapter_ids = [cid for cid, var in self.chapter_check_vars.items() if var.get()]
            if not selected_chapter_ids:
                messagebox.showinfo("提示", "请先在右侧勾选要下载的章节")
                return
        else:
            if not self.chapter_data:
                self._log("章节数据为空，正在重新加载...")
                return
            selected_chapter_ids = [ch["id"] for ch in self.chapter_data]

        self.download_running = True
        self.downloader.reset_cancel()
        self._set_buttons_downloading(True)
        self.progress_chapter.set(0)
        self.progress_total.set(0)

        auto_pdf = self.auto_pdf_var.get()
        self.download_thread = threading.Thread(
            target=self._download_worker,
            args=(info, selected_chapter_ids, auto_pdf),
            daemon=True)
        self.download_thread.start()

    def _set_buttons_downloading(self, downloading):
        if downloading:
            self.btn_download_sel.configure(state="disabled", text="下载中...")
            self.btn_download_all.configure(state="disabled", text="下载中...")
            self.btn_stop.configure(state="normal")
        else:
            self.btn_download_sel.configure(state="normal", text="⬇ 下载选中章节")
            self.btn_download_all.configure(state="normal", text="⬇⬇ 下载全部")
            self.btn_stop.configure(state="disabled")

    def _download_worker(self, manga_info, chapter_ids, auto_pdf):
        title = manga_info["title"]
        total = len(chapter_ids)
        self.after(0, lambda t=title: self.lbl_progress_title.configure(text=f"下载中: {t}"))
        self._log(f"⬇ {title} - 共{total}章")

        chapters_to_download = [ch for ch in self.chapter_data if ch["id"] in chapter_ids]

        for idx, chapter in enumerate(chapters_to_download, 1):
            if self.downloader._cancel_flag.is_set():
                break

            ch_id = chapter["id"]
            ch_title = chapter["title"]
            self.after(0, lambda i=idx, t=total: self.lbl_total_progress.configure(
                text=f"章节 {i}/{t}"))
            self.after(0, lambda ct=ch_title: self.lbl_progress_title.configure(
                text=f"下载中: {ct}"))

            self._log(f"  [{idx}/{total}] {ch_title}")

            try:
                chapter_dir = self.downloader.download_chapter(manga_info, chapter, base_dir=self.download_dir)
                self._log(f"  [{idx}/{total}] {ch_title} ✓ 下载完成")

                if auto_pdf:
                    self._log(f"  [{idx}/{total}] 正在生成PDF: {ch_title}")
                    try:
                        pdf_path = self.pdf_maker.make_single_chapter_pdf(
                            title, ch_title, download_dir=self.download_dir,
                            chapter_dir=chapter_dir)
                        short_path = os.path.basename(pdf_path) if pdf_path else "?"
                        self._log(f"  [{idx}/{total}] PDF已生成: {short_path}")
                    except Exception as e:
                        self._log(f"  [{idx}/{total}] PDF生成失败: {e}")

            except Exception as e:
                self._log(f"  [{idx}/{total}] 下载失败: {e}")

            self.after(0, lambda v=idx/total: self.progress_total.set(v))
            self.after(0, lambda i=idx, t=total: self.lbl_total_progress.configure(
                text=f"已完成 {i}/{t} 章"))

        self.after(0, self._on_download_done)

    def _on_download_done(self):
        self.download_running = False
        self._set_buttons_downloading(False)
        self.lbl_progress_title.configure(text="下载完成 ✓")
        self.lbl_progress_detail.configure(text="")
        self._log("下载全部完成 ✓")

    def _stop_download(self):
        self.downloader.cancel()
        self._log("正在停止下载...")

    def _on_download_progress(self, chapter_idx, chapter_total, page_idx, page_total, manga_title):
        if page_total:
            self._pending_ch_progress = page_idx / page_total
        self._pending_detail = f"{manga_title} - 页 {page_idx}/{page_total}"
        if not self._progress_dirty:
            self._progress_dirty = True
            self.after(50, self._flush_progress)

    def _flush_progress(self):
        self._progress_dirty = False
        self.progress_chapter.set(self._pending_ch_progress)
        self.lbl_progress_detail.configure(text=self._pending_detail)

    def _on_status_message(self, message):
        self._log(message)

    def _make_pdf_by_chapter(self):
        self._make_pdf("chapter")

    def _make_pdf_full(self):
        self._make_pdf("full")

    def _make_pdf(self, mode):
        if not self.selected_manga_id:
            messagebox.showinfo("提示", "请先在左侧点击选择漫画")
            return
        info = next((m for m in self.favorites_data if m["id"] == self.selected_manga_id), None)
        if not info:
            messagebox.showinfo("提示", "未找到选中的漫画信息")
            return
        label = "分章节" if mode == "chapter" else "完整版"
        self._log(f"📄 生成PDF ({label})...")

        def worker():
            t = info["title"]
            try:
                if mode == "chapter":
                    pdfs = self.pdf_maker.make_chapter_pdfs(t, download_dir=self.download_dir)
                    self._log(f"  [{t}] → {len(pdfs)} 个PDF")
                else:
                    path = self.pdf_maker.make_full_pdf(t, download_dir=self.download_dir)
                    self._log(f"  [{t}] → {os.path.basename(path)}")
            except Exception as e:
                self._log(f"  [{t}] PDF失败: {e}")
            self._log("PDF生成完成 ✓")
        threading.Thread(target=worker, daemon=True).start()

    def _open_pdf_dir(self):
        if os.path.isdir(self.download_dir):
            os.startfile(self.download_dir)
        else:
            os.startfile(os.path.dirname(self.download_dir) or ".")


def main():
    app = JMComicApp()
    app.mainloop()


if __name__ == "__main__":
    main()
