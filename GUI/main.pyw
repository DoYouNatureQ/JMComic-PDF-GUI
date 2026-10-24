import sys, os, ctypes

if getattr(sys, 'frozen', False):
    BASE = os.path.dirname(sys.executable)
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from gui.main_window import JMComicApp

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("JMComic-PDF")
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JMComic.PDF")
    icon = os.path.join(sys._MEIPASS, "icon.ico") if getattr(sys, "frozen", False) else os.path.join(BASE, "icon.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    window = JMComicApp()
    window.show()
    sys.exit(app.exec())
