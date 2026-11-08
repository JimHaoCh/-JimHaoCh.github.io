"""Fault-injection coverage for active waits, uncertain RUN and wire integrity."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from ne501.controller import (NE501Controller, ProgramSettings, PumpConnectionError,
                              PumpTimeoutError, parse_number_and_unit)
from ne501.protocol import build_command, parse_response
from ne501.mock_controller import MockNE501Controller
from ui.i18n import manager, tr
from ui.unit_fields import preserve_quantity
from ui.i18n_widgets import SpinBox, ComboBox, Button
from test_controller_features import FakeSerial, ScriptedStopController
import test_workflow_141 as helpers


def settings():
    return ProgramSettings(10, 'UM', 'INF', True, 1, 'UL', False, 1, 'UL', 'LOW', 10)


class WireAuditTests(unittest.TestCase):
    def test_documented_basic_statuses_and_system_address_remain_compatible(self):
        for status in 'IWSPTUX':
            self.assertTrue(parse_response(f'\x0200{status}\x03'.encode(), 0).ok)
            self.assertTrue(parse_response(f'\x020{status}\x03'.encode(), 0).ok)
        self.assertTrue(parse_response(b'\x02*S\x03').ok)
        self.assertFalse(parse_response(b'\x0200A?S\x03', 0).ok)

    def test_malformed_packets_never_report_success(self):
        for raw in (b'00S', b'00S\x03', b'\x0200S', b'\x0200garbage\x03',
                    b'\x0200A\x03', b'\x0200S10\xff\x03', b'\x0200S\nRUN\x03'):
            with self.subTest(raw=raw):
                self.assertFalse(parse_response(raw, 0).ok)

    def test_noise_without_start_marker_cannot_acknowledge_a_command(self):
        c = NE501Controller(timeout=.005, inter_command_delay=0)
        c._serial = FakeSerial(b'00S\x03')
        with self.assertRaises((PumpConnectionError, PumpTimeoutError)):
            c.send_command(0, 'RUN 1')

    def test_serial_reader_resynchronizes_on_real_start_marker(self):
        c = NE501Controller(timeout=.02, inter_command_delay=0)
        c._serial = FakeSerial(b'noise\x03\x0200S\x03')
        self.assertTrue(c.send_command(0, '').ok)

    def test_truncated_write_is_not_retried_or_accepted(self):
        c = NE501Controller(timeout=.02, inter_command_delay=0)
        c._serial = FakeSerial(b'\x0200I\x03')
        with patch.object(c._serial, 'write', return_value=3) as write:
            with self.assertRaises(PumpConnectionError):c.send_command(0, 'RUN 1')
        write.assert_called_once_with(b'00RUN 1\r')

    def test_commands_reject_control_characters_and_noninteger_addresses(self):
        for command in ('RUN\rSTP', 'RUN\n', '\tRUN', 'RUN\x02'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                build_command(0, command)
        for address in (True, 1.5, '0'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                build_command(address, 'RUN')

    def test_number_readback_requires_the_whole_payload(self):
        for text in ('junk10UM', '10UMjunk', '10UM 20MH', '10e3UM', 'NaNUM'):
            with self.subTest(text=text):
                self.assertEqual(parse_number_and_unit(text, {'UM'}), (None, None))
        self.assertEqual(parse_number_and_unit(' 10.00 UM ', {'UM'}), (10, 'UM'))
        self.assertEqual(parse_number_and_unit('.001UM', {'UM'}), (.001, 'UM'))
        self.assertEqual(parse_number_and_unit('10.UM', {'UM'}), (10, 'UM'))

    def test_malformed_framed_response_raises_transport_error(self):
        c = NE501Controller(timeout=.02, inter_command_delay=0)
        c._serial = FakeSerial(b'\x0200Q\x03')
        with self.assertRaises(PumpConnectionError):c.send_command(0, '')

    def test_diameter_readback_with_extra_payload_is_never_confirmed(self):
        for text in ('junk10', '10junk', '10MM', '10 20'):
            c = ScriptedStopController([('S',''), ('S',''), ('S',text)])
            self.assertFalse(c.set_diameter(0, 10).confirmed, text)

    def test_program_readback_requires_exact_function_direction_and_quantity(self):
        for corrupt, data in (('FUN','RATjunk'), ('DIR','INFjunk'),
                              ('RAT','10UMjunk'), ('VOL','0ULjunk')):
            c = MockNE501Controller([0], latency=0); c.connect()
            send = c.send_command
            def altered(address, command):
                response = send(address, command)
                return parse_response(f'\x0200S{data}\x03'.encode(), 0) if command == corrupt else response
            with patch.object(c, 'send_command', side_effect=altered):
                self.assertFalse(c.configure_program(0, settings()).verified, corrupt)

    def test_unexpected_active_state_aborts_remaining_configuration_commands(self):
        c = ScriptedStopController([('S',''), ('U','')])
        self.assertFalse(c.configure_program(0, settings()).verified)
        self.assertEqual(c.commands, ['', 'PHN 1'])
        c = ScriptedStopController([('U','')])
        actual, problem = c._program_prime_rate(0, 10, [])
        self.assertIsNone(actual)
        self.assertTrue(problem)
        self.assertEqual(len(c.commands), 1)

    def test_diameter_write_requires_a_confirmed_reset(self):
        c = ScriptedStopController([('U',''), ('U',''), ('S','10'), ('S','10')])
        with self.assertRaises(PumpConnectionError):c.set_diameter(0, 10)
        self.assertFalse(any(x.startswith('DIA') for x in c.commands))

    def test_program_write_requires_a_confirmed_reset(self):
        c = ScriptedStopController([('T',''), ('T','')])
        result = c.configure_program(0, settings())
        self.assertFalse(result.verified)
        self.assertEqual(c.commands, ['', 'STP'])


class UnitDraftAuditTests(unittest.TestCase):
    setUpClass = classmethod(helpers.ModeWorkflowTests.setUpClass.__func__)

    def test_english_ampersand_is_literal_and_does_not_create_a_shortcut(self):
        manager.set_language('en')
        button = Button('Write & verify')
        self.assertEqual(button.text(), 'Write && verify')
        self.assertTrue(button.shortcut().isEmpty())
        manager.set_language('zh_TW')
        self.assertEqual(button.text(), '寫入並回讀')
        manager.set_language('en')
        self.assertEqual(button.text(), 'Write && verify')
        manager.set_language('zh_TW')

    def fields(self):
        spin = SpinBox(); spin.setDecimals(4); spin.setRange(0, 9999)
        combo = ComboBox(); combo.addItem('µL/min', 'UM'); combo.addItem('µL/hr', 'UH')
        notices = []
        preserve_quantity(spin, combo, {'UM': 1, 'UH': 1/60}, notices.append)
        return spin, combo, notices

    def test_typed_quantity_is_converted_instead_of_old_cached_value(self):
        spin, combo, _ = self.fields(); spin.setValue(10)
        spin.selectAll(); QTest.keyClicks(spin, '20')
        combo.setCurrentIndex(1)
        self.assertEqual(spin.value(), 1200)

    def test_invalid_draft_keeps_text_and_unit(self):
        spin, combo, notices = self.fields()
        spin.lineEdit().setText('-')
        combo.setCurrentIndex(1)
        self.assertEqual(combo.currentData(), 'UM')
        self.assertEqual(spin.lineEdit().text(), '-')
        self.assertTrue(notices)


class DeviceStateAuditTests(unittest.TestCase):
    setUpClass = classmethod(helpers.ModeWorkflowTests.setUpClass.__func__)
    setUp = helpers.ModeWorkflowTests.setUp
    tearDown = helpers.ModeWorkflowTests.tearDown
    idle = helpers.ModeWorkflowTests.idle
    ready = helpers.ModeWorkflowTests.ready

    def write(self, *addresses):
        self.win.write_station_programs([self.win.panels[a] for a in addresses]); self.idle()
        self.assertTrue(all(self.win.panels[a].settings_applied for a in addresses))

    def test_active_wait_locks_settings_and_timeline_but_leaves_stop_available(self):
        self.ready(); self.write(0); w = self.win; p = w.panels[0]
        for status in ('T', 'U'):
            with self.subTest(status=status):
                p.update_from_status(status); w.refresh_group_controls()
                self.assertTrue(p.running)
                self.assertFalse(w.can_write_panel(p))
                self.assertFalse(w.can_use_timeline())
                self.assertFalse(p.run_button.isEnabled())
                self.assertTrue(p.stop_button.isEnabled())
                self.assertNotIn(p.status_label.source_text, ('● Ready', '● Running'))

    def test_active_wait_is_polled_even_when_auto_refresh_is_off(self):
        self.ready(); w = self.win; w.auto_refresh_checkbox.setChecked(False)
        for status in ('T', 'U'):
            w.panels[0].update_from_status(status)
            with patch.object(w, 'refresh_status') as refresh:
                w.maybe_refresh_status(); refresh.assert_called_once()

    def test_stop_from_either_active_wait_confirms_retained_progress(self):
        self.ready(); w = self.win; p = w.panels[0]
        for status in ('T','U'):
            w.controller.pumps[0].status=status
            p.update_from_status(status); w.refresh_group_controls()
            w.hold_station([0]); self.idle()
            self.assertEqual(p.last_status, 'P')
            self.assertFalse(p.running); self.assertFalse(p.stop_pending)

    def test_legacy_start_entries_cannot_bypass_write_and_readback(self):
        self.ready(); w = self.win
        with patch.object(w.controller, 'send_command', wraps=w.controller.send_command) as send:
            w.run_single_command(0, 'RUN 1', w.panels[0]); self.idle()
            w.group_command([w.panels[0]], 'RUN 1'); self.idle()
        self.assertFalse(any(c.args[1].startswith('RUN') for c in send.call_args_list))

    def test_wait_and_uncertain_state_copy_is_translated(self):
        for language in ('zh_TW','en'):
            manager.set_language(language)
            for source in ('● Timed wait · program active','● Trigger wait · program active',
                           'Start not confirmed','Finish entering a valid number before changing units.'):
                self.assertEqual(tr(source)==source, language=='en')

    def test_start_timeout_after_motor_started_is_visibly_uncertain_until_stop(self):
        self.ready(); self.write(0); w = self.win; p = w.panels[0]
        send = w.controller.send_command; calls = []
        def lost_ack(address, command):
            calls.append((address, command))
            response = send(address, command)
            if command.startswith('RUN'):raise PumpTimeoutError('RUN acknowledgement lost')
            return response
        with patch.object(w.controller, 'send_command', side_effect=lost_ack):
            w.start_station(0); self.idle()
        self.assertEqual(sum(c.startswith('RUN') for _, c in calls), 1)
        self.assertEqual(w.controller.pumps[0].status, 'I')
        self.assertTrue(p.running)
        self.assertIsNone(p.last_status)
        self.assertFalse(w.can_use_timeline())
        self.assertTrue(p.stop_button.isEnabled())
        self.assertFalse(p.run_button.isEnabled())
        self.assertIn('UNCONFIRMED', p.status_label.source_text)
        self.assertIn('STOP', p.next_instruction())
        self.assertEqual(w.workflow_hint()[1], 3)
        self.assertIn('stop controls', w.workflow_hint()[0])
        w.hold_station([0]); self.idle()
        self.assertFalse(p.running); self.assertFalse(p.stop_pending)
        self.assertEqual(p.last_status, 'P')
        self.assertTrue(w.manual_start_blocker(0))
        self.assertTrue(p.online)
        self.assertNotEqual(p.version_label.source_text, 'No response')
        self.write(0)
        self.assertFalse(w.manual_start_blocker(0))

    def test_group_timeout_preserves_earlier_start_and_skips_later_pump(self):
        self.ready((0, 1, 2)); self.write(0, 1, 2); w = self.win
        send = w.controller.send_command; calls = []
        def lost_ack(address, command):
            calls.append((address, command)); response = send(address, command)
            if address == 1 and command.startswith('RUN'):raise PumpTimeoutError('lost')
            return response
        with patch.object(w.controller, 'send_command', side_effect=lost_ack):
            w.start_station_group([w.panels[a] for a in (0, 1, 2)]); self.idle()
        self.assertTrue(w.panels[0].running)
        self.assertTrue(w.panels[1].running)
        self.assertIsNone(w.panels[1].last_status)
        self.assertFalse(any(a == 2 and c.startswith('RUN') for a, c in calls))
        w.emergency_stop(); self.idle()
        self.assertTrue(all(p.last_status == 'S' for p in w.panels.values()))

    def test_alarm_is_noticed_once_and_cleared_status_cannot_rearm_old_proof(self):
        self.ready(); self.write(0); w = self.win
        alarm = parse_response(b'\x0200A?S\x03', 0)
        with patch.object(w, 'show_nonmodal_warning') as notice:
            w.process_results([(0, 'STATUS', alarm), (0, 'STATUS', alarm)])
            self.assertEqual(notice.call_count, 1)
        w.process_results([(0, 'STATUS', parse_response(b'\x0200P\x03', 0))])
        self.assertTrue(w.manual_start_blocker(0))
        self.assertNotIn(0, w.station_proofs)
        self.write(0)
        with patch.object(w, 'show_nonmodal_warning') as notice:
            w.process_results([(0, 'STATUS', alarm)])
            self.assertEqual(notice.call_count, 1)
        w.process_results([(0, 'STATUS', parse_response(b'\x0200S\x03', 0))])
        self.write(0)
        with patch.object(w, 'show_nonmodal_warning') as notice, patch.object(w.controller, 'scan', return_value={0:alarm}):
            w.scan_pumps(); self.idle()
            self.assertEqual(notice.call_count, 1)
        self.assertNotIn(0, w.station_proofs)


if __name__ == '__main__':unittest.main()
