# [JMComic-PDF-GUI](https://github.com/DoYouNatureQ/JMComic-PDF-GUI) - 禁漫漫画下载 & PDF 合成图形化工具

基于 [JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python) 二次开发，在原有下载功能之上增加**图形化界面、账号登录、自动合成 PDF**。

## 主要功能

- **图形化界面**：登录、搜索、勾选章节、下载、PDF 合成，全流程点击完成
- **账号登录**：同步禁漫收藏夹，批量下载收藏漫画
- **PDF 自动合成**：下载完成后自动合并为 PDF，支持压缩质量调节；已下载但未转 PDF 的漫画可离线直接转换，支持分章节 / 完整版，并可勾选指定章节
- **主题色切换**：内置多套主题色，也可自定义取色，重启后保留
- **漫画信息保存**：自动保存标题、作者、标签、简介为 TXT
- **命令行模式**：按提示输入本子 ID 即可下载（继承自原项目）

## 安装

**直接[下载 JM漫画下载器.exe](https://github.com/DoYouNatureQ/JMComic-PDF-GUI/releases) 双击运行即可，无需配置环境。**

从源码运行需 Python >= 3.9：

```shell
pip install -r GUI/requirements.txt
```

## 快速上手

- **GUI（推荐）**：双击 `GUI/启动.bat`（或 `GUI/main.pyw`），登录（可选）→ 搜索漫画 → 勾选章节 → 一键下载
- **命令行**：双击 `AAA执行脚本.bat`，或执行 `python jm.py`，按提示输入本子 ID

## 配置文件

| 文件 | 用途 |
|------|------|
| `option.yml` | 单章节本子下载配置 |
| `option2.yml` | 多章节本子下载配置（每章独立子文件夹） |

可按需修改下载路径、图片格式等参数。

## 感谢

本项目基于 [hect0x7/JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python) 开发，感谢原作者的杰出工作。
