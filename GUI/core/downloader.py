import threading
import logging

import jmcomic
from jmcomic import JmDownloader, JmAlbumDetail, JmPhotoDetail, JmImageDetail

from core.client import ComicClient

logger = logging.getLogger(__name__)


class _ProgressDownloader(JmDownloader):

    def __init__(self, option, on_progress=None, on_status=None, cancel_flag=None):
        super().__init__(option)
        self._on_progress = on_progress
        self._on_status = on_status
        self._cancel_flag = cancel_flag
        self._current_photo_index = 0
        self._total_photos = 0
        self._current_image_index = 0
        self._total_images = 0
        self._manga_title = ""

    def before_album(self, album: JmAlbumDetail):
        super().before_album(album)
        self._total_photos = len(album)
        self._current_photo_index = 0
        self._manga_title = album.name
        if self._on_status:
            self._on_status(f"开始下载: {album.name} (共{self._total_photos}章)")

    def before_photo(self, photo: JmPhotoDetail):
        if self._cancel_flag and self._cancel_flag.is_set():
            photo.skip = True
            return
        super().before_photo(photo)
        self._current_photo_index += 1
        self._total_images = len(photo)
        self._current_image_index = 0
        if self._on_status:
            self._on_status(
                f"下载章节 [{self._current_photo_index}/{self._total_photos}]: {photo.name}"
            )

    def after_image(self, image: JmImageDetail, img_save_path):
        super().after_image(image, img_save_path)
        self._current_image_index += 1
        if self._on_progress:
            self._on_progress(
                self._current_photo_index,
                self._total_photos,
                self._current_image_index,
                self._total_images,
                self._manga_title,
            )

    def before_image(self, image: JmImageDetail, img_save_path):
        if self._cancel_flag and self._cancel_flag.is_set():
            image.skip = True
            return
        super().before_image(image, img_save_path)


class Downloader:
    def __init__(self, client: ComicClient, threads=None):
        self._comic_client = client
        self._cancel_flag = threading.Event()
        self._progress_callbacks = []
        self._status_callbacks = []

    def on_progress(self, callback):
        self._progress_callbacks.append(callback)

    def on_status(self, callback):
        self._status_callbacks.append(callback)

    def cancel(self):
        self._cancel_flag.set()

    def reset_cancel(self):
        self._cancel_flag.clear()

    def _report_progress(self, chapter_index, chapter_total, page_index, page_total, manga_title):
        for cb in self._progress_callbacks:
            try:
                cb(chapter_index, chapter_total, page_index, page_total, manga_title)
            except Exception:
                pass

    def _report_status(self, message):
        for cb in self._status_callbacks:
            try:
                cb(message)
            except Exception:
                pass

    def download_chapter(self, manga_info, chapter_info, base_dir=None):
        album_id = manga_info.get("id", "")
        chapter_id = chapter_info.get("id", "")
        if not album_id or not chapter_id:
            self._report_status("无效的漫画或章节ID")
            return

        option = self._comic_client.option.copy_option()
        if base_dir:
            option.dir_rule.base_dir = base_dir

        try:
            jmcomic.download_photo(int(chapter_id), option)
            self._report_status(f"章节下载完成: {chapter_info.get('title', chapter_id)}")
        except Exception as e:
            self._report_status(f"章节下载出错: {e}")
            logger.error("章节下载出错 [%s/%s]: %s", album_id, chapter_id, e)
            raise
