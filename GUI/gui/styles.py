"""PySide6 全局配色与 QSS 样式。

配色沿用旧版 tkinter/customtkinter 界面的 B 站粉风格，
让新旧界面观感一致。

支持主题色切换：
- THEMES          预置主题，accent* 为随主题变化的强调色
- set_theme()     切换当前主题
- current_palette()  取当前主题色板（供列表委托等 Python 自绘代码取色）
- build_stylesheet() 按当前主题生成全局 QSS

控件 objectName 中的 pink/blue 等字样只是沿用旧名：
blue* 系列是固定的辅助色，pink* 系列才跟随主题色变化。
"""

import os
import tempfile

# ---------- 固定配色（不随主题变化） ----------
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
DANGER_HOVER = "#E57373"
FONT_FAMILY = "Microsoft YaHei UI"

# ---------- 主题色 ----------
# accent       强调色（导航栏、主按钮、白底按钮文字、滚动条悬停等）
# accent_hover 强调色按钮悬停态
# accent_light 强调色浅底（soft 按钮底色、列表选中底色等）
# accent_press 白底按钮按下态
# accent_disabled / accent_disabled2  强调色按钮禁用态底色
THEMES = {
    "pink": {
        "label": "B站粉",
        "accent": "#FB7299",
        "accent_hover": "#FC8BAA",
        "accent_light": "#FFF0F4",
        "accent_press": "#FFE4EE",
        "accent_disabled": "#F6D9E2",
        "accent_disabled2": "#F9D3DE",
    },
    "blue": {
        "label": "天空蓝",
        "accent": "#00A1D6",
        "accent_hover": "#00B5E5",
        "accent_light": "#E6F7FC",
        "accent_press": "#D2F0FA",
        "accent_disabled": "#C5E9F5",
        "accent_disabled2": "#BCE6F6",
    },
    "green": {
        "label": "薄荷绿",
        "accent": "#07C160",
        "accent_hover": "#2BD874",
        "accent_light": "#E8F9EF",
        "accent_press": "#D9F3E2",
        "accent_disabled": "#C2E9CF",
        "accent_disabled2": "#CDEDD8",
    },
    "purple": {
        "label": "淡雅紫",
        "accent": "#7C5CFC",
        "accent_hover": "#9679FD",
        "accent_light": "#F1EDFF",
        "accent_press": "#E5DEFF",
        "accent_disabled": "#D6CCF7",
        "accent_disabled2": "#DED5F9",
    },
    "orange": {
        "label": "活力橙",
        "accent": "#FF8C42",
        "accent_hover": "#FFA05C",
        "accent_light": "#FFF3EB",
        "accent_press": "#FFE7D5",
        "accent_disabled": "#FFDEC0",
        "accent_disabled2": "#FFE3CA",
    },
    "graphite": {
        "label": "石墨灰",
        "accent": "#5A6B7B",
        "accent_hover": "#71849A",
        "accent_light": "#EEF1F4",
        "accent_press": "#E3E8EC",
        "accent_disabled": "#D2DAE0",
        "accent_disabled2": "#D9E0E5",
    },
}
CUSTOM_THEME = "custom"
DEFAULT_THEME = "pink"

_current_theme = DEFAULT_THEME


def set_theme(name):
    """设置当前主题，返回生效的主题名。"""
    global _current_theme
    if name in THEMES:
        _current_theme = name
    return _current_theme


def current_theme():
    return _current_theme if _current_theme in THEMES else DEFAULT_THEME


def current_palette():
    return THEMES[current_theme()]


def make_custom_palette(color_hex):
    """由任意颜色推导一组完整色板（自定义主题用）。"""
    from PySide6.QtGui import QColor

    c = QColor(color_hex)
    if not c.isValid():
        return None
    c = c.toRgb()

    def mix(white_ratio):
        r = round(c.red() * (1 - white_ratio) + 255 * white_ratio)
        g = round(c.green() * (1 - white_ratio) + 255 * white_ratio)
        b = round(c.blue() * (1 - white_ratio) + 255 * white_ratio)
        return f"#{r:02X}{g:02X}{b:02X}"

    return {
        "label": "自定义",
        "accent": c.name(),
        "accent_hover": mix(0.17),
        "accent_light": mix(0.89),
        "accent_press": mix(0.82),
        "accent_disabled": mix(0.72),
        "accent_disabled2": mix(0.68),
    }


def register_custom_theme(color_hex):
    """注册/覆盖自定义主题，成功返回主题名，失败返回 None。"""
    palette = make_custom_palette(color_hex)
    if palette is None:
        return None
    THEMES[CUSTOM_THEME] = palette
    return CUSTOM_THEME


_CHECK_ICON = os.path.join(tempfile.gettempdir(), "jmpdf_checkmark.png")


