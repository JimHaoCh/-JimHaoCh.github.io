"""Scaled visual hierarchy for the shared preparation pages."""
def workflow_styles(scale):
    def px(n):
        return round(n * scale)
    def pt(n):
        return f'{n * scale:.2f}pt'
    return f'''
QWidget#setupCard {{
    background: #2a3442;
    border: 1px solid #526681;
    border-radius: {px(10)}px;
}}
QWidget#setupCard > QLabel {{ background: transparent; }}
QTabBar#modeSelector::tab {{
    background: #293442;
    color: #d5e7ff;
    border: 1px solid #6888b2;
    border-radius: {px(7)}px;
    min-height: {px(24)}px;
    padding: {px(2)}px {px(14)}px;
    font-size: {pt(11)};
    font-weight: 700;
}}
QTabBar#modeSelector::tab:selected {{
    background: #24486d;
    border: 2px solid #ffd166;
    color: #ffffff;
}}
QTabBar#modeSelector::tab:focus {{ border-color: #ffd166; }}
QLabel#pageTitle {{ font-size: {pt(15)}; font-weight: 800; color: #f4f8ff; }}
QLabel#cardTitle {{ font-size: {pt(11)}; font-weight: 700; color: #d5e7ff; }}
QLabel#diameterHeading {{ font-size: {pt(12)}; font-weight: 800; color: #ffffff; }}
QDoubleSpinBox#syringeValue {{
    background: #f5f8fc;
    color: #172434;
    font-size: {pt(14)};
    font-weight: 700;
    border: 2px solid #6888b2;
    border-radius: {px(8)}px;
    min-height: {px(34)}px;
    padding: {px(5)}px {px(8)}px;
    selection-background-color: #245ea6;
    selection-color: #ffffff;
}}
QDoubleSpinBox#syringeValue:focus {{ border: 3px solid #ffd166; }}
QDoubleSpinBox#syringeValue:disabled {{ background: #c0cbd9; color: #3a4b61; }}
QLineEdit {{
    background: #1c2532;
    color: #f4f7fb;
    border: 1px solid #6888b2;
    border-radius: {px(6)}px;
    min-height: {px(26)}px;
    padding: {px(4)}px {px(7)}px;
    selection-background-color: #245ea6;
}}
QPushButton#stepButton {{
    font-size: {pt(10)};
    min-height: {px(30)}px;
    padding-left: {px(5)}px;
    padding-right: {px(5)}px;
    background: #293442;
    border: 1px solid #6888b2;
}}
QPushButton#stepButton[current="true"] {{
    background: #24486d;
    color: #ffffff;
    border: 2px solid #ffd166;
}}
QPushButton#stepButton[complete="true"][current="false"] {{ border-color: #69c896; color: #c3efd6; }}
QLabel#liveStatus {{
    background: #26313f;
    color: #ecf2fa;
    padding: {px(4)}px {px(8)}px;
    border-radius: {px(5)}px;
    font-weight: 700;
}}
QTableWidget {{
    background: #243040;
    alternate-background-color: #2a3748;
    color: #f5f8fc;
    gridline-color: #647a96;
    border: 1px solid #647a96;
}}
QHeaderView::section {{ background: #33445a; color: #ffffff; padding: {px(5)}px; border: 0; }}
QPushButton:focus, QComboBox:focus, QLineEdit:focus {{ border: 2px solid #ffd166; }}
'''
