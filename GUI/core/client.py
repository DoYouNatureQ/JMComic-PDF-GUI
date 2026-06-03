import os
import logging

import jmcomic
from config import OPTION_YML, DOWNLOAD_DIR

logger = logging.getLogger(__name__)


class ComicClient:
    ENGINE = "jmcomic"

    def __init__(self):
        self._option = self._build_option()
        self._client = self._option.new_jm_client()
        self._proxy = self._detect_proxy()

    @property
    def option(self):
        return self._option

    @property
    def client(self):
        return self._client

    @property
    def proxy(self):
        return self._proxy

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
