import os
import io
import re

import img2pdf
from PIL import Image

from config import DOWNLOAD_DIR, PDF_QUALITY


class PdfMaker:
    def __init__(self, quality=None):
        self.quality = quality or PDF_QUALITY

    def make_pdf(self, image_paths, output_path, title=""):
        if not image_paths:
            raise ValueError("没有图片可合成PDF")

        valid_paths = [p for p in image_paths if os.path.exists(p)]
        if not valid_paths:
            raise ValueError("没有有效的图片文件")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if self.quality is not None:
            compressed_images = []
            for file_path in valid_paths:
                img = Image.open(file_path)
                if img.mode == 'RGBA':
                    img = img.convert('RGB')
                elif img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')

                with io.BytesIO() as buffer:
                    img.save(buffer, format='JPEG', quality=self.quality)
                    compressed_images.append(buffer.getvalue())

            pdf_bytes = img2pdf.convert(compressed_images)
        else:
            pdf_bytes = img2pdf.convert(valid_paths)

        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

        return output_path

    def make_single_chapter_pdf(self, manga_title, chapter_title, download_dir=None, chapter_dir=None):
        if download_dir is None:
            download_dir = DOWNLOAD_DIR

        if chapter_dir:
            chapter_dir = os.path.normpath(chapter_dir)
            if not os.path.isdir(chapter_dir):
                raise ValueError(f"章节目录不存在: {chapter_dir}")
        else:
            manga_dir = self._find_manga_dir(manga_title, download_dir)
            if not manga_dir:
                raise ValueError(f"漫画目录不存在: {manga_title}")

            for d in sorted(os.listdir(manga_dir)):
                full = os.path.join(manga_dir, d)
                if os.path.isdir(full) and chapter_title in d:
                    chapter_dir = full
                    break

            if not chapter_dir:
                all_dirs = [d for d in os.listdir(manga_dir) if os.path.isdir(os.path.join(manga_dir, d))]
                if all_dirs:
                    chapter_dir = os.path.join(manga_dir, sorted(all_dirs)[-1])

            if not chapter_dir:
                raise ValueError(f"未找到章节文件夹: {chapter_title}")

        manga_dir = os.path.dirname(chapter_dir)

        images = _collect_images(chapter_dir)
        if not images:
            raise ValueError(f"章节文件夹无图片: {os.path.basename(chapter_dir)}")

        safe_chapter = _sanitize(os.path.basename(chapter_dir))
        pdf_name = f"{safe_chapter}.pdf"
        pdf_path = os.path.join(manga_dir, pdf_name)
        self.make_pdf(images, pdf_path, title=os.path.basename(chapter_dir))
        return pdf_path

    def make_chapter_pdfs(self, manga_title, download_dir=None,
                          manga_id=None, chapter_titles=None):
        """把已下载的章节图片转换为PDF。

        chapter_titles 为 None 时转换磁盘上全部章节；
        指定 chapter_titles 时只转换能找到的章节，找不到的标题放入返回的
        missing 列表（不报错，由调用方决定是否提示下载）。

        返回 (pdf_outputs, missing_titles)。
        """
        if download_dir is None:
            download_dir = DOWNLOAD_DIR

        manga_dir = self._find_manga_dir(manga_title, download_dir,
                                         manga_id=manga_id)
        if not manga_dir:
            raise ValueError(f"漫画目录不存在: {manga_title}")

        chapter_dirs, missing = self._find_chapter_dirs(manga_dir,
                                                        chapter_titles)

        if chapter_titles is None and not chapter_dirs:
            images = _collect_images(manga_dir)
            if images:
                safe_title = _sanitize(manga_title)
                pdf_path = os.path.join(manga_dir, f"{safe_title}.pdf")
                self.make_pdf(images, pdf_path, title=manga_title)
                return [pdf_path], []
            raise ValueError("没有找到章节文件夹或图片文件")

        pdf_outputs = []
        for chapter_dir in chapter_dirs:
            images = _collect_images(chapter_dir)
            if not images:
                continue

            safe_chapter = _sanitize(os.path.basename(chapter_dir))
            pdf_name = f"{safe_chapter}.pdf"
            pdf_path = os.path.join(manga_dir, pdf_name)

            try:
                self.make_pdf(images, pdf_path,
                              title=os.path.basename(chapter_dir))
                pdf_outputs.append(pdf_path)
            except Exception as e:
                print(f"生成PDF失败 [{chapter_dir}]: {e}")

        return pdf_outputs, missing

    def make_full_pdf(self, manga_title, download_dir=None,
                      manga_id=None, chapter_titles=None):
        """把已下载的章节图片合并为一个完整版PDF。

        指定 chapter_titles 时只合并这些章节的图片（按给出顺序），
        找不到的标题放入返回的 missing 列表。

        返回 (pdf_path, missing_titles)。
        """
        if download_dir is None:
            download_dir = DOWNLOAD_DIR

        manga_dir = self._find_manga_dir(manga_title, download_dir,
                                         manga_id=manga_id)
        if not manga_dir:
            raise ValueError(f"漫画目录不存在: {manga_title}")

        chapter_dirs, missing = self._find_chapter_dirs(manga_dir,
                                                        chapter_titles)

        if chapter_titles and not chapter_dirs:
            # 勾选的章节一个都没下载过，直接返回缺失列表，由界面提示
            return None, missing

        all_images = []
        if chapter_dirs:
            for chapter_dir in chapter_dirs:
                all_images.extend(_collect_images(chapter_dir))
        else:
            all_images = _collect_images(manga_dir)

        if not all_images:
            raise ValueError("没有找到图片文件")

        safe_title = _sanitize(manga_title)
        if chapter_titles:
            # 勾选章节的合并版单独命名，避免覆盖全量完整版PDF
            pdf_path = os.path.join(
                manga_dir, f"{safe_title}_合并{len(chapter_dirs)}章.pdf")
        else:
            pdf_path = os.path.join(manga_dir, f"{safe_title}_完整版.pdf")
        self.make_pdf(all_images, pdf_path, title=manga_title)
        return pdf_path, missing

    def check_downloaded_chapters(self, manga_title, chapter_titles,
                                  download_dir=None, manga_id=None):
        """检查章节是否已下载（本地存在对应章节文件夹）。

        返回 (已下载章节标题列表, 未下载章节标题列表)。
        """
        if download_dir is None:
            download_dir = DOWNLOAD_DIR

        manga_dir = self._find_manga_dir(manga_title, download_dir,
                                         manga_id=manga_id)
        if not manga_dir:
            return [], list(chapter_titles)

        _dirs, missing = self._find_chapter_dirs(manga_dir,
                                                 list(chapter_titles))
        missing_set = set(missing)
        found = [t for t in chapter_titles if t not in missing_set]
        return found, missing

    @staticmethod
    def _find_manga_dir(manga_title, download_dir, manga_id=None):
        if not os.path.isdir(download_dir):
            return None

        items = os.listdir(download_dir)

        # 漫画ID不随标题变动，优先按下载时生成的 "(JM{id})" 前缀匹配
        if manga_id:
            prefix = f"(JM{manga_id})"
            for item in items:
                item_path = os.path.join(download_dir, item)
                if os.path.isdir(item_path) and item.startswith(prefix):
                    return item_path

        candidates = [manga_title]
        safe = _sanitize(manga_title)
        if safe != manga_title:
            candidates.append(safe)
        for cand in candidates:
            for item in items:
                item_path = os.path.join(download_dir, item)
                if os.path.isdir(item_path) and cand in item:
                    return item_path

        return None

    @staticmethod
    def _find_chapter_dirs(manga_dir, chapter_titles=None):
        """解析章节目录。

        chapter_titles 为 None 时返回磁盘上全部章节目录（按名称排序）；
        否则按标题逐个匹配章节文件夹（文件夹名为 "[NNN] 标题"），
        返回 (匹配到的目录列表(按标题顺序), 未匹配到的标题列表)。
        """
        all_dirs = sorted([
            d for d in os.listdir(manga_dir)
            if os.path.isdir(os.path.join(manga_dir, d))
        ])

        if chapter_titles is None:
            return [os.path.join(manga_dir, d) for d in all_dirs], []

        found_dirs, missing = [], []
        for title in chapter_titles:
            variants = [title]
            safe = _sanitize(title)
            if safe != title:
                variants.append(safe)
            match = None
            for d in all_dirs:
                if any(v and v in d for v in variants):
                    match = os.path.join(manga_dir, d)
                    break
            if match:
                found_dirs.append(match)
            else:
                missing.append(title)
        return found_dirs, missing


def _collect_images(directory):
    exts = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
    images = []
    try:
        for f in os.listdir(directory):
            path = os.path.join(directory, f)
            if os.path.isfile(path) and os.path.splitext(f)[1].lower() in exts:
                images.append(path)
    except OSError:
        return []

    images.sort(key=lambda x: (
        int(re.search(r'(\d+)', os.path.basename(x)).group(1))
        if re.search(r'(\d+)', os.path.basename(x)) else 0
    ))
    return images


def _sanitize(name):
    name = name or "unknown"
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name.strip().strip('.')[:200]
