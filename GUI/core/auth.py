import logging
from core.client import ComicClient

logger = logging.getLogger(__name__)


class Authenticator:
    def __init__(self, client: ComicClient):
        self._comic_client = client
        self._logged_in = False
        self._username = None

    @property
    def is_logged_in(self):
        return self._logged_in

    @property
    def username(self):
        return self._username

    def try_auto_login(self):
        try:
            page = self._comic_client.client.favorite_folder(page=1)
            if page and len(page.content) >= 0:
                self._logged_in = True
                self._username = ""
                return True, "自动登录成功(已有有效会话)"
        except Exception:
            pass
        return False, "未找到有效会话，请手动登录"

    def login(self, username, password):
        try:
            self._comic_client.client.login(username, password)
            self._logged_in = True
            self._username = username
            return True, "登录成功"
        except Exception as e:
            logger.error("登录失败: %s", e)
            return False, f"登录失败: {e}"

    def verify_session_valid(self):
        try:
            page = self._comic_client.client.favorite_folder(page=1)
            return page is not None
        except Exception:
            return False

    def logout(self):
        self._logged_in = False
        self._username = None
        try:
            self._comic_client._option = self._comic_client._build_option()
            self._comic_client._client = self._comic_client._option.new_jm_client()
        except Exception:
            pass
        return True, "已退出登录"
