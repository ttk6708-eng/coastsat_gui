from pathlib import Path
from PySide6.QtGui import QFont, QFontDatabase


def configure_application(application):
    application.setApplicationName('CoastSat Studio')
    application.setStyle('Fusion')
    font = Path(__file__).resolve().parents[1]/'assets'/'fonts'/'NotoSansKR.ttf'
    if font.is_file():
        identifier = QFontDatabase.addApplicationFont(str(font))
        families = QFontDatabase.applicationFontFamilies(identifier)
        if families:
            application.setFont(QFont(families[0],10))
