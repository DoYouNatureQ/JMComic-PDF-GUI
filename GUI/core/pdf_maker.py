import os
import io
import re
import glob

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

    def make_single_chapter_pdf(self, manga_title, chapter_title, download_dir=None):
        if download_dir is None:
            download_dir = DOWNLOAD_DIR

        manga_dir = self._find_manga_dir(manga_title, download_dir)
        if not manga_dir:
            raise ValueError(f"漫画目录不存在: {manga_title}")

        chapter_dir = None
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

        images = _collect_images(chapter_dir)
        if not images:
            raise ValueError(f"章节文件夹无图片: {os.path.basename(chapter_dir)}")

        safe_chapter = _sanitize(os.path.basename(chapter_dir))
        pdf_name = f"{safe_chapter}.pdf"
        pdf_path = os.path.join(manga_dir, pdf_name)
        self.make_pdf(images, pdf_path, title=os.path.basename(chapter_dir))
        return pdf_path

    def make_chapter_pdfs(self, manga_title, download_dir=None):
        if download_dir is None:
            download_dir = DOWNLOAD_DIR

        manga_dir = self._find_manga_dir(manga_title, download_dir)
        if not manga_dir:
            raise ValueError(f"漫画目录不存在: {manga_title}")

        chapter_dirs = sorted([
            d for d in os.listdir(manga_dir)
            if os.path.isdir(os.path.join(manga_dir, d))
        ])

        if not chapter_dirs:
            images = _collect_images(manga_dir)
            if images:
                safe_title = _sanitize(manga_title)
                pdf_path = os.path.join(manga_dir, f"{safe_title}.pdf")
                self.make_pdf(images, pdf_path, title=manga_title)
                return [pdf_path]
            raise ValueError("没有找到章节文件夹或图片文件")

        pdf_outputs = []
        for chapter_dir in chapter_dirs:
            full_dir = os.path.join(manga_dir, chapter_dir)
            images = _collect_images(full_dir)
            if not images:
                continue

            safe_chapter = _sanitize(chapter_dir)
            pdf_name = f"{safe_chapter}.pdf"
            pdf_path = os.path.join(manga_dir, pdf_name)

            try:
                self.make_pdf(images, pdf_path, title=chapter_dir)
                pdf_outputs.append(pdf_path)
            except Exception as e:
                print(f"生成PDF失败 [{chapter_dir}]: {e}")

        return pdf_outputs

    def make_full_pdf(self, manga_title, download_dir=None):
        if download_dir is None:
            download_dir = DOWNLOAD_DIR

        manga_dir = self._find_manga_dir(manga_title, download_dir)
        if not manga_dir:
            raise ValueError(f"漫画目录不存在: {manga_title}")

        chapter_dirs = sorted([
            d for d in os.listdir(manga_dir)
            if os.path.isdir(os.path.join(manga_dir, d))
        ])

        all_images = []
        if chapter_dirs:
            for chapter_dir in chapter_dirs:
                full_dir = os.path.join(manga_dir, chapter_dir)
                all_images.extend(_collect_images(full_dir))
        else:
            all_images = _collect_images(manga_dir)

        if not all_images:
            raise ValueError("没有找到图片文件")

        safe_title = _sanitize(manga_title)
        pdf_path = os.path.join(manga_dir, f"{safe_title}_完整版.pdf")
        self.make_pdf(all_images, pdf_path, title=manga_title)
        return pdf_path

    @staticmethod
    def _find_manga_dir(manga_title, download_dir):
        if not os.path.isdir(download_dir):
            return None

        for item in os.listdir(download_dir):
            item_path = os.path.join(download_dir, item)
            if os.path.isdir(item_path) and manga_title in item:
                return item_path

        safe = _sanitize(manga_title)
        for item in os.listdir(download_dir):
            item_path = os.path.join(download_dir, item)
            if os.path.isdir(item_path) and safe in item:
                return item_path

        return None


def _collect_images(directory):
    patterns = ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif"]
    images = set()
    for pat in patterns:
        images.update(glob.glob(os.path.join(directory, pat)))

    images = sorted(images, key=lambda x: (
        int(re.search(r'(\d+)', os.path.basename(x)).group(1))
        if re.search(r'(\d+)', os.path.basename(x)) else 0
    ))
    return images


def _sanitize(name):
    name = name or "unknown"
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name.strip().strip('.')[:200]
