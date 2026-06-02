"""JMComic-PDF - 禁漫天堂漫画下载工具兼图像合成PDF

功能:
  - 登录获取收藏漫画数据
  - 自选漫画下载
  - 批量下载
  - 下载导出PDF
  - 图形化界面
"""

import sys
import os
import logging

logging.basicConfig(level=logging.DEBUG, format="[%(name)s] %(levelname)s: %(message)s")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    from gui.main_window import JMComicApp
    app = JMComicApp()
    app.mainloop()


if __name__ == "__main__":
    main()
