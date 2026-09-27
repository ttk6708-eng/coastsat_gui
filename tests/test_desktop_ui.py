"""In-process screen regression checks; no browser or Google account is used."""
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest


class DesktopUITests(unittest.TestCase):
    def test_input_routes_do_not_require_login_or_raise(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'desktop_app.py')).run(timeout=40)
        self.assertFalse(app.exception)
        self.assertTrue(any(b.label == '파일 확인' for b in app.button))
        app.sidebar.radio[0].set_value('Google에서 영상 수집').run()
        self.assertFalse(app.exception)
        self.assertTrue(next(b for b in app.button if b.label == '위성영상 수집 시작').disabled)
        app.sidebar.radio[0].set_value('CoastSat 폴더 전처리').run()
        self.assertFalse(app.exception)
        self.assertFalse(next(b for b in app.button if b.label == '폴더 확인 및 전처리 시작').disabled)
