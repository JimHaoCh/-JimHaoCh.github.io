"""Edit timeline syringe geometry; device read-backs are display-only context."""
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QVBoxLayout

from ne501.syringe import format_diameter
from .i18n import manager, tr
from .i18n_widgets import Button, CheckBox, Label, SpinBox


class SyringeDialog(QDialog):
    def __init__(self, addresses, diameters, device_diameters=None, parent=None):
        super().__init__(parent)
        self.addresses = list(addresses)
        self.device_diameters = dict(device_diameters or {})
        self.values = list(diameters)
        self.setWindowTitle(tr('Timeline syringe diameters'))
        manager.changed.connect(lambda: self.setWindowTitle(tr('Timeline syringe diameters')))
        self.resize(700, 380)
        root = QVBoxLayout(self)
        note = Label('Set the actual inside diameter for each used pump. Flow units describe volume; diameter converts flow to plunger speed.')
        note.setWordWrap(True)
        root.addWidget(note)
        grid = QGridLayout()
        for col, text in enumerate(('Pump / address', 'Configured', 'Inside diameter (mm)', 'Manual read-back')):
            grid.addWidget(Label(text), 0, col)
        self.enabled_checks = []
        self.spins = []
        for index, (address, diameter) in enumerate(zip(self.addresses, diameters)):
            grid.addWidget(Label(f'Pump {index + 1} | Address {address:02d}'), index + 1, 0)
            check = CheckBox('Use')
            check.setChecked(diameter is not None)
            spin = SpinBox()
            spin.setDecimals(3)
            spin.setRange(.1, 50)
            spin.setSingleStep(.001)
            spin.setValue(diameter if diameter is not None else 10)
            spin.setEnabled(check.isChecked())
            check.toggled.connect(spin.setEnabled)
            grid.addWidget(check, index + 1, 1)
            grid.addWidget(spin, index + 1, 2)
            readback = self.device_diameters.get(address)
            label = Label(f'Verified: {readback:g} mm' if readback is not None else 'Not verified')
            grid.addWidget(label, index + 1, 3)
            self.enabled_checks.append(check)
            self.spins.append(spin)
        root.addLayout(grid)
        self.error_label = Label()
        self.error_label.setObjectName('warningLabel')
        self.error_label.setWordWrap(True)
        root.addWidget(self.error_label)
        self.copy_button = Button('Use manual read-backs')
        self.copy_button.setEnabled(any(self.device_diameters.get(a) is not None for a in self.addresses))
        self.copy_button.clicked.connect(self.copy_readbacks)
        root.addWidget(self.copy_button)
        context = Label('Timeline values are planning data. Manual Control must write and verify the actual device diameter. This dialog sends no pump commands.')
        context.setWordWrap(True)
        context.setObjectName('secondaryLabel')
        root.addWidget(context)
        root.addStretch()
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = Button('Cancel')
        self.apply_button = Button('Apply syringe settings')
        self.apply_button.setObjectName('applyButton')
        self.apply_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.apply_settings)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.apply_button)
        root.addLayout(actions)

    def copy_readbacks(self):
        for address, check, spin in zip(self.addresses, self.enabled_checks, self.spins):
            value = self.device_diameters.get(address)
            if value is not None:
                check.setChecked(True)
                spin.setValue(value)

    def apply_settings(self):
        result = []
        for index, (check, spin) in enumerate(zip(self.enabled_checks, self.spins)):
            if not check.isChecked():
                result.append(None)
                continue
            try:
                if not spin.hasAcceptableInput():
                    raise ValueError('Enter a complete inside diameter between 0.10 and 50.00 mm.')
                spin.interpretText()
                format_diameter(spin.value())
            except ValueError as exc:
                self.error_label.setText(f'Pump {index + 1}: {exc}')
                spin.setFocus()
                return
            result.append(spin.value())
        self.values = result
        self.accept()
