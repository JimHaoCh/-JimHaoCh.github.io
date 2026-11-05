# NE-501 Multi Pump Controller v1.0.1

獨立的研究與教學軟體，以 New Era NE-501 多台針筒幫浦 RS-232 控制為目標。
本專案與原廠無隸屬、授權或背書關係。預設四台泵浦，位址 00–03。
目前是 v1.0.1 候選版，需完成 Windows 建置及實體泵浦驗證。

**使用前請閱讀 [免責與安全說明](DISCLAIMER.txt)。** 程式未提供臨床驗證
資料，請勿用於人體輸注或臨床治療。軟體全停止依賴通訊，操作設備時
請保留獨立的實體斷電或緊急停止方式；Prime 選項不測量或限制壓力。

Windows x64 and Windows 11 ARM64 build project, derived from v1.0.0.
This is independent research/educational software with no manufacturer
affiliation or endorsement. The v1.0.1 candidate requires hardware validation.
See [DISCLAIMER.txt](DISCLAIMER.txt) before operation.

For the M5 Mac / Parallels workflow see `README_Build.txt`.
For users of a successfully built installer see `QUICK_START_Traditional_Chinese.txt`.
References, credits and suggested citation are in [REFERENCES.md](REFERENCES.md).
Third-party license information is in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The installer script combines separately built x64 and ARM64 onedir applications.
The GitHub Actions workflow builds both, compiles a single Inno Setup installer,
and tests installation, executable architecture, simulation and uninstall on
Windows runners. The workflow must run successfully before distribution.

The pump protocol and Prime/steady-flow commands are based on v1.0.0. Changes:

* Per-user JSON configuration is retained across upgrades and uninstall.
* STOP ALL attempts remaining addresses after one pump times out; the display
  marks unconfirmed responses explicitly.
* A STOP ALL request invalidates queued operations, including queued RUN.
  An operation already executing must finish before the software stop runs.
* Worker callbacks are queued onto Qt's GUI thread.
* A simulation-only executable smoke test is available to the build pipeline.

The software stop depends on the PC, virtual machine, serial adapter, cables and
pump. It is not an independent hardware safety circuit. No pressure sensing or
continuous telemetry has been added. Follow the existing lab SOP and verify all
four pumps before unattended operation.

Documentation marked v1.0.0 describes the earlier version. The project-specific
source-code license has not been designated. Third-party licenses still apply.
