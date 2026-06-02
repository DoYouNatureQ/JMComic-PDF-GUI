import jmcomic
import json
import os
import shutil
import img2pdf
from PIL import Image
import io # 新增：用于内存操作

# Define a custom exception to gracefully handle the end of a processing cycle,
class ProcessingCycleEnd(Exception):
    pass

# --- 统一的、最灵活的PDF生成函数 (新增图片压缩功能) ---
def convert_to_pdf(image_source_folder, pdf_save_path, quality=85):
    """
    将图片合并为PDF，并提供图片质量压缩选项来减小文件大小。

    :param image_source_folder: 图片源文件夹。
    :param pdf_save_path: 完整的PDF保存路径。
    :param quality: 压缩质量 (1-100)，数值越小体积越小但质量越低。设为None则不压缩。
    """
    if not os.path.isdir(image_source_folder): return

    pdf_save_dir = os.path.dirname(pdf_save_path)
    try:
        os.makedirs(pdf_save_dir, exist_ok=True)
    except OSError as e:
        print(f"  - [PDF创建失败] 创建目录时出错: {e}")
        return

    image_files = []
    supported_formats = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')
    for f in os.listdir(image_source_folder):
        file_path = os.path.join(image_source_folder, f)
        if os.path.isfile(file_path) and f.lower().endswith(supported_formats):
            image_files.append(file_path)
    image_files.sort()

    if not image_files:
        print(f"  - [转换警告] 未在文件夹内找到图片: {os.path.basename(image_source_folder)}")
        return

    try:
        if quality is not None:
            # 如果启用了压缩，处理图片并将其转为内存中的二进制数据
            compressed_images = []
            for file_path in image_files:
                img = Image.open(file_path)
                # 转换有透明度的PNG为RGB，否则无法保存为JPG
                if img.mode == 'RGBA':
                    img = img.convert('RGB')
                
                # 使用内存中的 BytesIO 对象来暂存压缩后的图片数据
                with io.BytesIO() as buffer:
                    img.save(buffer, format='JPEG', quality=quality)
                    compressed_images.append(buffer.getvalue())
            
            # 将内存中的图片数据列表传递给 img2pdf
            pdf_bytes = img2pdf.convert(compressed_images)
        else:
            # 不压缩，直接使用原始文件路径
            pdf_bytes = img2pdf.convert(image_files)

        with open(pdf_save_path, "wb") as f:
            f.write(pdf_bytes)
        print(f"  - [转换成功] {os.path.basename(pdf_save_path)} 已保存")
            
    except Exception as e:
        print(f"  - [转换失败] 创建PDF时出错: {e}")


# --- 统一的、保存本子信息为 TXT 的函数 (修正作者名拼接) ---
def save_album_info_to_txt(album_detail, txt_save_path):
    try:
        os.makedirs(os.path.dirname(txt_save_path), exist_ok=True)
        content = [
            f"标题：{album_detail.title}",
            f"ID：JM{album_detail.id}",
            f"作者：{''.join(album_detail.author)}", # 使用空字符串拼接，去除逗号
            "\n" + "="*20 + "\n",
        ]
        if album_detail.tags:
            content.append("标签：")
            tag_lines = []
            for i in range(0, len(album_detail.tags), 5):
                tag_lines.append("  ".join(album_detail.tags[i:i+5]))
            content.append("\n".join(tag_lines))
            content.append("\n" + "="*20 + "\n")
        if hasattr(album_detail, 'description') and album_detail.description:
            content.append("简介：")
            content.append(album_detail.description)
        with open(txt_save_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(content))
        print(f"  - [信息保存成功] {os.path.basename(txt_save_path)} 已保存")
    except Exception as e:
        print(f"  - [信息保存失败] 创建 TXT 文件时出错: {e}")


