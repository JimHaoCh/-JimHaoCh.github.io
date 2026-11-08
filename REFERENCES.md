# References, citation and acknowledgements / 參考與引用

## Technical references / 技術參考

1. New Era Pump Systems, Inc. *NE-500/NE-501 Multi-Phaser OEM Syringe Pump User Manual*, V3.9. RS-232 Basic Mode and equipment instructions. [Manufacturer's manual](https://www.syringepump.com/download/NE-500%20OEM%20Syringe%20Pump%20User%20Manual%20V3.9.pdf).
2. New Era Pump Systems, Inc. *NE-1000/NE-500/NE-501 Rates and Specifications*. [Manufacturer's specifications](https://www.syringepump.com/download/NE-1000-500-501%20Rates%20and%20Specifications.pdf).
3. Prolific Technology Inc. *PL2303GT USB to RS232 Bridge Controller*: [product and driver information](https://www.prolific.com.tw/portfolio-item/pl2303gt/). Adapter models and driver compatibility must be checked on each system.
4. ClarkLabUCB. [NewEraPumps_Python3](https://github.com/ClarkLabUCB/NewEraPumps_Python3), a related NE-500 Python controller considered in the early exploration of this project. Its README credits the earlier work to Phil Romero and later contributions by John Halliburton, Kevin Joslin and Sakshi Shah. The referenced repository's license status is not stated here; this citation does not confer rights to its contents.
5. RomeroLab. [syringe-pump-controller](https://github.com/RomeroLab/syringe-pump-controller), an earlier Python GUI for NE-500/501 pumps. Reviewed for workflow context; no source copied for V2.0.0.
6. Hiro Shikata. [SyringeGUI](https://github.com/hiro-shikata/SyringeGUI), README sections on units, manual controls, programmed pause/resume and abort. Reviewed 2026-11-08; different hardware and command protocol.
7. MWorks. [NE-500 syringe pump](https://mworks.github.io/documentation/latest/components/ne_500_syringe_pump.html) and [pump network](https://mworks.github.io/documentation/latest/components/ne_500_syringe_pump_network.html), official component documentation. Reviewed 2026-11-08 for units, timeout and command logging.
8. pySerial. [API documentation](https://pyserial.readthedocs.io/en/latest/pyserial_api.html), read/write length and timeout semantics. Qt. [QAbstractSpinBox](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QAbstractSpinBox.html), keyboard tracking and draft interpretation. Reviewed 2026-11-08.

The V2.0.0 source-to-test mapping is documented in [UI_REVIEW_v2.0.0.md](UI_REVIEW_v2.0.0.md). External project behavior is context for test design, not evidence that this application has passed hardware validation.

## Software dependencies / 軟體套件

* Python: [Python Software Foundation](https://www.python.org/), PSF License.
* PySide6 / Qt for Python: [Qt for Python](https://doc.qt.io/qtforpython-6/), available under LGPLv3 / GPL and commercial terms; bundled modules may include components with their own licenses.
* pySerial: [pySerial project](https://github.com/pyserial/pyserial), BSD 3-Clause.
* PyInstaller: [PyInstaller](https://pyinstaller.org/), GPL with a special bootloader exception; see its license.
* Inno Setup: [Inno Setup](https://jrsoftware.org/isinfo.php), used to build the Windows installer; see the project license.

The build collects license and notice files distributed with installed packages
under `THIRD_PARTY_LICENSES`. Consult `THIRD_PARTY_NOTICES.md` for upstream
license and source locations. Each third-party project retains its rights.

## Suggested software citation / 建議軟體引用

NE-501 Multi Pump Controller contributors. (2026). *NE-501 Multi Pump Controller*
(version 2.0.0) [Computer software].
https://github.com/JimHaoCh/-JimHaoCh.github.io/tree/ne501-v2.0.0

The project was developed for the NE-501 research workflow with AI assistance.
New Era Pump Systems does not sponsor, certify or endorse this software.
