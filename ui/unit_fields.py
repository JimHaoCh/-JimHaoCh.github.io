"""Preserve physical quantities when selecting display units."""
from PySide6.QtCore import QSignalBlocker


def preserve_quantity(spin, combo, factors, notice, loading=lambda: False):
    def code():
        return combo.currentData() if combo.currentData() is not None else combo.currentText()
    previous = [code()]

    def changed(*_):
        old, new = previous[0], code()
        if loading():
            previous[0] = new
            return
        if old == new or old not in factors or new not in factors:
            previous[0] = new
            return
        if spin.value() == 0 and spin.minimum() == 0:
            previous[0] = new
            return
        value = spin.value() * factors[old] / factors[new]
        if not spin.hasAcceptableInput() or not spin.minimum() <= value <= spin.maximum() or round(value, spin.decimals()) <= 0:
            blocker = QSignalBlocker(combo)
            index = combo.findData(old)
            combo.setCurrentIndex(index if index >= 0 else combo.findText(old))
            del blocker
            notice('The converted value exceeds this input range. Keep the current unit or adjust the quantity.')
            return
        blocker = QSignalBlocker(spin)
        spin.setValue(value)
        del blocker
        previous[0] = new
        notice('Unit converted; review the displayed value and device read-back.')

    combo.currentIndexChanged.connect(changed)
    return changed