def _checkmark_image():
    """生成白色对勾小图标（复选框选中态用），返回 QSS 可用的路径。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    if os.path.isfile(_CHECK_ICON):
        return _CHECK_ICON.replace(os.sep, "/")
    try:
        pix = QPixmap(16, 16)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("white"), 2.4, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(4, 9, 7, 12)
        p.drawLine(7, 12, 12, 5)
        p.end()
        pix.save(_CHECK_ICON, "PNG")
    except Exception:
        pass
    return _CHECK_ICON.replace(os.sep, "/")


def build_stylesheet() -> str:
    check = _checkmark_image()
    pal = current_palette()
    accent = pal["accent"]
    accent_hover = pal["accent_hover"]
    accent_light = pal["accent_light"]
    accent_press = pal["accent_press"]
    accent_disabled = pal["accent_disabled"]
    accent_disabled2 = pal["accent_disabled2"]
    return f"""
* {{
    font-family: "{FONT_FAMILY}";
    color: {TEXT_DARK};
}}

QFrame#root {{ background-color: {BG_GRAY}; }}
QFrame#card {{
    background-color: {BG_CARD};
    border-radius: 12px;
}}
QFrame#panel {{
    background-color: {BG_GRAY};
    border-radius: 8px;
}}

/* ---------- 顶部导航栏 ---------- */
QFrame#navbar {{
    background-color: {accent};
}}
QLabel#navTitle {{
    color: white;
    font-size: 19px;
    font-weight: bold;
}}
QLabel#navVersion {{
    color: rgba(255, 255, 255, 220);
    font-size: 11px;
}}
QLabel#navLabel {{
    color: {TEXT_DARK};
    font-size: 12px;
    font-weight: bold;
    background: transparent;
}}
QLabel#navText {{
    color: white;
    font-size: 11px;
    background: transparent;
}}
QLineEdit#navInput {{
    background-color: white;
    border: none;
    border-radius: 15px;
    padding: 0 12px;
    min-height: 30px;
    max-height: 30px;
    font-size: 13px;
    color: {TEXT_DARK};
    selection-background-color: {accent};
    selection-color: white;
}}

QPushButton {{
    border: none;
    font-family: "{FONT_FAMILY}";
}}
QPushButton#navWhiteBtn {{
    background-color: white;
    color: {accent};
    min-height: 30px;
    max-height: 30px;
    padding: 0 14px;
    border-radius: 15px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#navWhiteBtn:hover {{ background-color: {accent_light}; }}
QPushButton#navWhiteBtn:pressed {{ background-color: {accent_press}; }}
QPushButton#navWhiteBtn:disabled {{ color: {TEXT_GRAY}; }}

QPushButton#pinkSoftBtn {{
    background-color: {accent_light};
    color: {accent};
    min-height: 26px;
    max-height: 26px;
    padding: 0 12px;
    border-radius: 13px;
    font-size: 12px;
}}
QPushButton#pinkSoftBtn:hover {{ background-color: {accent}; color: white; }}
QPushButton#pinkSoftBtn:disabled {{ background-color: {BG_GRAY}; color: {TEXT_GRAY}; }}

QPushButton#blueSoftBtn {{
    background-color: {BLUE_LIGHT};
    color: {BLUE};
    min-height: 26px;
    max-height: 26px;
    padding: 0 12px;
    border-radius: 13px;
    font-size: 12px;
}}
QPushButton#blueSoftBtn:hover {{ background-color: {BLUE}; color: white; }}

QPushButton#graySoftBtn {{
    background-color: {BG_GRAY};
    color: {TEXT_GRAY};
    border: 1px solid {BORDER};
    min-height: 26px;
    max-height: 26px;
    padding: 0 12px;
    border-radius: 13px;
    font-size: 12px;
}}
QPushButton#graySoftBtn:hover {{ background-color: {BORDER}; color: {TEXT_LIGHT}; }}

QPushButton#pinkSolidBtn {{
    background-color: {accent};
    color: white;
    min-height: 34px;
    max-height: 34px;
    padding: 0 18px;
    border-radius: 17px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#pinkSolidBtn:hover {{ background-color: {accent_hover}; }}
QPushButton#pinkSolidBtn:disabled {{ background-color: {accent_disabled}; color: white; }}

QPushButton#pinkHoverBtn {{
    background-color: {accent_hover};
    color: white;
    min-height: 34px;
    max-height: 34px;
    padding: 0 18px;
    border-radius: 17px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#pinkHoverBtn:hover {{ background-color: {accent}; }}
QPushButton#pinkHoverBtn:disabled {{ background-color: {accent_disabled2}; color: white; }}

