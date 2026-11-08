# NE-501 V2.0.0 審查與缺陷修正

審查日期：2026-11-08。基準：v1.5.3，commit `4d6aa3ab4d2460e486d1512042a6b9fbf7217e01`。

本輪依使用者要求查閱公開幫浦控制專案與官方文件，將相關故障情境轉為本專案可重現測試，修正後發布 V2.0.0。保留已接受的三階段手動操作、單一針筒內徑頁、10 mm 初值、直接鍵入／刪除／上下調整、獨立預充、同頁啟停，以及進階時間軸編輯。

## 外部來源與本專案的核對方式

以下是來源記載的行為或開發注意事項，不代表已對其他專案做完整測試。新增修正均依本專案故障注入結果決定，未複製其他專案程式碼。

| 一手來源 | 查閱重點 | 本專案的對應檢查 |
| --- | --- | --- |
| [ClarkLabUCB/NewEraPumps_Python3](https://github.com/ClarkLabUCB/NewEraPumps_Python3)，README：Using the Pump GUI／Assign Pump Syringe Size | 作者提醒停止後再改針筒規格，並區分設定與目前流速 | 確認 DIA／程序可寫狀態；已寫入設定與草稿分離；維持設備回讀 |
| [RomeroLab/syringe-pump-controller](https://github.com/RomeroLab/syringe-pump-controller)，README | NE-500/501 微流體控制的早期 GUI 專案 | 對照選泵、流速、單位與停止的操作路徑；不沿用其舊 Python／Qt 架構 |
| [hiro-shikata/SyringeGUI](https://github.com/hiro-shikata/SyringeGUI)，README §3.4–3.5 | 單位換算、分別啟停、流程暫停／續跑與中止的不同語意 | 單位草稿換算；個別停止保留進度；全部停止重設程序；預充不隨正式續跑重複 |
| [MWorks NE-500 pump](https://mworks.github.io/documentation/latest/components/ne_500_syringe_pump.html) 與 [network](https://mworks.github.io/documentation/latest/components/ne_500_syringe_pump_network.html)，rate_unit／volume_unit／response_timeout／log_pump_commands | 內徑、流速與體積單位相依；通訊有明確逾時與指令紀錄 | 核對共享 VOL 單位、逾時處理、指令與結果紀錄；不套用其他環境的逾時值 |
| [原廠 NE-500/501 V3.9 手冊](https://www.syringepump.com/download/NE-500%20OEM%20Syringe%20Pump%20User%20Manual%20V3.9.pdf)，§5.9、§7.3.12、§8.3–8.5（PDF 第 12、19、31–39 頁） | 程序等待仍可自動續跑；P 與 T/U 不同；STP 的暫停／重設語意；Basic 封包及警報回覆 | 對照完整狀態分類、等待鎖定、停止確認、警報後舊驗證失效及封包解析 |
| [pySerial 3.5 API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html)，write／read／reset_input_buffer | write 回傳傳送長度；有讀寫逾時；清除輸入不保證先前動作未執行 | 模擬部分傳送、遺失回覆與雜訊；不自動重送 RUN |
| [Qt QAbstractSpinBox](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QAbstractSpinBox.html)，keyboardTracking／interpretText | 關閉 keyboardTracking 時，輸入中的文字可能尚未更新數值 | 單位切換前驗證並提交目前可見草稿，避免以舊值換算 |

## 可重現缺陷、修正與驗證

| 缺陷與預期結果 | 修正位置 | 新增自動驗證 |
| --- | --- | --- |
| T/U 被當成停止，可能開放修改或流程預覽。應視為仍在執行的程序 | protocol.py、pump_panel.py、main_window.py | 等待狀態禁止寫入／RUN／預覽；關閉自動更新仍持續查詢；停止接受 P |
| RUN 已讓虛擬馬達啟動，但回覆逾時後 UI 未保留可能運轉狀態。應顯示未確認，保留 STOP，不重送 RUN | manual_station.py、pump_panel.py | 注入「執行 RUN 後丟棄回覆」；一次送出；停止確認後仍須重新寫入 |
| 失聯後單台 STOP 已取得有效回覆，仍顯示離線，阻擋直接重新寫入 | manual_station.py、pump_panel.py | 有效停止回覆恢復連線顯示；舊驗證仍失效；可直接重新寫入並取得新驗證 |
| 群組中途發生啟動逾時。應保留先前成功狀態與失聯台的不確定狀態，後續台不啟動 | manual_station.py | 三台群組在第二台遺失回覆；確認第一台運轉、第二台未確認、第三台未送 RUN；全部停止逐台確認 |
| 舊相容啟動入口可繞過統一的寫入／讀回檢查 | main_window.py | 舊單台／群組入口均走相同手動啟動路徑；未寫入時不送 RUN |
| 原廠警報可被下一次查詢清除，提示可能消失。應保留非阻擋提醒並取消舊驗證 | main_window.py、manual_station.py | 初次偵測與背景更新共用警報處理；重複警報只提示一次；後續 P 不恢復舊啟動資格；重新完整寫入後可建立新驗證 |
| 缺 STX／ETX、未知狀態或非 ASCII 回覆可能被當成成功 | protocol.py、controller.py | 損壞封包不能確認指令；只從真正 STX 同步；支援既有一／二位位址與已知狀態 |
| 忽略 write 的傳送長度，部分傳送可能誤判成功 | controller.py | 短傳送立即回報失敗，不補送／重送 RUN |
| STP 回覆有合法狀態，但不是 S，仍可能繼續寫設定 | controller.py | DIA／程序只在確認重設 S 後寫入；確認失敗時無後續設定指令 |
| 回讀使用子字串或未完整錨定數值，尾隨資料可能取得驗證 | controller.py、manual_program.py | DIA、FUN、DIR、RAT、VOL 尾隨或前置多餘資料均不取得驗證；保留原廠正常格式 |
| 單位切換讀到先前快取數值，或在零值時略過無效草稿 | unit_fields.py | 未提交的 20 µL/min 正確換算為 1200 µL/hr；不完整數字保留原文字與單位 |
| 英文按鈕的 & 被 Qt 當成快捷鍵標記，文字顯示不完整 | i18n_widgets.py | 將自然文字的 & 轉義為可見符號；不建立隱藏快捷鍵；語言切換保留顯示 |

第一批 15 項測試在基準版執行時重現失敗，之後擴充至 24 項；修正後 24 項通過。既有案例保留，完整回歸共 269 項。新增封裝／安裝檢查直接重現 T/U 停止與遺失 RUN 回覆，確認不自動重送及舊驗證失效。

## 發布驗證與限制

發布程序要求完整回歸、來源與封裝 GUI 啟動、Windows x64／ARM64 版本與架構、安裝／解除安裝均成功，才建立下載安裝檔。畫面檢查涵蓋中英文、準備頁與操作台，以及既有不同縮放案例。

測試採虛擬控制器、可控制時鐘與替代串列 I/O。未連接 NE-501 實機，因此不宣稱已量測實際流量、同步誤差、停止延遲、壓力或針筒剩餘量。Basic 模式沒有可用於每次動作的交易編號，遺失回覆時不能保證判斷動作是否已執行；本版以狀態未確認、禁止重啟、查詢與確認停止處理。

原廠的安全通訊模式、通訊看門狗、電源恢復及外部 TTL 設定涉及持續性設備狀態，本版未自動改寫。亦未新增實機時間軸執行、剩餘針筒容量追蹤或壓力感測。這些需另定硬體規格與驗證條件；目前流程播放維持預覽。既有 JSON 格式與明確空內徑值相容，載入計畫不代表設備已驗證。