# Main loop to allow restarting the process.
while True:
    try:
        print("\n" + "="*50 + "\n")
        album_id_str = input("请输入要下载的本子ID: ")
        try:
            album_id = int(album_id_str)
        except ValueError:
            raise ProcessingCycleEnd("输入的本子ID无效，请输入一个数字。")

        print(f"\n正在获取本子 {album_id} 的详细信息和章节列表...")
        print("-" * 50)

        client = jmcomic.JmOption.default().new_jm_client()
        album_detail = client.get_album_detail(album_id)
        all_chapters_info = album_detail.episode_list

        if not all_chapters_info:
            raise ProcessingCycleEnd("未找到该本子的任何章节。")

        desired_chapter_ids = [item[0] for item in all_chapters_info]
        
        if len(all_chapters_info) == 1:
            # --- 单章节工作流 ---
            print("检测到为【单章节】本子，将加载 'option.yml' 并采用单文件夹模式。")
            option = jmcomic.create_option_by_file('option.yml')
            base_dir = option.dir_rule.base_dir
            album_folder_name = f"(JM{album_id}) {album_detail.title}"
            album_folder_path = os.path.join(base_dir, album_folder_name)
            
            print(f"\n图片将保存在: {album_folder_path}")
            print("-" * 50)
            
            jmcomic.download_album(album_id, option)
            
            print("\n" + "="*50 + "\n下载完成！")
            
            print("\n开始进行下载后处理...")
            output_folder = os.path.join(album_folder_path, "PDF")
            print(f"PDF和信息文件将被保存在: {output_folder}")

            txt_path = os.path.join(output_folder, '简介.txt')
            save_album_info_to_txt(album_detail, txt_path)

            pdf_save_path = os.path.join(output_folder, f"{album_folder_name}.pdf")
            convert_to_pdf(album_folder_path, pdf_save_path, quality=85)

        else:
            # --- 多章节工作流 ---
            print(f"检测到为【多章节】本子 (共 {len(all_chapters_info)} 章)，将加载 'option2.yml' 并采用子文件夹模式。")
            user_choice = input("直接回车将下载全部章节，输入 '1' 则返回并重新输入ID: ")
            
            if user_choice == '1':
                print("操作已取消，请重新输入ID。")
                continue

            option = jmcomic.create_option_by_file('option2.yml')
            print("\n好的，将下载全部章节。")

            base_dir = option.dir_rule.base_dir
            album_folder_name = f"(JM{album_id}) {album_detail.title}"
            album_folder_path = os.path.join(base_dir, album_folder_name)

            print(f"\n本子将保存在总文件夹: {album_folder_path}")
            print("-" * 50)
            
            chapter_index_map = {item[0]: str(i) for i, item in enumerate(all_chapters_info, start=1)}
            jmcomic.JmModuleConfig.PFIELD_ADVICE['index'] = lambda photo: chapter_index_map.get(photo.photo_id, str(photo.album_index))

            option.user_data = {"desired_chapter_ids": desired_chapter_ids, "mode": "select_chapters"}
            jmcomic.download_album(album_id, option)
            jmcomic.JmModuleConfig.PFIELD_ADVICE.pop('index', None)
            
            print("\n" + "="*50 + "\n所有指定章节下载完成！")

            print("\n开始进行下载后处理...")
            if not os.path.isdir(album_folder_path):
                print(f"错误：找不到本子总文件夹: {album_folder_path}")
            else:
                output_folder = os.path.join(album_folder_path, "PDF")
                print(f"所有PDF和信息文件将被保存在: {output_folder}")

                txt_path = os.path.join(output_folder, '简介.txt')
                save_album_info_to_txt(album_detail, txt_path)

                discovered_chapter_folders = []
                for item_name in os.listdir(album_folder_path):
                    item_path = os.path.join(album_folder_path, item_name)
                    if os.path.isdir(item_path) and item_name.upper() != "PDF":
                        discovered_chapter_folders.append(item_path)

                if not discovered_chapter_folders:
                    print("警告：未在总文件夹内扫描到任何章节子文件夹。")
                else:
                    for chapter_path in discovered_chapter_folders:
                        pdf_filename = os.path.basename(chapter_path) + ".pdf"
                        pdf_save_path = os.path.join(output_folder, pdf_filename)
                        convert_to_pdf(chapter_path, pdf_save_path, quality=85)
        
        print("\n所有文件已处理完毕！")

    except ProcessingCycleEnd as e:
        print(str(e))
    except Exception as e:
        print(f"\n获取本子详情或下载时发生错误: {e}")
        print("-" * 50)

    print("\n" + "="*50 + "\n")
    user_choice = input("处理完后，回车退出程序，输入数字1重新开始。")
    if user_choice == '1':
        continue
    else:
        break