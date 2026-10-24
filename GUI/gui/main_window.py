"""JMComic-PDF 主窗口（PySide6 实现）。

布局沿用旧版 tkinter/customtkinter 界面：
顶部粉色导航栏（搜索 / 下载路径 / 登录），左侧漫画列表，
右侧漫画信息 + 章节列表 + 下载进度，底部运行日志。

线程模型：下载/网络等耗时操作仍放在 threading.Thread 中执行，
通过 Qt 信号（自动队列连接）把结果调度回 UI 线程。
"""

import os
import sys
import json
import threading

from PySide6.QtCore import (
    Qt,
    QObject,
    Signal,
    QTimer,
    QRect,
    QRectF,
    QSize,
    QPoint,
    QByteArray,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QTextEdit,
    QMessageBox,
    QFileDialog,
    QMenu,
    QColorDialog,
    QVBoxLayout,
    QHBoxLayout,
    QAbstractItemView,
    QStyledItemDelegate,
    QLayout,
    QStyle,
    QSizePolicy,
)

from core.client import ComicClient
from core.auth import Authenticator
from core.parser import MangaParser
from core.downloader import Downloader
from core.pdf_maker import PdfMaker
from config import (BASE_DIR, DOWNLOAD_DIR, FAVORITES_CACHE,
                    load_settings, save_settings, encode_pwd, decode_pwd)
from gui.styles import (
    BG_CARD, BG_GRAY, TEXT_DARK, TEXT_GRAY, TEXT_LIGHT,
    build_stylesheet, current_palette, current_theme, set_theme,
    register_custom_theme, THEMES, DEFAULT_THEME,
)

import re as _re


def _mask_ip(text):
    if not isinstance(text, str):
        return text
    ipv4 = r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
    ipv6 = r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b'
    text = _re.sub(ipv4, '[IP_REDACTED]', text)
    text = _re.sub(ipv6, '[IP_REDACTED]', text)
    return text


WINDOW_STATE_FILE = os.path.join(BASE_DIR, "window_state.json")


# ---------------------------------------------------------------------------
# 跨线程调度：把任意线程的回调投递到 UI 线程执行
# ---------------------------------------------------------------------------
class _UiBridge(QObject):
    log = Signal(str)
    progress = Signal(float, str)
    call = Signal(object)


class _WrapLayout(QLayout):
    """自动换行的按钮排布（替代旧版手写的 _wrap_row）。"""

    def __init__(self, parent=None, h_spacing=6, v_spacing=4):
        super().__init__(parent)
        self._items = []
        self._h = h_spacing
        self._v = v_spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        left = rect.x() + margins.left()
        top = rect.y() + margins.top()
        right = rect.right() - margins.right()
        x, y = left, top
        line_height = 0
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            if x > left and x + w > right:
                x = left
                y += line_height + self._v
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x += w + self._h
            line_height = max(line_height, h)
        return y + line_height - rect.y() + margins.bottom()


class MangaListDelegate(QStyledItemDelegate):
    """漫画列表项绘制：白色卡片 + 选中主题色底，两行文本（标题 / ID·作者·话数）。"""

    ITEM_HEIGHT = 52

    def sizeHint(self, option, index):
        return QSize(240, self.ITEM_HEIGHT)

    def paint(self, painter, option, index):
        item = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(item, dict):
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(0, 2, -0, -2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 8, 8)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            fill = QColor(current_palette()["accent_light"])
        elif hovered:
            fill = QColor("#F0F1F3")
        else:
            fill = QColor(BG_CARD)
        painter.fillPath(path, fill)

        title = (item.get("title") or f"#{item.get('id')}")[:40]
        meta = f"#{item.get('id')}"
        author = item.get("author", "")
        if author:
            meta += f"  ·  {author[:16]}"
        ch = item.get("chapter_count", 0)
        if ch:
            meta += f"  ·  {ch}话"

        text_rect = rect.adjusted(12, 0, -12, 0)
        font = painter.font()
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(TEXT_DARK))
        fm = painter.fontMetrics()
        painter.drawText(QRect(text_rect.x(), rect.y() + 7,
                               text_rect.width(), 20),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(title, Qt.TextElideMode.ElideRight,
                                       text_rect.width()))

        font.setPixelSize(11)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(TEXT_GRAY))
        painter.drawText(QRect(text_rect.x(), rect.y() + 28,
                               text_rect.width(), 16),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(meta, Qt.TextElideMode.ElideRight,
                                       text_rect.width()))
        painter.restore()


class JMComicApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("JMComic-PDF")
        self.resize(1180, 760)
        self.setMinimumSize(800, 540)

        self.settings = load_settings()
        self._init_theme()
        self.setStyleSheet(build_stylesheet())
        self.download_dir = self.settings.get("download_dir", DOWNLOAD_DIR)
        os.makedirs(self.download_dir, exist_ok=True)

        self._load_window_state()

        # ---- 状态 ----
        self.favorites_data = []
        self.chapter_data = []
        self.selected_manga_id = None
        self.download_running = False
        self.download_thread = None
        self._pdf_running = False
        self._refreshing = False
        self._searching = False
        # Progress debounce
        self._progress_dirty = False
        self._pending_ch_progress = 0.0
        self._pending_detail = ""
        # Log batch
        self._log_queue = []
        self._log_pending = False

        self._build_ui()

        # ---- 跨线程信号桥 ----
        self._bridge = _UiBridge()
        self._bridge.log.connect(self._on_log_queued)
        self._bridge.progress.connect(self._on_progress_queued)
        self._bridge.call.connect(self._run_queued)
        self._log_timer = QTimer(self)
        self._log_timer.setSingleShot(True)
        self._log_timer.setInterval(16)
        self._log_timer.timeout.connect(self._flush_log)
        self._progress_timer = QTimer(self)
        self._progress_timer.setSingleShot(True)
        self._progress_timer.setInterval(50)
        self._progress_timer.timeout.connect(self._flush_progress)

        # ---- 凭据回填 ----
        saved_user = self.settings.get("username", "")
        saved_pwd = decode_pwd(self.settings.get("password", ""))
        if saved_user:
            self.entry_user.setText(saved_user)
        if saved_pwd:
            self.entry_pass.setText(saved_pwd)

        # ---- 核心逻辑（与界面框架无关，保持不变） ----
        self.client = ComicClient()
        self.auth = Authenticator(self.client)
        self.parser = MangaParser(self.client)
        self.downloader = Downloader(self.client)
        self.pdf_maker = PdfMaker()

        self.downloader.on_progress(self._on_download_progress)
        self.downloader.on_status(self._on_status_message)

        QTimer.singleShot(
            100,
            lambda: self._log(f"网络引擎: {ComicClient.ENGINE}, "
                              f"代理: {_mask_ip(self.client.proxy) if self.client.proxy else '直连'}"))
        QTimer.singleShot(200, self._try_auto_login)
        QTimer.singleShot(0, self._apply_responsive_layout)

    # ------------------------------------------------------------------
    # 窗口状态
    # ------------------------------------------------------------------
    def _init_theme(self):
        """从设置恢复主题色（需在 build_stylesheet 之前调用）。"""
        theme = self.settings.get("theme", DEFAULT_THEME)
        if theme == "custom":
            color = self.settings.get("custom_theme_color", "")
            theme = register_custom_theme(color) or DEFAULT_THEME
        if theme not in THEMES:
            theme = DEFAULT_THEME
        self.theme_name = set_theme(theme)

    def _load_window_state(self):
        try:
            with open(WINDOW_STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            geo = state.get("geometry", "")
            if geo:
                if not self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii"))):
                    self.resize(1180, 760)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass

    def closeEvent(self, event):
        try:
            with open(WINDOW_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"geometry":
                           bytes(self.saveGeometry().toBase64()).decode("ascii")}, f)
        except OSError:
            pass
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "left_panel"):
            self._apply_responsive_layout()

    def _apply_responsive_layout(self):
        w = self.width()
        left_w = max(220, int(w * 0.23))
        self.left_panel.setFixedWidth(left_w)
        info_w = max(220, int((w - 40 - left_w) * 0.32))
        self.info_card.setFixedWidth(info_w)
        self.lbl_path.setVisible(w >= 980)
        self.lbl_status.setVisible(w >= 1060)
        self.lbl_version.setVisible(w >= 900)
        self.lbl_manga_hint.setVisible(left_w >= 260)

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QFrame(objectName="root")
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_navbar())
        root_layout.addWidget(self._build_content(), 1)
        root_layout.addWidget(self._build_footer())

    def _build_navbar(self):
        navbar = QFrame(objectName="navbar")
        navbar.setFixedHeight(52)
        layout = QHBoxLayout(navbar)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(8)

        self.lbl_title = QLabel("JMComic-PDF", objectName="navTitle")
        layout.addWidget(self.lbl_title)

        self.lbl_version = QLabel("v2.0", objectName="navVersion")
        layout.addWidget(self.lbl_version)

        search_wrap = QWidget()
        search_layout = QHBoxLayout(search_wrap)
        search_layout.setContentsMargins(10, 0, 10, 0)
        search_layout.setSpacing(4)
        self.entry_search = QLineEdit(objectName="navInput")
        self.entry_search.setPlaceholderText("搜索漫画...")
        self.entry_search.setClearButtonEnabled(True)
        self.entry_search.returnPressed.connect(self._do_search)
        search_layout.addWidget(self.entry_search, 1)
        self.btn_search = QPushButton("搜索", objectName="navWhiteBtn")
        self.btn_search.clicked.connect(self._do_search)
        search_layout.addWidget(self.btn_search)
        layout.addWidget(search_wrap, 1)

        path_wrap = QWidget()
        path_layout = QHBoxLayout(path_wrap)
        path_layout.setContentsMargins(6, 0, 10, 0)
        path_layout.setSpacing(4)
        self.btn_choose_path = QPushButton("路径", objectName="navWhiteBtn")
        self.btn_choose_path.setToolTip("选择下载目录")
        self.btn_choose_path.clicked.connect(self._choose_download_path)
        path_layout.addWidget(self.btn_choose_path)
        display_path = self.download_dir
        if len(display_path) > 28:
            display_path = "..." + display_path[-25:]
        self.lbl_path = QLabel(display_path, objectName="navText")
        path_layout.addWidget(self.lbl_path)
        layout.addWidget(path_wrap)

        self.btn_theme = QPushButton("主题", objectName="navWhiteBtn")
        self.btn_theme.setToolTip("切换界面主题色")
        self.btn_theme.clicked.connect(self._show_theme_menu)
        layout.addWidget(self.btn_theme)

        login_wrap = QWidget()
        login_layout = QHBoxLayout(login_wrap)
        login_layout.setContentsMargins(10, 0, 0, 0)
        login_layout.setSpacing(6)
        login_layout.addWidget(QLabel("账号", objectName="navLabel"))
        self.entry_user = QLineEdit(objectName="navInput")
        self.entry_user.setPlaceholderText("输入用户名")
        self.entry_user.setMinimumWidth(96)
        login_layout.addWidget(self.entry_user, 1)
        login_layout.addWidget(QLabel("密码", objectName="navLabel"))
        self.entry_pass = QLineEdit(objectName="navInput")
        self.entry_pass.setPlaceholderText("输入密码")
        self.entry_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.entry_pass.setMinimumWidth(96)
        self.entry_pass.returnPressed.connect(self._do_login)
        login_layout.addWidget(self.entry_pass, 1)
        self.btn_login = QPushButton("登录", objectName="navWhiteBtn")
        self.btn_login.clicked.connect(self._do_login)
        login_layout.addWidget(self.btn_login)
        self.lbl_status = QLabel("未登录", objectName="navLabel")
        login_layout.addWidget(self.lbl_status)
        layout.addWidget(login_wrap, 1)

        return navbar

    def _build_content(self):
        wrap = QWidget()
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(14, 10, 14, 4)
        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)
        wrap_layout.addLayout(content)
        content.addWidget(self._build_left_panel())
        content.addWidget(self._build_right_panel(), 1)
        return wrap

    def _build_left_panel(self):
        self.left_panel = QFrame(objectName="card")
        layout = QVBoxLayout(self.left_panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        layout.addWidget(QLabel("漫画列表", objectName="sectionTitle"))

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.lbl_manga_hint = QLabel("点击漫画名查看章节", objectName="subtle")
        actions.addWidget(self.lbl_manga_hint)
        actions.addStretch(1)
        self.btn_refresh = QPushButton("刷 新 收 藏", objectName="pinkSoftBtn")
        self.btn_refresh.clicked.connect(self._load_favorites)
        actions.addWidget(self.btn_refresh)
        layout.addLayout(actions)

        self.manga_list = QListWidget(objectName="mangaList")
        self.manga_list.setItemDelegate(MangaListDelegate(self.manga_list))
        self.manga_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.manga_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.manga_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.manga_list.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.manga_list.setMouseTracking(True)
        self.manga_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manga_list.itemClicked.connect(self._on_manga_item_clicked)
        layout.addWidget(self.manga_list, 1)

        return self.left_panel

    def _build_right_panel(self):
        card = QFrame(objectName="card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        # ---- 左侧 固定宽度: 漫画信息 ----
        self.info_card = QFrame(objectName="panel")
        info_layout = QVBoxLayout(self.info_card)
        info_layout.setContentsMargins(12, 10, 12, 10)
        info_layout.setSpacing(4)

        info_layout.addWidget(QLabel("漫画信息", objectName="cardTitle"))
        self.lbl_manga_name = QLabel("", objectName="infoName")
        self.lbl_manga_name.setWordWrap(True)
        self.lbl_manga_name.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        info_layout.addWidget(self.lbl_manga_name)
        self.lbl_manga_id = QLabel("", objectName="subtle")
        info_layout.addWidget(self.lbl_manga_id)
        self.lbl_manga_author = QLabel("", objectName="subtleLight")
        info_layout.addWidget(self.lbl_manga_author)

        info_layout.addSpacing(6)
        info_layout.addWidget(QLabel("简介", objectName="miniTitle"))
        self.lbl_manga_desc = QLabel("", objectName="subtle")
        self.lbl_manga_desc.setWordWrap(True)
        self.lbl_manga_desc.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        info_layout.addWidget(self.lbl_manga_desc, 1)

        self.lbl_manga_ch_count = QLabel("", objectName="pinkBold")
        info_layout.addWidget(self.lbl_manga_ch_count)

        layout.addWidget(self.info_card)

        # ---- 右侧: 章节列表 ----
        ch_area = QWidget()
        ch_layout = QVBoxLayout(ch_area)
        ch_layout.setContentsMargins(0, 0, 0, 0)
        ch_layout.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(QLabel("章节列表", objectName="sectionTitle"))
        header.addStretch(1)
        self.lbl_chapter_count = QLabel("", objectName="subtle")
        header.addWidget(self.lbl_chapter_count)
        ch_layout.addLayout(header)

        self.chapter_list = QListWidget(objectName="chapterList")
        self.chapter_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.chapter_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.chapter_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.chapter_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ch_layout.addWidget(self.chapter_list, 1)

        ch_actions = QWidget()
        self.ch_actions_layout = _WrapLayout(ch_actions, 6, 4)
        self.btn_ch_all = QPushButton("全选章节", objectName="blueSoftBtn")
        self.btn_ch_all.clicked.connect(self._select_all_chapters)
        self.ch_actions_layout.addWidget(self.btn_ch_all)
        self.btn_ch_none = QPushButton("取消全选", objectName="graySoftBtn")
        self.btn_ch_none.clicked.connect(self._deselect_all_chapters)
        self.ch_actions_layout.addWidget(self.btn_ch_none)
        self.chk_auto_pdf = QCheckBox("每章下载完自动生成PDF")
        self.ch_actions_layout.addWidget(self.chk_auto_pdf)
        ch_layout.addWidget(ch_actions)

        prog_card = QFrame(objectName="panel")
        prog_layout = QVBoxLayout(prog_card)
        prog_layout.setContentsMargins(10, 6, 10, 6)
        prog_layout.setSpacing(3)
        self.lbl_progress_title = QLabel("等待下载...", objectName="subtle")
        prog_layout.addWidget(self.lbl_progress_title)
        self.progress_chapter = QProgressBar(objectName="chapterProgress")
        self.progress_chapter.setRange(0, 1000)
        self.progress_chapter.setValue(0)
        self.progress_chapter.setTextVisible(False)
        self.progress_chapter.setFixedHeight(6)
        prog_layout.addWidget(self.progress_chapter)
        self.lbl_progress_detail = QLabel("", objectName="small")
        prog_layout.addWidget(self.lbl_progress_detail)
        self.progress_total = QProgressBar(objectName="totalProgress")
        self.progress_total.setRange(0, 1000)
        self.progress_total.setValue(0)
        self.progress_total.setTextVisible(False)
        self.progress_total.setFixedHeight(6)
        prog_layout.addWidget(self.progress_total)
        self.lbl_total_progress = QLabel("", objectName="small")
        prog_layout.addWidget(self.lbl_total_progress)
        ch_layout.addWidget(prog_card)

        btn_frame = QWidget()
        self.btn_frame_layout = _WrapLayout(btn_frame, 6, 4)
        self.btn_download_sel = QPushButton("下载选中章节", objectName="pinkSolidBtn")
        self.btn_download_sel.clicked.connect(self._start_download)
        self.btn_frame_layout.addWidget(self.btn_download_sel)
        self.btn_download_all = QPushButton("下载全部", objectName="pinkHoverBtn")
        self.btn_download_all.clicked.connect(self._start_download_all)
        self.btn_frame_layout.addWidget(self.btn_download_all)
        self.btn_stop = QPushButton("停止", objectName="dangerBtn")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_download)
        self.btn_frame_layout.addWidget(self.btn_stop)
        self.btn_pdf_chapter = QPushButton("分章节PDF", objectName="blueSolidBtn")
        self.btn_pdf_chapter.setToolTip(
            "直接用本地已下载的图片生成PDF（无需重新下载）。\n"
            "勾选了章节时只转换勾选的章节，未勾选时转换全部已下载章节")
        self.btn_pdf_chapter.clicked.connect(self._make_pdf_by_chapter)
        self.btn_frame_layout.addWidget(self.btn_pdf_chapter)
        self.btn_pdf_full = QPushButton("完整版PDF", objectName="blueSolidBtn")
        self.btn_pdf_full.setToolTip(
            "直接用本地已下载的图片合并为一个完整版PDF（无需重新下载）。\n"
            "勾选了章节时只合并勾选的章节")
        self.btn_pdf_full.clicked.connect(self._make_pdf_full)
        self.btn_frame_layout.addWidget(self.btn_pdf_full)
        self.btn_folder = QPushButton("打开目录", objectName="grayTextBtn")
        self.btn_folder.setToolTip("打开下载目录")
        self.btn_folder.clicked.connect(self._open_pdf_dir)
        self.btn_frame_layout.addWidget(self.btn_folder)
        ch_layout.addWidget(btn_frame)

        layout.addWidget(ch_area, 1)
        return card

    def _build_footer(self):
        card = QFrame(objectName="card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 8, 14, 10)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.addWidget(QLabel("运行日志", objectName="cardTitle"))
        header.addStretch(1)
        self.btn_clear_log = QPushButton("清空", objectName="graySoftBtn")
        self.btn_clear_log.setFixedHeight(24)
        self.btn_clear_log.clicked.connect(self._clear_log)
        header.addWidget(self.btn_clear_log)
        layout.addLayout(header)

        self.log_box = QTextEdit(objectName="logBox")
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(110)
        self.log_box.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.log_box)
        return card

    # ------------------------------------------------------------------
    # 跨线程 UI 调度
    # ------------------------------------------------------------------
    def post(self, fn):
        """线程安全地把 fn 调度到 UI 线程执行（等价旧版 self.after(0, fn)）。"""
        self._bridge.call.emit(fn)

    def _run_queued(self, fn):
        fn()

    def _log(self, message):
        self._bridge.log.emit(_mask_ip(message))

    def _on_log_queued(self, message):
        self._log_queue.append(message)
        if not self._log_pending:
            self._log_pending = True
            self._log_timer.start()

    def _flush_log(self):
        self._log_pending = False
        if not self._log_queue:
            return
        for msg in self._log_queue:
            self.log_box.append(msg)
        self._log_queue.clear()
        self.log_box.verticalScrollBar().setValue(
            self.log_box.verticalScrollBar().maximum())

    def _clear_log(self):
        self.log_box.clear()

    def _on_download_progress(self, chapter_idx, chapter_total,
                              page_idx, page_total, manga_title):
        value = page_idx / page_total if page_total else self._pending_ch_progress
        self._bridge.progress.emit(value, f"{manga_title} - 页 {page_idx}/{page_total}")

    def _on_progress_queued(self, value, detail):
        self._pending_ch_progress = value
        self._pending_detail = detail
        if not self._progress_dirty:
            self._progress_dirty = True
            self._progress_timer.start()

    def _flush_progress(self):
        self._progress_dirty = False
        self.progress_chapter.setValue(int(self._pending_ch_progress * 1000))
        self.lbl_progress_detail.setText(self._pending_detail)

    def _on_status_message(self, message):
        self._log(message)

    # ------------------------------------------------------------------
    # 漫画列表
    # ------------------------------------------------------------------
    def _set_manga_items(self, items):
        self.manga_list.clear()
        for it in items:
            li = QListWidgetItem()
            li.setData(Qt.ItemDataRole.UserRole, it)
            self.manga_list.addItem(li)

    def _on_manga_item_clicked(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            self._on_manga_select(data.get("id"), data)

    # ------------------------------------------------------------------
    # 路径选择
    # ------------------------------------------------------------------
    def _choose_download_path(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择下载目录", self.download_dir)
        if not path:
            return
        self.download_dir = path
        os.makedirs(self.download_dir, exist_ok=True)
        self.settings["download_dir"] = path
        save_settings(self.settings)
        display_path = path
        if len(display_path) > 28:
            display_path = "..." + display_path[-25:]
        self.lbl_path.setText(display_path)
        self._log(f"下载路径已更新: {path}")

    # ------------------------------------------------------------------
    # 主题切换
    # ------------------------------------------------------------------
    def _theme_icon(self, color):
        """生成主题色圆形色块图标。"""
        pix = QPixmap(14, 14)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(0, 0, 0, 30), 1))
        p.setBrush(QColor(color))
        p.drawEllipse(1, 1, 11, 11)
        p.end()
        return QIcon(pix)

    def _show_theme_menu(self):
        menu = QMenu(self)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for name, palette in THEMES.items():
            action = QAction(self._theme_icon(palette["accent"]),
                             palette["label"], menu)
            action.setCheckable(True)
            action.setChecked(name == current_theme())
            action.triggered.connect(
                lambda checked=False, n=name: self._switch_theme(n))
            group.addAction(action)
            menu.addAction(action)
        menu.addSeparator()
        custom = QAction(self._theme_icon(current_palette()["accent"]),
                         "自定义颜色...", menu)
        custom.triggered.connect(self._pick_custom_theme)
        menu.addAction(custom)
        menu.exec(QCursor.pos())

    def _pick_custom_theme(self):
        color = QColorDialog.getColor(
            QColor(current_palette()["accent"]), self, "选择主题色")
        if not color.isValid():
            return
        name = register_custom_theme(color.name())
        if name:
            self.settings["custom_theme_color"] = color.name()
            self._switch_theme(name)

    def _switch_theme(self, name):
        if name not in THEMES or name == current_theme():
            return
        set_theme(name)
        self.theme_name = name
        self.settings["theme"] = name
        save_settings(self.settings)
        self.setStyleSheet(build_stylesheet())
        self._log(f"主题已切换: {THEMES[name]['label']}")

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------
    def _try_auto_login(self):
        self._log("正在检查登录状态...")

        def worker():
            success, msg = self.auth.try_auto_login()
            self.post(lambda: self._on_auto_login_result(success, msg))
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
        username = self.entry_user.text().strip()
        password = self.entry_pass.text().strip()
        if not username or not password:
            QMessageBox.information(self, "提示", "请输入用户名和密码")
            return
        self.btn_login.setEnabled(False)
        self.btn_login.setText("登录中...")
        self._log("正在登录...")

        def worker():
            success, msg = self.auth.login(username, password)
            self.post(lambda: self._on_login_result(success, msg))
        threading.Thread(target=worker, daemon=True).start()

    def _on_login_result(self, success, msg):
        self.btn_login.setEnabled(True)
        self._log(f"[{'✓' if success else '✗'}] {msg}")
        if success:
            username = self.entry_user.text().strip()
            password = self.entry_pass.text().strip()
            self.settings["username"] = username
            self.settings["password"] = encode_pwd(password) if password else ""
            save_settings(self.settings)
            self._set_login_state(True)
            self._load_favorites()
        else:
            self.btn_login.setText("登录")
            QMessageBox.critical(self, "登录失败", msg)

    def _do_logout(self):
        self.auth.logout()
        self._set_login_state(False)
        self._log("已退出登录")
        self._clear_lists()

    def _set_login_state(self, logged_in):
        if logged_in:
            username = self.auth.username or ""
            self.lbl_status.setText(f"已登录: {username}")
            self.btn_login.setEnabled(True)
            self.btn_login.setText("退出登录")
        else:
            self.lbl_status.setText("未登录")
            self.btn_login.setEnabled(True)
            self.btn_login.setText("登录")

    # ------------------------------------------------------------------
    # 收藏
    # ------------------------------------------------------------------
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
            QMessageBox.information(self, "提示", "请先登录")
            return
        if self._refreshing:
            self._log("收藏列表正在刷新中，请稍候...")
            return

        self._refreshing = True
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("加载中...")
        self.btn_search.setEnabled(False)
        username = self.auth.username or ""
        self._log("正在加载收藏列表...")
        if username:
            self._log("收藏地址: https://18comic.vip/user/***/favorite/albums")
        else:
            self._log("收藏地址: https://18comic.vip/user/favorite")

        self._clear_manga_list()
        self._log("正在从服务器获取最新收藏数据...")

        def worker():
            try:
                if not self.auth.verify_session_valid():
                    self._log("会话已过期，请重新登录后再刷新收藏列表")
                    self.post(lambda: self._on_favorites_loaded([]))
                    return
                favs = self.parser.parse_all_favorites(username=self.auth.username or "")
                if not favs:
                    threading.Thread(
                        target=self._diagnose_favorites_failure, daemon=True).start()
                self.post(lambda: self._on_favorites_loaded(favs))
            except Exception as e:
                self._log(f"加载失败: {e}")
                self.post(lambda: self._on_favorites_loaded([]))
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
                link_count = len(re.findall(
                    r'href=["\'][^"\']*/(album|photo|comic|manga|book|detail)/\d+[^"\']*["\']',
                    resp.text, re.I))
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
                    dump_path = os.path.join(
                        tempfile.gettempdir(), f"jmpdf_debug_fav_{urls.index(u)}.html")
                    try:
                        with open(dump_path, "w", encoding="utf-8") as f:
                            f.write(resp.text[:80000])
                        lines.append(f"[诊断] 调试文件: {dump_path}")
                    except Exception:
                        pass
                for line in lines:
                    self._log(line)
                if link_count > 0 and not is_login:
                    self._log(f"[诊断] URL {u} 似乎有效（找到 {link_count} 个链接），"
                              f"但解析器未提取到条目，请检查解析器选择器")
                    break
                elif link_count > 0:
                    self._log(f"[诊断] URL {u} 找到链接但页面可能是登录页")
        except Exception as e:
            self._log(f"[诊断] 失败: {e}")

    def _on_favorites_loaded(self, favs):
        self._refreshing = False
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("刷 新 收 藏")
        self.btn_search.setEnabled(True)
        if not favs:
            cached = self._load_favorites_cache()
            if cached:
                self._set_manga_items(cached)
                self.favorites_data = cached
                self._log("刷新失败，已恢复为本地缓存数据")
                self._log("提示: 请尝试重新登录。如问题持续，检查 %TEMP%/jmpdf_debug_fav_*.html")
                QMessageBox.warning(
                    self, "刷新失败",
                    "无法从服务器获取最新收藏数据，已恢复为本地缓存。\n请尝试重新登录后再试。")
            else:
                self._log("收藏列表为空（请确认已登录且已收藏漫画）")
                self._log("提示: 诊断信息已写入上方日志。调试文件: %TEMP%/jmpdf_debug_fav_*.html")
                QMessageBox.error(self, "刷新失败", "无法获取收藏列表。\n请确认已登录且已收藏漫画。")
            return
        self._save_favorites_cache(favs)
        self._clear_manga_list()
        self.favorites_data = favs
        self._set_manga_items(favs)
        self._log(f"已从服务器同步 {len(favs)} 部收藏漫画")

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def _do_search(self):
        keyword = self.entry_search.text().strip()
        if not keyword:
            return
        if self._searching:
            self._log("搜索正在进行中，请稍候...")
            return
        if keyword.isdigit():
            self._search_by_id(keyword)
            return
        self._searching = True
        self.btn_search.setEnabled(False)
        self.btn_search.setText("搜索中...")
        self.btn_refresh.setEnabled(False)
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
                self.post(lambda: self._on_search_results(results))
            except Exception as e:
                self._log(f"搜索失败: {e}")
            finally:
                self.post(self._on_search_finished)
        threading.Thread(target=worker, daemon=True).start()

    def _on_search_finished(self):
        self._searching = False
        self.btn_search.setEnabled(True)
        self.btn_search.setText("搜索")
        self.btn_refresh.setEnabled(True)

    def _on_search_results(self, results):
        self.favorites_data = results
        self._set_manga_items(results)
        self._log(f"搜索到 {len(results)} 部漫画")

    def _search_by_id(self, manga_id):
        self._searching = True
        self.btn_search.setEnabled(False)
        self.btn_search.setText("搜索中...")
        self.btn_refresh.setEnabled(False)
        self._log(f"搜索ID: {manga_id}")
        self._clear_chapters()

        def worker():
            try:
                detail = self.parser.parse_manga_detail(manga_id)
                self.post(lambda: self._on_id_search_result(manga_id, detail))
            except Exception as e:
                self.post(lambda: self._on_id_search_failed(manga_id, e))
            finally:
                self.post(self._on_search_finished)
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
        self._set_manga_items([item])
        self._on_chapters_loaded(detail)
        self._log(f"ID搜索: {detail.get('title', '')} (共{total}话)")

    def _on_id_search_failed(self, manga_id, _e):
        self._log(f"未搜索到ID为 {manga_id} 的漫画")
        self.favorites_data = []
        self.manga_list.clear()
        self.selected_manga_id = None
        self.lbl_manga_name.setText("没有符合的漫画")
        self.lbl_manga_id.setText(f"ID: {manga_id}")
        self.lbl_manga_author.setText("")
        self.lbl_manga_desc.setText("")
        self.lbl_manga_ch_count.setText("")

    # ------------------------------------------------------------------
    # 章节
    # ------------------------------------------------------------------
    def _on_manga_select(self, item_id, _item):
        self.selected_manga_id = item_id
        self._load_chapters(item_id)

    def _clear_manga_list(self):
        self.favorites_data = []
        self.selected_manga_id = None
        self.manga_list.clear()
        self._clear_chapters()

    def _select_all_chapters(self):
        for row in range(self.chapter_list.count()):
            self.chapter_list.item(row).setCheckState(
                Qt.CheckState.Checked)

    def _deselect_all_chapters(self):
        for row in range(self.chapter_list.count()):
            self.chapter_list.item(row).setCheckState(
                Qt.CheckState.Unchecked)

    def _get_checked_chapter_ids(self):
        return [self.chapter_list.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(self.chapter_list.count())
                if self.chapter_list.item(row).checkState() == Qt.CheckState.Checked]

    def _load_chapters(self, manga_id):
        self._clear_chapters()
        info = next((m for m in self.favorites_data if m["id"] == manga_id), None)
        if not info:
            return
        self._log(f"加载章节: {info['title']}")

        def worker():
            try:
                detail = self.parser.parse_manga_detail(info["url"])
                self.post(lambda: self._on_chapters_loaded(detail))
            except Exception as e:
                self._log(f"加载章节失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _on_chapters_loaded(self, detail):
        self.chapter_data = detail.get("chapters", [])
        total = len(self.chapter_data)
        self.lbl_chapter_count.setText(f"共 {total} 话")

        self.lbl_manga_name.setText(detail.get("title", ""))
        self.lbl_manga_id.setText(
            f"ID: {self.selected_manga_id}" if self.selected_manga_id else "")
        author = detail.get("author", "")
        self.lbl_manga_author.setText(f"作者: {author}" if author else "")
        desc = detail.get("description", "")
        self.lbl_manga_desc.setText(desc[:200] if desc else "暂无简介")
        self.lbl_manga_ch_count.setText(f"共 {total} 话")

        if self.selected_manga_id:
            info = next((m for m in self.favorites_data
                         if m["id"] == self.selected_manga_id), None)
            if info:
                info["chapter_count"] = total
                author = detail.get("author", "") or info.get("author", "")
                if author:
                    info["author"] = author
                update_time = detail.get("update_time", "")
                if update_time:
                    info["update_time"] = update_time

        self.chapter_list.clear()
        for i, ch in enumerate(self.chapter_data):
            item = QListWidgetItem(f"[{i + 1:03d}]  {ch['title'][:38]}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, ch["id"])
            self.chapter_list.addItem(item)
        if total:
            self._log(f"加载 {total} 个章节")
        self._mark_downloaded_chapters()

    def _mark_downloaded_chapters(self):
        """扫描本地下载目录，给已下载的章节行尾加上 ✓ 标记。"""
        if not self.selected_manga_id or not self.chapter_data:
            return
        info = next((m for m in self.favorites_data
                     if m["id"] == self.selected_manga_id), None)
        if not info:
            return
        manga_title = info.get("title", "")
        manga_id = info.get("id")
        titles = [ch["title"] for ch in self.chapter_data]

        def worker():
            try:
                found, _missing = self.pdf_maker.check_downloaded_chapters(
                    manga_title, titles, download_dir=self.download_dir,
                    manga_id=manga_id)
            except Exception:
                return
            found_set = set(found)

            def apply():
                # 期间用户切换了漫画则放弃本次标记
                if self.selected_manga_id != manga_id:
                    return
                for row in range(self.chapter_list.count()):
                    item = self.chapter_list.item(row)
                    ch_id = item.data(Qt.ItemDataRole.UserRole)
                    ch = next((c for c in self.chapter_data
                               if c["id"] == ch_id), None)
                    if not ch:
                        continue
                    text = f"[{row + 1:03d}]  {ch['title'][:38]}"
                    if ch["title"] in found_set:
                        text += "  ✓"
                    item.setText(text)

            self.post(apply)

        threading.Thread(target=worker, daemon=True).start()

    def _clear_chapters(self):
        self.chapter_data = []
        self.lbl_chapter_count.setText("")
        self.lbl_manga_name.setText("")
        self.lbl_manga_id.setText("")
        self.lbl_manga_author.setText("")
        self.lbl_manga_desc.setText("")
        self.lbl_manga_ch_count.setText("")
        self.chapter_list.clear()

    def _clear_lists(self):
        self._clear_manga_list()

    # ------------------------------------------------------------------
    # 下载
    # ------------------------------------------------------------------
    def _start_download(self):
        self._do_download(all_chapters=False)

    def _start_download_all(self):
        self._do_download(all_chapters=True)

    def _do_download(self, all_chapters=False):
        if self.download_running:
            QMessageBox.information(self, "提示", "下载任务正在进行中")
            return
        if not self.selected_manga_id:
            QMessageBox.information(self, "提示", "请先在左侧点击选择一部漫画")
            return

        info = next((m for m in self.favorites_data
                     if m["id"] == self.selected_manga_id), None)
        if not info:
            QMessageBox.information(self, "提示", "未找到选中的漫画信息")
            return

        if not all_chapters:
            selected_chapter_ids = self._get_checked_chapter_ids()
            if not selected_chapter_ids:
                QMessageBox.information(self, "提示", "请先在右侧勾选要下载的章节")
                return
        else:
            if not self.chapter_data:
                self._log("章节数据为空，正在重新加载...")
                return
            selected_chapter_ids = [ch["id"] for ch in self.chapter_data]

        self.download_running = True
        self.downloader.reset_cancel()
        self._set_buttons_downloading(True)
        self.progress_chapter.setValue(0)
        self.progress_total.setValue(0)

        auto_pdf = self.chk_auto_pdf.isChecked()
        self.download_thread = threading.Thread(
            target=self._download_worker,
            args=(info, selected_chapter_ids, auto_pdf),
            daemon=True)
        self.download_thread.start()

    def _set_buttons_downloading(self, downloading):
        if downloading:
            self.btn_download_sel.setEnabled(False)
            self.btn_download_sel.setText("下载中...")
            self.btn_download_all.setEnabled(False)
            self.btn_download_all.setText("下载中...")
            self.btn_stop.setEnabled(True)
        else:
            self.btn_download_sel.setEnabled(True)
            self.btn_download_sel.setText("下载选中章节")
            self.btn_download_all.setEnabled(True)
            self.btn_download_all.setText("下载全部")
            self.btn_stop.setEnabled(False)

    def _download_worker(self, manga_info, chapter_ids, auto_pdf):
        title = manga_info["title"]
        total = len(chapter_ids)
        self.post(lambda: self.lbl_progress_title.setText(f"下载中: {title}"))
        self._log(f"{title} - 共{total}章")

        chapters_to_download = [ch for ch in self.chapter_data
                                if ch["id"] in chapter_ids]

        for idx, chapter in enumerate(chapters_to_download, 1):
            if self.downloader._cancel_flag.is_set():
                break

            ch_title = chapter["title"]
            self.post(lambda i=idx, t=total:
                      self.lbl_total_progress.setText(f"章节 {i}/{t}"))
            self.post(lambda ct=ch_title:
                      self.lbl_progress_title.setText(f"下载中: {ct}"))

            self._log(f"  [{idx}/{total}] {ch_title}")

            try:
                chapter_dir = self.downloader.download_chapter(
                    manga_info, chapter, base_dir=self.download_dir)
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

            self.post(lambda v=idx / total:
                      self.progress_total.setValue(int(v * 1000)))
            self.post(lambda i=idx, t=total:
                      self.lbl_total_progress.setText(f"已完成 {i}/{t} 章"))

        self.post(self._on_download_done)

    def _on_download_done(self):
        self.download_running = False
        self._set_buttons_downloading(False)
        self.lbl_progress_title.setText("下载完成 ✓")
        self.lbl_progress_detail.setText("")
        self._log("下载全部完成 ✓")
        self._mark_downloaded_chapters()

    def _stop_download(self):
        self.downloader.cancel()
        self._log("正在停止下载...")

    # ------------------------------------------------------------------
    # PDF
    # ------------------------------------------------------------------
    def _make_pdf_by_chapter(self):
        self._make_pdf("chapter")

    def _make_pdf_full(self):
        self._make_pdf("full")

    def _make_pdf(self, mode):
        if self._pdf_running:
            QMessageBox.information(self, "提示", "正在生成PDF，请稍候")
            return
        if not self.selected_manga_id:
            QMessageBox.information(self, "提示", "请先在左侧点击选择漫画")
            return
        info = next((m for m in self.favorites_data
                     if m["id"] == self.selected_manga_id), None)
        if not info:
            QMessageBox.information(self, "提示", "未找到选中的漫画信息")
            return

        # 勾选了章节则只转换勾选的章节（必须是已下载的章节），
        # 未勾选则转换本地已下载的全部章节
        checked_ids = set(self._get_checked_chapter_ids())
        checked_titles = [ch["title"] for ch in self.chapter_data
                          if ch["id"] in checked_ids]

        label = "分章节" if mode == "chapter" else "完整版"
        if checked_titles:
            self._log(f"生成{label}PDF (仅选中的 {len(checked_titles)} 章, "
                      f"直接使用本地已下载图片)...")
        else:
            self._log(f"生成{label}PDF (直接使用本地已下载图片)...")

        self._pdf_running = True
        self.post(lambda: self._set_pdf_buttons_running(True))

        def worker():
            t = info["title"]
            try:
                self.post(lambda: self.lbl_progress_title.setText(
                    f"生成{label}PDF中: {t}"))
                if mode == "chapter":
                    pdfs, missing = self.pdf_maker.make_chapter_pdfs(
                        t, download_dir=self.download_dir,
                        manga_id=info.get("id"),
                        chapter_titles=checked_titles or None)
                    if pdfs:
                        self._log(f"  [{t}] → {len(pdfs)} 个PDF")
                else:
                    path, missing = self.pdf_maker.make_full_pdf(
                        t, download_dir=self.download_dir,
                        manga_id=info.get("id"),
                        chapter_titles=checked_titles or None)
                    if path:
                        self._log(f"  [{t}] → {os.path.basename(path)}")
                for m_title in missing:
                    self._log(f"  [{t}] 章节“{m_title}”本地未下载, "
                              f"已跳过 (勾选后点“下载选中章节”可补齐)")
            except Exception as e:
                self._log(f"  [{t}] PDF失败: {e}")
            finally:
                self._pdf_running = False
                self.post(lambda: self._set_pdf_buttons_running(False))
            self._log("PDF生成完成 ✓")
            self.post(lambda: self.lbl_progress_title.setText("PDF生成完成 ✓"))
        threading.Thread(target=worker, daemon=True).start()

    def _set_pdf_buttons_running(self, running):
        self.btn_pdf_chapter.setEnabled(not running)
        self.btn_pdf_chapter.setText("转换中..." if running else "分章节PDF")
        self.btn_pdf_full.setEnabled(not running)
        self.btn_pdf_full.setText("转换中..." if running else "完整版PDF")

    def _open_pdf_dir(self):
        if os.path.isdir(self.download_dir):
            os.startfile(self.download_dir)
        else:
            os.startfile(os.path.dirname(self.download_dir) or ".")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("JMComic-PDF")
    window = JMComicApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
