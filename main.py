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
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

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
    if timeline.model.diameters != [10.0] * 4 or window.preparation.used_addresses():
        raise RuntimeError('A new experiment must start with 10 mm defaults and no selected pumps')
    if any(p.confirmed_diameter is not None for p in window.panels.values()):
        raise RuntimeError('Default values must not count as device confirmations')
    window.update_preparation(0, used=True, diameter=4.699, fluid='Sample', inlet='A')
    # Fixture setup is intentional; avoid a save prompt in unattended checks.
    timeline.saved_snapshot = timeline.model.to_json()
    window.load_example_workflow()
    if window.workflow.step != 1 or timeline.model.diameters[0] != 4.699 or window.preparation.used_addresses() != [0] or timeline.model.names[0] != 'Sample':
        raise RuntimeError('Example loading must retain shared setup and review step 2')
    flow_diameter = window.workflow.diameter_inputs[0]
    example_diameter = timeline.model.diameters[0]
    flow_diameter.setFocus(); flow_diameter.selectAll()
    QTest.keyClick(flow_diameter, Qt.Key.Key_Backspace)
    QTest.keyClick(flow_diameter, Qt.Key.Key_Tab)
    if flow_diameter.text() or timeline.model.diameters[0] is not None:
        raise RuntimeError('Deleting a diameter must keep the plan empty after Tab')
    QTest.mouseClick(flow_diameter, Qt.MouseButton.LeftButton)
    if flow_diameter.text() or flow_diameter.lineEdit().placeholderText():
        raise RuntimeError('Clicking an empty timeline diameter must clear the visual hint')
    QTest.keyClicks(flow_diameter, str(example_diameter))
    QTest.keyClick(flow_diameter, Qt.Key.Key_Return)
    if timeline.model.diameters[0] != example_diameter:
        raise RuntimeError('Timeline diameter must accept typing immediately after a mouse click')
    window.show_workflow_step(3)
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
    if hasattr(window.workflow, 'mapping_check') or hasattr(window.workflow, 'tubing_box'):
        raise RuntimeError('Manual preparation must omit mapping and tubing confirmation controls')
    window.select_pump(0)
    panel = window.panels[0]
    window.show_workflow_step(1)
    diameter = window.workflow.diameter_inputs[0]
    window.workflow.next_button.setFocus()
    window.update_preparation(0, diameter=None)
    QTest.mouseClick(diameter, Qt.MouseButton.LeftButton)
    if diameter.text() or diameter.lineEdit().placeholderText():
        raise RuntimeError('Clicking an empty manual diameter must clear the visual hint')
    QTest.keyClicks(diameter,'4.699')
    if diameter.text()!='4.699':raise RuntimeError('Typed diameter was overwritten')
    QTest.mouseClick(window.workflow.diameter_buttons[0],Qt.MouseButton.LeftButton)
    wait_until(lambda: window.pending_tasks == 0 and panel.confirmed_diameter == 4.699, 'typed step-2 diameter verification')
    diameter.setFocus()
    QTest.keyClick(diameter, Qt.Key.Key_Up)
    if window.preparation.plans[0].diameter != 4.7 or panel.confirmed_diameter is not None:
        raise RuntimeError('Arrow changes must update the plan and invalidate old read-back')
    QTest.keyClick(diameter, Qt.Key.Key_Down)
    QTest.mouseClick(window.workflow.diameter_buttons[0], Qt.MouseButton.LeftButton)
    wait_until(lambda: window.pending_tasks == 0 and panel.confirmed_diameter == 4.699, 'arrow-edited diameter verification')
    window.show_workflow_step(3)
    if hasattr(panel,'inline_setup') or not panel.diameter_input.isReadOnly():
        raise RuntimeError('The manual console must have one read-only syringe summary')
    panel.apply_button.click()
    wait_until(lambda: window.pending_tasks == 0 and panel.settings_applied, 'fixed-footer apply and read-back')
    panel.editor_run_button.click()
    wait_until(lambda: window.pending_tasks == 0 and panel.running, 'fixed-footer start')
    if window.workflow.step != 3:
        raise RuntimeError('Manual start must stay on the console')
    panel.editor_stop_button.click()
    wait_until(lambda: window.pending_tasks == 0 and panel.last_status == 'P' and not panel.running, 'fixed-footer stop preserving progress')
    panel.run_button.click()
    wait_until(lambda: window.pending_tasks == 0 and panel.running, 'card resume')
    panel.stop_button.click()
    wait_until(lambda: window.pending_tasks == 0 and panel.last_status == 'P', 'card stop')
    panel.priming_control.toggle.setChecked(True)
    panel.priming_control.mode.setCurrentIndex(1)
    window.workflow.prep_rate.setFocus();window.workflow.prep_rate.selectAll()
    QTest.keyClicks(window.workflow.prep_rate,'10')
    window.workflow.prep_volume.setFocus();window.workflow.prep_volume.selectAll()
    QTest.keyClicks(window.workflow.prep_volume,'5')
    window.workflow.prep_write.click()
    wait_until(lambda: window.pending_tasks == 0 and window.workflow.prep_start.isEnabled(), 'bounded priming write/read-back')
    window.workflow.mode_selector.setCurrentIndex(1)
    if sum(button.isVisible() for button in window.workflow.steps) != 4 or window.workflow.step != 3:
        raise RuntimeError('Timeline mode must have four steps and omit manual priming')
    window.write_preparation()
    window.start_preparation()
    if window.pending_tasks or window.controller.pumps[0].status != 'S':
        raise RuntimeError('Manual priming must be unavailable in timeline mode')
    window.show_workflow_step(4)
    if window.workflow.review_table.columnCount() != 4:
        raise RuntimeError('Timeline review must omit manual volume stages')
    window.workflow.mode_selector.setCurrentIndex(0)
    window.show_workflow_step(3)
    window.workflow.prep_start.click()
    wait_until(lambda: window.pending_tasks == 0 and panel.running, 'explicit priming start')
    label=panel.target_label.source_text;panel.refresh_age()
    if label!=panel.target_label.source_text or not label.startswith('Priming:'):
        raise RuntimeError('Age refresh overwrote the priming-stage display')
    window.workflow.prep_stop.click()
    wait_until(lambda: window.pending_tasks == 0 and not panel.running, 'priming stop')
    if window.manual_start_blocker(0):
        raise RuntimeError('Formal delivery must not require a tubing confirmation after priming')
    window.set_diameter(0, 10)
    wait_until(lambda: window.pending_tasks == 0, 'same-diameter rewrite')
    if window.workflow.prep_start.isEnabled():
        raise RuntimeError('A diameter rewrite must invalidate the old priming verification')
    for language in ('zh_TW', 'en'):
        manager.set_language(language)
        for step in (0,1,3):
            window.show_workflow_step(step)
            app.processEvents()
            window.grab().save(str(report_path.parent / f'workflow-step{step + 1}-{language}.png'))
    window.controller.disconnect()
    window.controller = None
    # These fixture edits intentionally exercised plan changes; leave no save
    # dialog for the unattended packaged-startup check.
    timeline.saved_snapshot = timeline.model.to_json()
    timeline.dirty = timeline.duration_dirty = False
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
        "mode_specific_workflow": True,
        "stale_priming_proof_rejected": True,
        "same_page_start_stop_resume": True,
        "manual_stages": 3,
        "unified_explicit_priming": True,
        "keyboard_diameter": True,
        "keyboard_priming": True,
        "single_diameter_entry": True,
        "stage_label_retained": True,
        "mouse_diameter_manual": True,
        "mouse_diameter_timeline": True,
        "no_preparation_confirmation_gates": True,
        "default_diameter_10_mm": True,
        "example_setup_retained": True,
        "example_reviews_step_two": True,
        "cleared_diameter_persists": True,
        "arrow_diameter_committed": True,
        "font_family": font_family,
        "hardware_connected": False,
    }, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
