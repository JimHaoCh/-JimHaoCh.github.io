"""Data-integrity and syringe-geometry regressions found during the v1.3.1 audit."""
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ne501.controller import ProgramSettings, format_pump_number
from ne501.mock_controller import MockNE501Controller
from ne501.syringe import format_diameter, plunger_speed_mm_min, flow_limits_ul_min
from ne501.timeline_model import Clip, Timeline, example_timeline


def program(**changes):
    values=dict(rate=1,rate_unit='UM',direction='INF',continuous=False,
                volume=.001,volume_unit='ML',prime_enabled=False,prime_volume=1,
                prime_volume_unit='UL',prime_speed_level='LOW',diameter_mm=10)
    values.update(changes)
    return ProgramSettings(**values)


class AuditNumbersTests(unittest.TestCase):
    def test_four_digit_integers_preserve_all_trailing_zeroes(self):
        for value in range(1000,10000,10):
            self.assertEqual(format_pump_number(value),str(value))
        for value,expected in ((0,'0'),(10,'10'),(100,'100'),(12.300,'12.3')):
            self.assertEqual(format_pump_number(value),expected)

    def test_rate_and_volume_1000_reach_the_simulated_device_unchanged(self):
        controller=MockNE501Controller([0],latency=0);controller.connect()
        confirmation=controller.configure_program(0,program(rate=1000,volume=1000,volume_unit='UL'))
        self.assertTrue(confirmation.verified)
        commands=[command for _,command,_ in confirmation.commands]
        self.assertIn('RAT 1000 UM',commands);self.assertIn('VOL 1000',commands)
        self.assertEqual(controller.pumps[0].phases[1].rate,1000)
        self.assertEqual(controller.pumps[0].phases[1].volume,1000)

    def test_one_digit_readback_error_cannot_verify_a_doubled_low_rate(self):
        class WrongRate(MockNE501Controller):
            def send_command(self,address,command):
                response=super().send_command(address,command)
                return self._response(address,response.status,'0.002UM') if command=='RAT' else response
        controller=WrongRate([0],latency=0);controller.connect()
        confirmation=controller.configure_program(0,program(rate=.001,diameter_mm=.1))
        self.assertFalse(confirmation.verified);self.assertIn('steady RAT',confirmation.message)

    def test_one_digit_readback_error_cannot_verify_a_doubled_low_volume(self):
        class WrongVolume(MockNE501Controller):
            def send_command(self,address,command):
                response=super().send_command(address,command)
                return self._response(address,response.status,'0.002ML') if command=='VOL' else response
        controller=WrongVolume([0],latency=0);controller.connect()
        confirmation=controller.configure_program(0,program())
        self.assertFalse(confirmation.verified);self.assertIn('steady VOL',confirmation.message)

    def test_manufacturer_diameter_4699_is_preserved_and_rechecked_exactly(self):
        controller=MockNE501Controller([0],latency=0);controller.connect()
        confirmation=controller.set_diameter(0,4.699)
        self.assertTrue(confirmation.confirmed);self.assertEqual(confirmation.confirmed_mm,4.699)
        self.assertEqual(controller.pumps[0].diameter,4.699)
        with self.assertRaises(ValueError):controller.set_diameter(0,14.431)
        for value in (True,float('nan'),float('inf'),.01,51):
            with self.assertRaises(ValueError):format_diameter(value)

    def test_diameter_readback_001mm_difference_is_not_accepted(self):
        class WrongDiameter(MockNE501Controller):
            def send_command(self,address,command):
                response=super().send_command(address,command)
                return self._response(address,response.status,'10.01') if command=='DIA' else response
        controller=WrongDiameter([0],latency=0);controller.connect()
        self.assertFalse(controller.set_diameter(0,10).confirmed)