QPushButton#blueSolidBtn {{
    background-color: {BLUE};
    color: white;
    min-height: 34px;
    max-height: 34px;
    padding: 0 18px;
    border-radius: 17px;
    font-size: 13px;
}}
QPushButton#blueSolidBtn:hover {{ background-color: {BLUE_HOVER}; }}
QPushButton#blueSolidBtn:disabled {{ background-color: #C5E9F5; color: white; }}

QPushButton#dangerBtn {{
    background-color: {DANGER};
    color: white;
    min-height: 34px;
    max-height: 34px;
    padding: 0 18px;
    border-radius: 17px;
    font-size: 13px;
}}
QPushButton#dangerBtn:hover {{ background-color: {DANGER_HOVER}; }}
QPushButton#dangerBtn:disabled {{ background-color: #F5CACA; color: white; }}

QPushButton#grayTextBtn {{
    background-color: {BG_GRAY};
    color: {TEXT_GRAY};
    border: 1px solid {BORDER};
    min-height: 34px;
    max-height: 34px;
    padding: 0 14px;
    border-radius: 17px;
    font-size: 12px;
}}
QPushButton#grayTextBtn:hover {{ background-color: {BORDER}; color: {TEXT_LIGHT}; }}

/* ---------- 主题菜单 ---------- */
QMenu {{
    background-color: white;
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 10px;
    border-radius: 6px;
    font-size: 12px;
    color: {TEXT_DARK};
}}
QMenu::item:selected {{ background-color: {accent_light}; color: {accent}; }}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}
QMenu::indicator {{
    width: 14px;
    height: 14px;
    margin-left: 6px;
}}

/* ---------- 面板内标题 ---------- */
QLabel#sectionTitle {{
    font-size: 15px;
    font-weight: bold;
    color: {TEXT_DARK};
}}
QLabel#cardTitle {{
    font-size: 13px;
    font-weight: bold;
    color: {TEXT_DARK};
}}
QLabel#miniTitle {{
    font-size: 12px;
    font-weight: bold;
    color: {TEXT_DARK};
}}
QLabel#subtle {{
    color: {TEXT_GRAY};
    font-size: 11px;
}}
QLabel#subtleLight {{
    color: {TEXT_LIGHT};
    font-size: 11px;
}}
QLabel#infoName {{
    font-size: 13px;
    font-weight: bold;
    color: {TEXT_DARK};
}}
QLabel#pinkBold {{
    color: {accent};
    font-size: 12px;
    font-weight: bold;
}}
QLabel#small {{
    color: {TEXT_GRAY};
    font-size: 10px;
}}

/* ---------- 漫画列表（自绘委托） ---------- */
QListWidget#mangaList {{
    background: {BG_GRAY};
    border: none;
    outline: 0;
}}

/* ---------- 章节列表 ---------- */
QListWidget#chapterList {{
    background-color: {BG_GRAY};
    border: none;
    border-radius: 8px;
    outline: 0;
    padding: 4px 2px;
    font-size: 13px;
    color: {TEXT_LIGHT};
}}
QListWidget#chapterList::item {{
    color: {TEXT_LIGHT};
    padding: 5px 4px;
    border-radius: 6px;
    margin: 0 2px;
}}
QListWidget#chapterList::item:hover {{ background-color: #EDEFF1; }}
QListWidget#chapterList::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background-color: white;
    top: 2px;
}}
QListWidget#chapterList::indicator:hover {{ border-color: {BLUE}; }}
QListWidget#chapterList::indicator:checked {{
    background-color: {BLUE};
    border-color: {BLUE};
    image: url({check});
}}

QCheckBox {{
    font-size: 12px;
    color: {TEXT_LIGHT};
    spacing: 6px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background-color: white;
}}
QCheckBox::indicator:hover {{ border-color: {BLUE}; }}
QCheckBox::indicator:checked {{
    background-color: {BLUE};
    border-color: {BLUE};
    image: url({check});
}}

/* ---------- 进度条 ---------- */
QProgressBar {{
    background-color: {BORDER};
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
}}
QProgressBar::chunk {{ border-radius: 3px; }}
QProgressBar#chapterProgress::chunk {{ background-color: {BLUE}; }}
QProgressBar#totalProgress::chunk {{ background-color: {accent}; }}

/* ---------- 日志 ---------- */
QTextEdit#logBox {{
    background-color: {BG_GRAY};
    border: none;
    border-radius: 8px;
    font-family: "Consolas";
    font-size: 12px;
    color: {TEXT_LIGHT};
    padding: 4px;
}}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #C9CDD4;
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #C9CDD4;
    border-radius: 3px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {accent}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

QToolTip {{
    background-color: white;
    color: {TEXT_DARK};
    border: 1px solid {BORDER};
    padding: 4px 8px;
    font-size: 12px;
}}
"""
