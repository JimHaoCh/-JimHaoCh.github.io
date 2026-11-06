"""Isolation and wiring checks for the simulation-only timeline preview."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]

class PreviewSafetyTests(unittest.TestCase):
    def test_timeline_modules_do_not_import_pump_or_serial_controllers(self):
        for name in ('ne501/timeline_model.py', 'ui/timeline_editor.py'):
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            modules = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import): modules.extend(a.name for a in node.names)
                if isinstance(node, ast.ImportFrom): modules.append(node.module or '')
            self.assertFalse(any(m == 'serial' or m.startswith('serial.') or m in ('ne501.controller', 'ne501.mock_controller') for m in modules), modules)

    def test_preview_installs_separately_from_existing_application(self):
        setup = (ROOT / 'build/installer.iss').read_text(encoding='utf-8')
        config = (ROOT / 'ne501/config.py').read_text(encoding='utf-8')
        self.assertIn('NE501_Timeline_UI_Preview', setup)
        self.assertIn('NE501_Timeline_UI_Preview', config)
        self.assertNotIn('DefaultDirName={localappdata}\\Programs\\NE501_Multi_Pump_Controller', setup)
        self.assertNotIn('AppId={{4D6C2834-6DF7-4921-A9C4-CBA47318A501}', setup)

if __name__ == '__main__': unittest.main()
