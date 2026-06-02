import sys, os, ctypes

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

from gui.main_window import JMComicApp

if __name__ == "__main__":
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JMComic.PDF")
    JMComicApp().mainloop()
