import os
import sys
import json
import base64

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    PROJECT_ROOT = BASE_DIR
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(BASE_DIR)
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
COOKIE_DIR = os.path.join(BASE_DIR, "cookies")
COOKIE_FILE = os.path.join(COOKIE_DIR, "session.pkl")
FAVORITES_CACHE = os.path.join(BASE_DIR, "favorites_cache.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

if getattr(sys, 'frozen', False):
    _bundled = os.path.join(sys._MEIPASS, "option.yml")
    _external = os.path.join(BASE_DIR, "option.yml")
    OPTION_YML = _external if os.path.isfile(_external) else _bundled
else:
    OPTION_YML = os.path.join(PROJECT_ROOT, "option.yml")

DOWNLOAD_THREADS = 5
PDF_QUALITY = 85

try:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(COOKIE_DIR, exist_ok=True)
except OSError:
    pass


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def encode_pwd(s):
    return base64.b64encode(s.encode("utf-8")).decode("utf-8")


def decode_pwd(s):
    try:
        return base64.b64decode(s.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""
