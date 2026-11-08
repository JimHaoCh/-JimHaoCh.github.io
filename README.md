# NE-501 Multi Pump Controller — UI Preview v1.5.3

Four-pump manual control and a visual timeline editor with global Traditional Chinese / English switching.

v1.5.3 將新工作階段與新流程的四支針筒統一預設為 10 mm，預設值不代表設備已確認。範例只載入所選幫浦的區塊，保留自訂內徑、流體及入口，並回步驟 2 檢視。新檔、開檔、範例與兩種模式共用一致的準備順序；刪除空值、上下鍵同步、格式邊界、未確認停止、未完成內徑存檔及紀錄建立失敗均加入修正與回歸。

**手動控制會操作已連線設備；時間軸提供流程預覽，播放不傳送幫浦啟動指令。** 0.1 秒為編輯刻度，實機四幫浦同步誤差尚未量測。本專案與原廠無隸屬或背書關係，使用前請閱讀 [DISCLAIMER.txt](DISCLAIMER.txt)。

## 使用

- [版本下載](https://github.com/JimHaoCh/-JimHaoCh.github.io/releases)
- [繁體中文快速說明](TIMELINE_PREVIEW_README_zh.txt)
- [English quick start](BILINGUAL_UI_QUICK_START_en.txt)
- [雙語與手動介面設計、驗證範圍](BILINGUAL_MANUAL_UI_v1.5.3.md)
- [時間軌審查紀錄](UI_REVIEW_2026-11-06.md)
- [v1.5.3 原始碼審查與修正](UI_REVIEW_v1.5.3.md)
- [參考來源](REFERENCES.md)／[引用資料](CITATION.cff)

Windows x64／Windows 11 ARM64 共用安裝程式，使用者無須另裝 Python。預覽版使用與 v1.0.1 分開的安裝位置與設定；此版更新既有 UI Preview。

Manual Control operates connected pumps. Timeline playback is a calculated preview and sends no pump start commands. Device synchronization, delivered flow and tubing behavior require hardware measurements.

## 從原始碼執行

Use matching-architecture Python 3.12 and install requirements.txt. Then run:

    python build/fetch_ui_font.py
    python build/copy_qt_translation.py
    python main.py

字型從固定來源下載並驗證 SHA-256，保持原版內容並附 OFL 授權。Qt 標準繁體中文文字由已安裝的 PySide6 套件複製。完整建置與安裝程序見 build/、README_Build.txt 及 .github/workflows/windows-build.yml。

Windows CI 在 x64 與 ARM64 執行回歸測試、封裝後 GUI 啟動，以及安裝、架構辨識和解除安裝驗證；檢查完成才發布預覽安裝檔。
