v1.4.0：建置結果為 release/NE501_UI_v1.4.0_Setup.exe；版本、兩種架構及安裝驗證見 build/ 與 .github/workflows/windows-build.yml。

NE-501 Multi Pump Controller v1.0.1 — 建置說明

重要：本壓縮包是原始碼與建置工具，目前不含已編譯的 EXE 或安裝程式。
以下建置流程尚待 Windows 與實際幫浦驗證。

一、在 M5 Mac 的 Parallels Windows 11 ARM 建置本機版本

1. 在 Windows 檔案總管的地址列輸入 %LOCALAPPDATA%，按 Enter。
   在該 Windows 本機資料夾建立 NE501，並將本壓縮包解壓縮到其中。
   Mac 的 Downloads 共用路徑通常是 \\Mac\...，建議先複製到上述
   Windows 本機路徑再建置。
2. 安裝 Python 3.12.10「Windows installer (ARM64)」：
   https://www.python.org/downloads/release/python-31210/
   安裝時選取 Add python.exe to PATH；保留 pip 元件與 Python launcher。
3. 如要確認，開啟新的 Windows 命令提示字元，輸入：
   py -3.12-arm64 -c "import sysconfig; print(sysconfig.get_platform())"
   預期顯示 win-arm64。若仍找不到 Python，請確認是在 Windows 虛擬機
   內安裝 ARM64 版，並重新開啟命令提示字元。
4. 在解壓縮後的資料夾，雙擊 BUILD_THIS_WINDOWS.bat。
   電腦必須連網，腳本會下載指定版本的程式套件並執行測試與打包。
5. 若腳本顯示 Build passed，執行：
   builds\arm64\NE501_Multi_Pump_Controller\NE501_Multi_Pump_Controller.exe
   請保留同一資料夾中的 _internal 子資料夾。這是 ARM64 單架構
   可攜式程式，並非含兩種架構的安裝程式。
6. 在 Parallels 將 USB 轉 RS-232 裝置連到 Windows，安裝對應的 ARM64
   驅動，於裝置管理員確認 COM 埠。先以 Simulation 測試介面，再進行
   依實驗室 SOP 安排的單台及四台實機測試。

二、在一般 Intel / AMD Windows 電腦建置

使用 Python 3.12.10 Windows installer (64-bit)，同樣雙擊
BUILD_THIS_WINDOWS.bat。應顯示 win-amd64，輸出位於 builds\x64。

三、製作同時包含 x64 和 ARM64 的單一安裝檔

兩種版本均須先完成 build_arch.ps1 與程式啟動測試，再將兩個
builds\x64 和 builds\arm64 目錄放回同一份專案。於 Windows 安裝
Inno Setup 6.3 以上，執行 build\assemble_installer.ps1。
也可在已授權的 GitHub 儲存庫使用內附 Actions 流程分別建置和測試。
尚未執行的流程不能視為成功或已通過驗證。

四、設定與限制

設定：%LOCALAPPDATA%\NE501_Multi_Pump_Controller\config.json
紀錄：%LOCALAPPDATA%\NE501_Multi_Pump_Controller\logs\

全停止仍需依賴通訊；正在執行的命令會先完成。虛擬機休眠、斷線或
電腦關閉時，泵浦狀態需以實體設備確認。應保留獨立斷電方法。
