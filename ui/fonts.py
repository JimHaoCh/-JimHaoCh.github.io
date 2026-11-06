"""Load the bundled, unmodified OFL font in native and offscreen Qt alike."""
from PySide6.QtGui import QFont, QFontDatabase
from ne501.config import resource_path


def configure_ui_font(app) -> str:
    path = resource_path('assets/fonts/NotoSansCJKtc-Regular.otf')
    if not path.is_file():
        raise RuntimeError('UI font is missing. Run python build/fetch_ui_font.py before starting from source.')
    font_id = QFontDatabase.addApplicationFont(str(path))
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise RuntimeError('The bundled UI font could not be loaded.')
    app.setFont(QFont(families[0], 10))
    return families[0]