class AuditTimelineDataTests(unittest.TestCase):
    def test_four_flow_units_and_diameter_squared_conversion(self):
        expected=10/(math.pi*25)
        for value,unit in ((10,'µL/min'),(.01,'mL/min'),(600,'µL/hr'),(.6,'mL/hr')):
            self.assertAlmostEqual(plunger_speed_mm_min(value,unit,10),expected)
            self.assertAlmostEqual(plunger_speed_mm_min(value,unit,5),expected*4)
        low,high=flow_limits_ul_min(14.43)
        self.assertAlmostEqual(low*60,6.876,delta=.003)
        self.assertAlmostEqual(high*.06,500.4,delta=.2)

    def test_diameters_survive_save_copy_split_and_edits(self):
        model=example_timeline([5,7,8,9]);model.set_diameters([4.699,14.43,10,None])
        saved=Timeline.from_json(model.to_json())
        self.assertEqual(saved.diameters,model.diameters)
        copied=model.copy();copied.split('a',100);copied.set_total(1300)
        copied.replace(replace(copied.get('b'),rate=7))
        self.assertEqual(copied.diameters,model.diameters)
        copied.set_diameters([10,10,10,10]);self.assertEqual(model.diameters[0],4.699)

    def test_old_workflows_keep_diameter_unset_until_user_supplies_it(self):
        data=json.loads(example_timeline().to_json())
        for track in data['tracks']:del track['diameter_mm']
        model=Timeline.from_json(json.dumps(data))
        self.assertEqual(model.diameters,[None]*4)
        with self.assertRaisesRegex(ValueError,'inside diameter'):model.validate_syringes()
        model.set_diameters([10]*4);model.validate_syringes()

    def test_preflight_checks_only_used_pumps_and_mechanical_rate_range(self):
        model=Timeline(1200,[Clip('a',0,0,100,'INF',10,'µL/min')],diameters=[10,None,None,None])
        model.validate_syringes()
        model.set_diameters([.1,None,None,None])
        with self.assertRaisesRegex(ValueError,'mechanical'):model.validate_syringes()
        model.set_diameters([50,None,None,None]);model.replace(replace(model.get('a'),rate=1))
        with self.assertRaisesRegex(ValueError,'mechanical'):model.validate_syringes()

    def test_unrepresentable_command_rate_fails_preflight(self):
        model=Timeline(1200,[Clip('a',0,0,100,'INF',.0001,'µL/min')],diameters=[.1,None,None,None])
        with self.assertRaises(ValueError):model.validate_syringes()

    def test_extreme_file_numbers_are_reported_as_validation_errors(self):
        for value in (1e308,10**350,float('inf'),float('nan')):
            data=json.loads(example_timeline().to_json());data['duration']=value
            with self.assertRaises(ValueError):Timeline.from_json(json.dumps(data))
            data=json.loads(example_timeline().to_json());data['tracks'][0]['blocks'][0]['rate']=value
            with self.assertRaises(ValueError):Timeline.from_json(json.dumps(data))
        for value in (True,.01,51,14.431,{},float('nan')):
            data=json.loads(example_timeline().to_json());data['tracks'][0]['diameter_mm']=value
            with self.assertRaises(ValueError):Timeline.from_json(json.dumps(data))


class AuditConfigAndLogTests(unittest.TestCase):
    def test_fractional_boolean_and_duplicate_addresses_do_not_select_another_pump(self):
        from ne501.config import _validated_config
        for addresses in ([0,1.9,2,3],[False,1,2,3],[5,5,7,8],[],None,[100],['1.0']):
            with self.assertRaises(ValueError):_validated_config({'addresses':addresses})
        self.assertEqual(_validated_config({'addresses':['05','7',8,9]})['addresses'],[5,7,8,9])

    def test_two_loggers_in_the_same_instant_do_not_overwrite_earlier_commands(self):
        from datetime import datetime
        from ne501.logging_utils import CsvCommandLogger
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'LOCALAPPDATA':folder}),patch('ne501.logging_utils.datetime') as clock:
            clock.now.return_value=datetime(2026,11,6,12,0,0)
            first=CsvCommandLogger();first.write(0,'RAT 1000 UM')
            second=CsvCommandLogger()
            self.assertNotEqual(first.path,second.path)
            self.assertIn('RAT 1000 UM',first.path.read_text(encoding='utf-8-sig'))


os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
try:
    from PySide6.QtCore import QPoint, QSettings
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QMessageBox
    from ui.fonts import configure_ui_font
    from ui.i18n import manager
    from ui.style import build_stylesheet
    from ui.timeline_editor import TimelineEditor
    from ui.syringe_dialog import SyringeDialog
    from ui.main_window import MainWindow
    HAVE_QT=True
except ImportError:HAVE_QT=False


