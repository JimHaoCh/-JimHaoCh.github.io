# NE-501 Multi Pump Controller — UI Preview v1.3.1

Four-pump manual control and a visual timeline editor with global Traditional Chinese / English switching.

v1.3.1 補入流程針筒內徑、推桿速度換算與流速範圍檢查，並修正數字格式、回讀驗證及檔案一致性問題。手動頁提供四步操作提示，以及集中於同一設定區的套用／啟動／停止；群組區列出待處理幫浦、具體原因與導引按鈕。保留繁體中文／English 即時切換、四台幫浦摘要卡、獨立參數與設備狀態回讀。操作語言與控制資料分離。

**手動控制會操作已連線設備；時間軌播放維持模擬。** 0.1 秒為編輯刻度，實機四幫浦同步誤差尚未量測。本專案與原廠無隸屬或背書關係，使用前請閱讀 [DISCLAIMER.txt](DISCLAIMER.txt)。

## 使用

- [版本下載](https://github.com/JimHaoCh/-JimHaoCh.github.io/releases)
- [繁體中文快速說明](TIMELINE_PREVIEW_README_zh.txt)
- [English quick start](BILINGUAL_UI_QUICK_START_en.txt)
- [雙語與手動介面設計、驗證範圍](BILINGUAL_MANUAL_UI_v1.3.1.md)
- [時間軌審查紀錄](UI_REVIEW_2026-11-06.md)
- [v1.3.1 原始碼審查與修正](SOURCE_AUDIT_v1.3.1.md)
- [參考來源](REFERENCES.md)／[引用資料](CITATION.cff)

Windows x64／Windows 11 ARM64 共用安裝程式，使用者無須另裝 Python。預覽版使用與 v1.0.1 分開的安裝位置與設定；此版更新既有 UI Preview。

Manual Control operates connected pumps. Timeline playback remains simulation only. Device synchronization, delivered flow and tubing behavior require hardware measurements.

## 從原始碼執行

Use matching-architecture Python 3.12 and install requirements.txt. Then run:

    python build/fetch_ui_font.py
    python build/copy_qt_translation.py
    python main.py

字型從固定來源下載並驗證 SHA-256，保持原版內容並附 OFL 授權。Qt 標準繁體中文文字由已安裝的 PySide6 套件複製。完整建置與安裝程序見 build/、README_Build.txt 及 .github/workflows/windows-build.yml。

Windows CI 在 x64 與 ARM64 執行回歸測試、封裝後 GUI 啟動，以及安裝、架構辨識和解除安裝驗證；檢查完成才發布預覽安裝檔。
