from __future__ import annotations

import sys
import json
import sysconfig
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ne501.config import load_config, resource_path
from ui.main_window import MainWindow
from ui.style import build_stylesheet
from ui.fonts import configure_ui_font
from ui.i18n import manager
from ne501.mock_controller import MockNE501Controller
from ne501 import __version__
from ui.i18n_widgets import MessageBox as QMessageBox


def create_main_window():
    try:
        config = load_config()
    except (ValueError, OSError) as exc:
        QMessageBox.warning(None, 'Configuration error', str(exc))
        return None
    return MainWindow(config)


def main() -> int:
    # The packaged build uses this mode to check GUI startup and simulation
    # without opening a serial port or touching any physical pump.
    report_path = None
    if "--smoke-test-report" in sys.argv:
        index = sys.argv.index("--smoke-test-report")
        if index + 1 >= len(sys.argv):
            return 2
        report_path = Path(sys.argv[index + 1])
    if report_path is not None:
        try:
            return run_smoke_test(report_path)
        except Exception:
            report_path.write_text(json.dumps({"ok": False, "error": traceback.format_exc()}, indent=2), encoding="utf-8")
            return 1

    app = QApplication(sys.argv)
    app.setApplicationName("NE501 Multi Pump Controller")
    app.setOrganizationName("NE501Controller")
    app.setStyle("Fusion")
    configure_ui_font(app)

    settings = QSettings("NE501Controller", "NE501 Timeline UI Preview")
    try:
        ui_scale = float(settings.value("ui_scale", 1.0))
    except (TypeError, ValueError):
        ui_scale = 1.0
    app.setStyleSheet(build_stylesheet(ui_scale))

    icon_path = resource_path("assets/ne501.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    manager.set_language(str(settings.value('language', 'zh_TW')))
    window = create_main_window()
    if window is None:
        return 2
    window.show()
    return app.exec()


def run_smoke_test(report_path: Path) -> int:
    import serial
    from serial.tools import list_ports

    app = QApplication([sys.argv[0]])
    app.setApplicationName("NE501 Multi Pump Controller")
    app.setOrganizationName("NE501Controller")
    app.setStyle("Fusion")
    font_family = configure_ui_font(app)
    app.setStyleSheet(build_stylesheet(1.0))
    config = load_config()
    isolated_settings = QSettings(str(report_path.parent / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(config, settings=isolated_settings)
    # The smoke test must not change the real user's saved COM selection.
    window.show()
    app.processEvents()
    if sorted(window.panels) != [0, 1, 2, 3]:
        raise RuntimeError("Expected four default pump panels")
    if window.timeline_editor is None or len(window.timeline_editor.model.addresses) != 4:
        raise RuntimeError("Four-track timeline preview is missing")
    timeline = window.timeline_editor
    if timeline.model.diameters != [None] * 4 or window.preparation.used_addresses():
        raise RuntimeError('A new experiment must start with blank syringe plans')
    window.load_example_workflow()
    if not window.grab().save(str(report_path.parent / 'timeline-preview.png')):
        raise RuntimeError('Unable to render timeline preview screenshot')
    for language in ('zh_TW','en'):
        manager.set_language(language)
        for index,name in ((0,'manual'),(1,'timeline')):
            window.mode_tabs.setCurrentIndex(index)
            app.processEvents()
            if not window.grab().save(str(report_path.parent / f'{name}-{language}.png')):
                raise RuntimeError('UI screenshot failed')
    manager.set_language('zh_TW')
    window.show_workflow_step(3)
    window.mode_tabs.setCurrentIndex(1)
    timeline.canvas.grab()
    timeline.check_flow()
    if not timeline.play_button.isEnabled():
        raise RuntimeError("Timeline simulation check failed")
    timeline.start_preview()
    if not timeline.running:
        raise RuntimeError("Timeline simulation did not start")
    timeline.stop_preview()
    if window.port_combo.findData("MOCK") < 0:
        raise RuntimeError("Simulation mode is missing")
    mock = MockNE501Controller([0, 1, 2, 3], latency=0)
    mock.connect("MOCK", 19200)
    if sorted(mock.scan([0, 1, 2, 3])) != [0, 1, 2, 3]:
        raise RuntimeError("Simulation scan did not find all four pumps")
    mock.disconnect()
    # Ensure the dynamically-selected Windows COM backend is bundled.
    list(list_ports.comports())

    def wait_until(predicate, description: str) -> None:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        raise RuntimeError(f"Timed out waiting for {description}")

    # Exercise real Qt queued signals and workers using simulation only.
    window.port_combo.setCurrentIndex(window.port_combo.findData("MOCK"))
    window.connect_controller()
    wait_until(
        lambda: isinstance(window.controller, MockNE501Controller)
        and all(panel.online for panel in window.panels.values())
        and window.pending_tasks == 0,
        "simulation connection and scan",
    )
    window.emergency_stop()
    wait_until(lambda: window.pending_tasks == 0, "simulated STOP ALL")
    if not all(panel.last_status == "S" and panel.last_response_source == "STOP confirmed by pump response" for panel in window.panels.values()):
        raise RuntimeError("Simulated STOP ALL did not confirm every pump")
    window.mode_tabs.setCurrentIndex(0)
    window.show_workflow_step(0)
    window.workflow.mapping_check.setChecked(True)
    for address in window.preparation.used_addresses():
        window.change_tubing(address, 'skipped')
    window.show_workflow_step(3)
    window.select_pump(0)
    panel = window.panels[0]
    panel.set_diameter_button.click()
    wait_until(lambda: window.pending_tasks == 0 and panel.confirmed_diameter is not None, 'diameter verification')
    panel.apply_button.click()
    wait_until(lambda: window.pending_tasks == 0 and panel.settings_applied, 'fixed-footer apply and read-back')
    panel.editor_run_button.click()
    if window.workflow.step != 4 or panel.running:
        raise RuntimeError('Manual start must first show the review page')
    window.workflow.review_start.click()
    wait_until(lambda: window.pending_tasks == 0 and panel.running, 'fixed-footer start')
    panel.editor_stop_button.click()
    wait_until(lambda: window.pending_tasks == 0 and panel.last_status == 'S' and not panel.running, 'fixed-footer stop')
    window.show_workflow_step(2)
    window.change_tubing(0, 'needed')
    window.workflow.prep_rate.setValue(10)
    window.workflow.prep_volume.setValue(5)
    window.workflow.prep_write.click()
    wait_until(lambda: window.pending_tasks == 0 and window.workflow.prep_start.isEnabled(), 'bounded priming write/read-back')
    window.workflow.prep_start.click()
    wait_until(lambda: window.pending_tasks == 0 and panel.running, 'explicit priming start')
    window.workflow.prep_stop.click()
    wait_until(lambda: window.pending_tasks == 0 and not panel.running, 'priming stop')
    if panel.settings_applied:
        raise RuntimeError('Priming must not arm the main delivery')
    for language in ('zh_TW', 'en'):
        manager.set_language(language)
        for step in range(5):
            window.show_workflow_step(step)
            app.processEvents()
            window.grab().save(str(report_path.parent / f'workflow-step{step + 1}-{language}.png'))
    window.controller.disconnect()
    window.controller = None
    QTimer.singleShot(300, app.quit)
    exit_code = app.exec()
    if exit_code:
        raise RuntimeError(f"GUI returned {exit_code}")
    report_path.write_text(json.dumps({
        "ok": True,
        "version": __version__,
        "python_platform": sysconfig.get_platform(),
        "pyserial": serial.__version__,
        "simulation_pumps": 4,
        "timeline_preview": True,
        "guided_manual_workflow": True,
        "shared_preparation": True,
        "bounded_priming": True,
        "font_family": font_family,
        "hardware_connected": False,
    }, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