@unittest.skipUnless(HAVE_QT,'PySide6 required')
class AuditSyringeUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion');configure_ui_font(cls.app)
    def setUp(self):
        self.ui=TimelineEditor([5,7,8,9]);self.ui.resize(1280,760);self.ui.show();self.app.processEvents()
    def tearDown(self):
        self.ui.stop_preview();self.ui.close();manager.set_language('zh_TW');self.app.setStyleSheet(build_stylesheet(1))
    def test_syringe_edit_is_undoable_invalidates_check_and_cancel_changes_nothing(self):
        self.ui.check_flow();self.assertTrue(self.ui.checked)
        with patch('ui.timeline_editor.SyringeDialog') as factory:
            factory.return_value.exec.return_value=1;factory.return_value.DialogCode.Accepted=1
            factory.return_value.values=[4.699,10,10,10]
            self.ui.edit_syringes()
        self.assertEqual(self.ui.model.diameters[0],4.699);self.assertFalse(self.ui.checked)
        self.assertTrue(self.ui.modified());self.ui.undo();self.assertEqual(self.ui.model.diameters,[10]*4)
        self.ui.redo();self.assertEqual(self.ui.model.diameters[0],4.699)
        before=self.ui.model.to_json()
        with patch('ui.timeline_editor.SyringeDialog') as factory:
            factory.return_value.exec.return_value=0;factory.return_value.DialogCode.Accepted=1
            self.ui.edit_syringes()
        self.assertEqual(self.ui.model.to_json(),before)
    def test_dialog_copies_verified_values_and_saves_no_device_verification_flag(self):
        dialog=SyringeDialog([5,7,8,9],[None]*4,{5:4.699,7:14.43},self.ui)
        dialog.copy_readbacks();dialog.apply_settings()
        self.assertEqual(dialog.values,[4.699,14.43,None,None])
        self.assertEqual(self.ui.model.diameters,[10]*4)
    def test_old_workflow_requires_syringe_setup_and_updates_conversion(self):
        model=example_timeline([5,7,8,9]);model.set_diameters([None]*4);self.ui._load_model(model)
        self.assertFalse(self.ui.check_button.isEnabled());self.ui.check_flow();self.assertFalse(self.ui.checked)
        self.assertIn('inside diameter',self.ui.notice_label.source_text)
        model.set_diameters([10]*4);self.ui.select_clip('a');self.ui.check_flow()
        self.assertTrue(self.ui.checked);self.assertIn('0.127324',self.ui.plunger_label.source_text)
    def test_open_same_file_after_save_loads_just_saved_content(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'flow.json';path.write_text(self.ui.model.to_json(),encoding='utf-8')
            self.ui.current_path=path;self.ui.saved_snapshot=self.ui.model.to_json()
            self.ui.model.replace(replace(self.ui.model.get('a'),rate=20))
            with patch('ui.timeline_editor.QFileDialog.getOpenFileName',return_value=(str(path),'')),patch('ui.timeline_editor.QMessageBox.question',return_value=QMessageBox.StandardButton.Save):
                self.ui.open_file()
            self.assertEqual(self.ui.model.get('a').rate,20)
            self.assertEqual(Timeline.from_json(path.read_text()).get('a').rate,20)
            self.assertFalse(self.ui.modified())
    def test_dialog_fits_two_languages_and_large_font(self):
        self.app.setStyleSheet(build_stylesheet(1.3))
        for language in ('zh_TW','en'):
            manager.set_language(language)
            dialog=SyringeDialog([5,7,8,9],[4.699,14.43,None,None],{5:4.699},self.ui)
            dialog.show();self.app.processEvents()
            shots=Path(__file__).resolve().parents[1]/'builds/ui-shots-source'
            shots.mkdir(parents=True,exist_ok=True)
            dialog.grab().save(str(shots/f'syringes-{language}-130.png'))
            self.assertLessEqual(dialog.width(),1024);self.assertLessEqual(dialog.height(),768)
            for widget in dialog.spins+[dialog.apply_button,dialog.cancel_button]:
                point=widget.mapTo(dialog,QPoint(0,0))
                self.assertGreaterEqual(point.x(),0);self.assertGreaterEqual(point.y(),0)
                self.assertLessEqual(point.x()+widget.width(),dialog.width())
                self.assertLessEqual(point.y()+widget.height(),dialog.height())
            if language=='en':
                import re
                for label in dialog.findChildren(QLabel):self.assertFalse(re.search(r'[\u3400-\u9fff]',label.text()),label.text())
            dialog.close()
    def test_manual_readback_reaches_timeline_without_overwriting_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=QSettings(str(Path(folder)/'prefs.ini'),QSettings.Format.IniFormat)
            window=MainWindow({'addresses':[5,7,8,9]},settings=settings)
            panel=window.panels[5];panel.set_online(True);panel.update_from_status('S');panel.confirm_diameter(4.699)
            self.assertEqual(window.timeline_editor.device_diameters[5],4.699)
            self.assertEqual(window.timeline_editor.model.diameters[0],10)
            window.timeline_editor.select_clip('a')
            manager.set_language('zh_TW')
            self.assertEqual(window.timeline_editor.diameter_label.text(),'規劃內徑：10 mm')
            self.assertEqual(window.timeline_editor.device_diameter_label.text(),'設備內徑：4.699 mm')
            self.assertFalse(window.timeline_editor.diameter_mismatch_label.isHidden())
            manager.set_language('en')
            self.assertEqual(window.timeline_editor.device_diameter_label.text(),'Device diameter: 4.699 mm')
            panel.open_diameter_editor();panel.diameter_input.setValue(4.700)
            self.assertIsNone(panel.confirmed_diameter);self.assertIsNone(window.timeline_editor.device_diameters[5])
            window.close()

    def test_invalid_config_displays_an_error_before_creating_device_controls(self):
        from main import create_main_window
        with patch('main.load_config',side_effect=ValueError('Pump addresses must be unique integers from 0 to 99.')),patch('main.QMessageBox.warning') as warning,patch('main.MainWindow') as window:
            self.assertIsNone(create_main_window());warning.assert_called_once();window.assert_not_called()

if __name__=='__main__':unittest.main()
