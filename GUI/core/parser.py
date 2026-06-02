import re
import logging
from core.client import ComicClient

logger = logging.getLogger(__name__)


class MangaParser:
    def __init__(self, client: ComicClient):
        self._comic_client = client

    @property
    def jm_client(self):
        return self._comic_client.client

    def parse_favorites(self, page=1, username=""):
        try:
            fav_page = self.jm_client.favorite_folder(page=page, username=username)
        except Exception as e:
            logger.error("获取收藏页 %d 失败: %s", page, e)
            return [], False

        favorites = []
        for album_id, info in fav_page.content:
            name = info.get("name", "")
            author = ""
            if "author" in info:
                a = info["author"]
                author = a if isinstance(a, str) else ", ".join(a) if isinstance(a, list) else ""
            favorites.append({
                "id": str(album_id),
                "title": name,
                "cover": "",
                "url": str(album_id),
                "author": author,
            })

        has_next = len(fav_page.content) > 0 and page < fav_page.page_count
        return favorites, has_next

    def parse_all_favorites(self, max_pages=20, username=""):
        all_favorites = []
        for page in range(1, max_pages + 1):
            favs, has_next = self.parse_favorites(page, username)
            all_favorites.extend(favs)
            if not has_next or not favs:
                break
        return all_favorites

    def parse_manga_detail(self, url_or_id):
        album_id = self._extract_id(url_or_id)
        try:
            album = self.jm_client.get_album_detail(album_id)
        except Exception as e:
            logger.error("获取本子详情失败 [%s]: %s", album_id, e)
            raise

        chapters = []
        for photo_id, photo_index, photo_title in album.episode_list:
            chapters.append({
                "id": str(photo_id),
                "title": photo_title,
                "url": str(photo_id),
            })

        author = ", ".join(album.authors) if album.authors else ""

        return {
            "title": album.name,
            "cover": "",
            "author": author,
            "description": album.description or "",
            "update_time": album.update_date or "",
            "chapters": chapters,
        }

    def find_manga(self, keyword, page=1):
        try:
            search_page = self.jm_client.search_site(keyword, page=page)
        except Exception as e:
            logger.error("搜索失败 [%s]: %s", keyword, e)
            return [], False

        results = []
        for album_id, info in search_page.content:
            name = info.get("name", "")
            author = ""
            if "author" in info:
                a = info["author"]
                author = a if isinstance(a, str) else ", ".join(a) if isinstance(a, list) else ""
            results.append({
                "id": str(album_id),
                "title": name,
                "cover": "",
                "url": str(album_id),
                "author": author,
            })

        has_next = len(search_page.content) > 0 and page < search_page.page_count
        return results, has_next

    @staticmethod
    def _extract_id(url_or_id):
        if isinstance(url_or_id, (int, float)):
            return str(int(url_or_id))
        s = str(url_or_id).strip()
        if s.isdigit():
            return s
        m = re.search(r'(\d{4,})', s)
        if m:
            return m.group(1)
        return s
