from __future__ import annotations


def build_stylesheet(scale: float = 1.0) -> str:
    """Build the application stylesheet at the requested UI text scale."""
    scale = max(0.8, min(1.35, float(scale)))

    def pt(value: float) -> str:
        return f"{value * scale:.2f}pt"

    # Pixel dimensions are also scaled slightly so larger text keeps adequate
    # touch targets and does not get clipped inside buttons/controls.
    def px(value: int) -> int:
        return max(1, round(value * scale))

    return f"""
QMainWindow, QWidget {{
    font-size: {pt(10.0)};
}}
QWidget {{
    background-color: #1f232a;
    color: #e8edf3;
}}
QGroupBox#pumpPanel {{
    background-color: #262c35;
    border: 1px solid #3a4350;
    border-radius: {px(10)}px;
    margin-top: {px(14)}px;
    padding: {px(12)}px;
    font-weight: 600;
}}
QGroupBox#pumpPanel[online="true"][diameterVerified="false"] {{
    border: 2px solid #d59a2f;
}}
QGroupBox#pumpPanel[active="true"] {{
    border: 2px solid #4d7cff;
}}
QGroupBox#pumpPanel[running="true"] {{
    border: 2px solid #24a148;
}}
QGroupBox#pumpPanel::title {{
    subcontrol-origin: margin;
    left: {px(12)}px;
    padding: 0 {px(6)}px;
    font-size: {pt(11.5)};
    color: #f5f7fa;
}}
QLabel {{
    background: transparent;
}}
QLabel#onlineStatus, QLabel#successLabel {{
    color: #38c172;
    font-weight: 700;
}}
QLabel#offlineStatus, QLabel#warningLabel {{
    color: #ff7b72;
    font-weight: 700;
}}
QLabel#secondaryLabel {{
    color: #9aa4b2;
}}
QLabel#workflowBanner {{
    background-color: #253752;
    color: #d9e8ff;
    border: 1px solid #4777b8;
    border-radius: {px(8)}px;
    padding: {px(7)}px {px(11)}px;
    font-weight: 800;
}}
QLabel#diameterRequiredBanner {{
    background-color: #5a3d12;
    color: #ffd166;
    border: 1px solid #d59a2f;
    border-radius: {px(8)}px;
    padding: {px(7)}px {px(9)}px;
    font-weight: 800;
}}
QLabel#diameterReadyBanner {{
    background-color: #153d2a;
    color: #69db9b;
    border: 1px solid #2f9e62;
    border-radius: {px(8)}px;
    padding: {px(7)}px {px(9)}px;
    font-weight: 800;
}}
QPushButton {{
    min-height: {px(30)}px;
    padding: {px(4)}px {px(11)}px;
    border-radius: {px(8)}px;
    border: 1px solid #46505f;
    background-color: #313844;
    color: #f5f7fa;
    font-weight: 600;
}}
QPushButton:hover {{ background-color: #394252; }}
QPushButton:pressed {{ background-color: #2a303a; }}
QPushButton:disabled {{
    background-color: #232932;
    color: #7d8794;
    border-color: #353d49;
}}
QPushButton#secondaryButton {{ background-color: #2b3340; }}
QPushButton#connectButton {{ background-color: #245ea6; border-color: #2c6cc2; }}
QPushButton#connectButton:hover {{ background-color: #2b6dbe; }}
QPushButton#diameterButton {{
    background-color: #b97812;
    border-color: #e3a12d;
    color: white;
    font-weight: 800;
}}
QPushButton#diameterButton:hover {{ background-color: #cc8817; }}
QPushButton#diameterButton:pressed {{ background-color: #99620e; }}
QPushButton#diameterButton:disabled {{
    background-color: #3a3020;
    border-color: #5a4a2c;
    color: #9b907f;
}}
QPushButton#applyButton {{ background-color: #2463d3; border-color: #3575e6; color: white; }}
QPushButton#applyButton:hover {{ background-color: #2f73ee; }}
QPushButton#applyButton:disabled {{
    background-color: #24334a;
    border-color: #3b4a60;
    color: #8494ab;
}}
QPushButton#runButton {{
    background-color: #1f8f4d;
    border-color: #2fb367;
    color: white;
    font-weight: 800;
}}
QPushButton#runButton:hover {{ background-color: #24a148; }}
QPushButton#runButton:pressed {{ background-color: #1a7b3a; }}
QPushButton#runButton:disabled {{
    background-color: #243529;
    border-color: #33503d;
    color: #8aa196;
}}
QPushButton#stopButton {{
    background-color: #c53b3b;
    border-color: #e35353;
    color: white;
    font-weight: 800;
}}
QPushButton#stopButton:hover {{ background-color: #d64545; }}
QPushButton#stopButton:pressed {{ background-color: #aa3030; }}
QPushButton#stopButton:disabled {{
    background-color: #3a2727;
    border-color: #584040;
    color: #b39a9a;
}}
QPushButton#emergencyButton {{
    min-height: {px(38)}px;
    padding: {px(6)}px {px(15)}px;
    font-size: {pt(10.5)};
    background-color: #b42323;
    border: 1px solid #e05858;
    color: white;
    font-weight: 800;
}}
QPushButton#emergencyButton:hover {{ background-color: #cb2a2a; }}
QPushButton#emergencyButton:pressed {{ background-color: #961d1d; }}
QPushButton#emergencyButton:disabled {{
    background-color: #3a2727;
    border-color: #584040;
    color: #b39a9a;
}}
QComboBox, QDoubleSpinBox, QPlainTextEdit {{
    border: 1px solid #46505f;
    border-radius: {px(7)}px;
    padding: {px(4)}px {px(6)}px;
    background-color: #1c2128;
    color: #edf2f7;
    selection-background-color: #2f73ee;
}}
QComboBox, QDoubleSpinBox {{
    min-height: {px(23)}px;
}}
QComboBox:disabled, QDoubleSpinBox:disabled {{
    background-color: #1a1f25;
    color: #7d8794;
    border-color: #353d49;
}}
QComboBox QAbstractItemView {{
    background-color: #1f232a;
    color: #edf2f7;
    border: 1px solid #46505f;
    selection-background-color: #2f73ee;
}}
QCheckBox {{ spacing: {px(7)}px; }}
QCheckBox::indicator {{
    width: {px(16)}px;
    height: {px(16)}px;
    border-radius: {px(4)}px;
    border: 1px solid #687386;
    background-color: #1c2128;
}}
QCheckBox::indicator:checked {{ background-color: #2f73ee; border: 1px solid #5a95ff; }}
QPlainTextEdit {{
    font-family: Consolas, "Courier New", monospace;
    font-size: {pt(9.0)};
}}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: #1c2128; width: {px(12)}px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: #4a5565;
    min-height: {px(24)}px;
    border-radius: {px(5)}px;
}}
QScrollBar:horizontal {{ background: #1c2128; height: {px(12)}px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: #4a5565;
    min-width: {px(24)}px;
    border-radius: {px(5)}px;
}}
"""
