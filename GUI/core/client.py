import os
import json
import logging

import jmcomic
from config import OPTION_YML, DOWNLOAD_DIR, COOKIE_DIR, COOKIE_FILE

logger = logging.getLogger(__name__)


class ComicClient:
    ENGINE = "jmcomic"

    def __init__(self):
        self._option = self._build_option()
        self._client = self._option.new_jm_client()
        self._proxy = self._detect_proxy()
        self._session_username = self._load_session()

    @property
    def option(self):
        return self._option

    @property
    def client(self):
        return self._client

    @property
    def proxy(self):
        return self._proxy

    @property
    def session_username(self):
        return self._session_username

    def _load_session(self):
        """启动时恢复上次登录的会话cookie，实现自动登录。"""
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            cookies = data.get("cookies") or {}
            if cookies.get("AVS"):
                self._client["cookies"] = cookies
                return data.get("username", "")
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
            pass
        return ""

    def save_session(self, username=""):
        """登录成功后把会话cookie持久化，供下次启动自动登录。"""
        try:
            cookies = dict(self._client.get_meta_data("cookies") or {})
            if not cookies.get("AVS"):
                logger.warning("当前会话无AVS凭证，跳过保存")
                return
            os.makedirs(COOKIE_DIR, exist_ok=True)
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump({"username": username, "cookies": cookies}, f,
                          ensure_ascii=False)
        except OSError as e:
            logger.warning("保存登录会话失败: %s", e)

    def clear_session(self):
        try:
            os.remove(COOKIE_FILE)
        except OSError:
            pass

    def _build_option(self):
        if os.path.isfile(OPTION_YML):
            option = jmcomic.create_option_by_file(OPTION_YML)
        else:
            option = jmcomic.JmOption.default()

        option.dir_rule.base_dir = DOWNLOAD_DIR
        option.dir_rule.rule_dsl = "Bd / (JM{Aid}) {Atitle} / [{Pindex:03d}] {Ptitle}"
        option.dir_rule.parser_list = option.dir_rule.get_rule_parser_list(option.dir_rule.rule_dsl)
        return option

    def _detect_proxy(self):
        try:
            meta = self._option.client.postman.meta_data.src_dict
            proxies = meta.get("proxies", None)
            if proxies:
                return proxies.get("https", proxies.get("http", None))
        except Exception:
            pass

        env_proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("ALL_PROXY")
        )
        return env_proxy
