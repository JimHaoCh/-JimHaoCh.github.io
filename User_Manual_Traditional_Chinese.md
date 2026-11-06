> v1.3.0 介面操作請先參閱 BILINGUAL_MANUAL_UI_v1.3.0.md 與 QUICK_START_Traditional_Chinese.txt。以下保留早期版本的控制功能與通訊參考。

# NE-501 Multi Pump Controller v1.0.0
## 繁體中文操作說明書

適用設備：New Era NE-501 OEM Syringe Pump，多台 RS-232 串接控制

---

## 1. 軟體用途

本程式用於 Windows 電腦控制多台 New Era NE-501 OEM syringe pump。預設配置為 4 台 Pump：

- Pump 00
- Pump 01
- Pump 02
- Pump 03

每台 Pump 都有獨立控制面板，可分別設定：

- Syringe inside diameter（針筒內徑）
- Prime 是否啟用
- Prime speed（5 檔）
- Prime volume
- Steady flow rate
- Infuse / Withdraw
- Continuous steady flow 或指定 Steady target volume
- Active 群組選擇
- 個別 RUN / STOP

程式也提供：

- Apply Active
- RUN Active
- STOP Active
- EMERGENCY STOP ALL
- Command / response log
- CSV 紀錄
- Simulation mode
- UI size 字體與控制項縮放

---

## 2. 重要安全說明

本程式透過 Windows + USB/RS-232 + NE-501 通訊控制 Pump。軟體控制仍依賴電腦、USB 轉接器、線材與泵浦電源。

### 2.1 EMERGENCY STOP ALL 的限制

`EMERGENCY STOP ALL` 會對所有設定的 Pump address 發送停止命令。它屬於軟體停止功能，無法取代實體斷電或硬體緊急停止措施。

建議實驗桌上保留可立即切斷 Pump 電源的方法。

### 2.2 Prime speed 不是壓力限制

Prime 的 Max / High / Medium / Low / Min 是依 NE-501 最大推桿速度建立的軟體速度比例。

它控制的是 **推桿速度 / 流量命令**，程式沒有壓力感測器，因此無法知道微流體晶片內的實際壓力。

微流體系統壓力會受到以下因素影響：

- 管路內徑與長度
- 微流道阻力
- 接頭與閥件
- 氣泡
- 堵塞
- 液體黏度
- 晶片結構

第一次使用新的晶片或管路時，建議先從 **Min (5%)** 或 **Low (10%)** Prime 測試。

### 2.3 針筒內徑必須正確

NE-501 依 Syringe inside diameter 換算流量。輸入錯誤內徑會直接造成實際輸送流量誤差。

請使用針筒製造商提供的 **inside diameter（mm）**，不要只依 nominal syringe volume 推測。

---

## 3. 硬體與串接

建議連線方式：

```text
Windows PC
  ↓ USB
USB-to-RS232 adapter
  ↓
CBL-PC-PUMP
  ↓
Pump 00 - Computer / To Computer
  ↓ Network
Pump 01 - Computer / To Computer
  ↓ Network
Pump 02 - Computer / To Computer
  ↓ Network
Pump 03 - Computer / To Computer
```

每台 Pump 必須有唯一 address，例如：

```text
Pump 1 = 00
Pump 2 = 01
Pump 3 = 02
Pump 4 = 03
```

預設通訊：

```text
Baud rate: 19200
Data bits: 8
Parity: None
Stop bits: 1
Flow control: None
```

使用本程式前，請完全關閉 WinPumpTerm 或其他可能占用 COM port 的 serial 軟體。

---

## 4. 啟動程式

開發版：

```text
run_dev.bat
```

最終 EXE：

```text
NE501_Multi_Pump_Controller.exe
```

程式啟動後，上方會看到：

- Port
- 19200 baud / 8N1
- Refresh COM
- Connect
- Scan Pumps
- UI size
- Connection status

---

## 5. 連接 Pump

### 步驟 1：選擇 COM

按 `Refresh COM`，選擇 USB-RS232 對應的 COM port。

目前系統預設為：

```text
COM4
```

COM 編號由 Windows 決定，日後可能變成 COM3、COM5 等，因此請以 Device Manager 顯示為準。

### 步驟 2：Connect

按：

```text
Connect
```

成功時右上會顯示綠色 Connected 狀態。

### 步驟 3：Scan Pumps

按：

```text
Scan Pumps 00, 01, 02, 03
```

四台正常時，各 Pump panel 會顯示：

```text
● Online
NE501V...
```

---

## 6. 每台 Pump 的必要操作流程

GUI 最上方的流程為：

```text
1) SET & VERIFY DIAMETER
→ 2) Configure Prime / Steady Flow
→ 3) APPLY & VERIFY
→ 4) Select Active Pumps / RUN
```

請依順序操作。

---

## 7. Step 1 - 設定 Syringe inside diameter

每台 Pump 都必須先完成內徑驗證。

### 操作

1. 在 `Syringe inside diameter` 輸入實際內徑，例如：

```text
10.00 mm
```

2. 按橘色按鈕：

```text
SET & VERIFY DIAMETER
```

程式會：

1. 寫入 DIA
2. 再讀回 DIA
3. 比對輸入值與 Pump 回傳值

成功後顯示：

```text
✓ STEP 1 COMPLETE
✓ Verified: 10.00 mm
```

此時 Prime、Steady flow、Active 與 APPLY 功能才會開放。

### 修改內徑

若已驗證後又修改內徑，程式會：

- 取消原本的 Diameter verified 狀態
- 將設定標記為未套用
- 取消 Active
- 要求再次按 `SET & VERIFY DIAMETER`

---

## 8. Prime 功能

Prime 用於先快速將液體推進管路或微流體晶片，達到指定 Prime volume 後，NE-501 會自動進入 steady-flow phase。

勾選：

```text
Prime before steady flow
```

即可啟用。

### 8.1 Prime speed 五檔

| 選項 | 推桿最大速度比例 | 用途建議 |
|---|---:|---|
| Max | 100% | 低阻力、大流道、已確認可承受的系統 |
| High | 50% | 較快速充填 |
| Medium | 25% | 一般較溫和 Prime |
| Low | 10% | 微流體建議起始值，軟體預設 |
| Min | 5% | 高阻力或較脆弱晶片的初始測試 |

這 5 檔是本程式建立的軟體 preset。

程式會依「已驗證的 syringe inside diameter」自動計算 Prime rate。

例如 10.00 mm syringe 的概念值約為：

| Prime level | 約略 Prime rate |
|---|---:|
| Max | 240 mL/hr |
| High | 120 mL/hr |
| Medium | 60 mL/hr |
| Low | 24 mL/hr |
| Min | 12 mL/hr |

GUI 會顯示：

```text
Calculated Prime rate: ... mL/hr (... µL/min)
```

Pump 實際接受值可能因數字格式或 firmware rate limit 被稍微向下調整。`APPLY & VERIFY` 成功後，Last response 會顯示實際寫入的 Prime rate。

### 8.2 Prime volume

設定 Prime 要輸送的體積，例如：

```text
Prime volume = 100 µL
```

可選：

```text
µL
mL
```

### 8.3 Prime 結束後

Prime volume 完成後，Pump 會自動從 Prime phase 切換至 steady-flow phase，不需要再次按 RUN。

---

## 9. Steady flow 設定

### 9.1 Steady rate

支援四種單位：

```text
µL/min
mL/min
µL/hr
mL/hr
```

程式會自動將太大或太小、無法直接由 NE-501 數值格式表示的流速換成等效單位。

例如某些很小的 mL/hr 值可能自動改用 µL/hr 寫入 Pump。

### 9.2 Direction

可選：

```text
Infuse
Withdraw
```

Prime 與 steady flow 使用同一個方向設定。

### 9.3 Continuous steady flow

勾選：

```text
Continuous steady flow
```

表示 steady phase 持續運轉，直到使用者按 STOP。

### 9.4 Steady target volume

取消 `Continuous steady flow` 後，可輸入：

```text
Steady target volume
```

這個數值只代表 **steady-flow phase 的體積**。

例如：

```text
Prime volume = 100 µL
Steady target volume = 1 mL
```

實際完整程序輸送總量約為：

```text
100 µL Prime + 1 mL steady flow
```

steady target 完成後，程式會進入 STOP phase。

---

## 10. APPLY & VERIFY

完成設定後按：

```text
APPLY & VERIFY
```

程式會把 Pumping Program 寫入 NE-501，並逐項讀回確認。

主要檢查內容包括：

- Program phase
- Function
- Prime rate
- Prime volume
- Steady rate
- Steady volume
- Direction
- STOP phase（有限體積模式）

只有驗證通過後，RUN 才會開放。

成功時 Last response 會顯示：

```text
Program verified ...
```

如果任何指令被 Pump 拒絕，GUI 會顯示失敗 command 與錯誤原因，例如：

```text
?OOR = Value out of range
?NA  = Command not applicable
?COM = Invalid command
```

---

## 11. Active 功能

每台 Pump 都有：

```text
Active (include in group actions)
```

Active 只決定「群組按鈕」作用在哪些 Pump。

例如：

```text
Pump 00 = Active
Pump 01 = inactive
Pump 02 = Active
Pump 03 = inactive
```

此時：

```text
RUN Active
```

只會啟動 Pump 00 與 Pump 02。

每台 Pump 的個別 RUN / STOP 不受 Active 勾選影響。

---

## 12. RUN

完成：

```text
SET & VERIFY DIAMETER
→ APPLY & VERIFY
```

之後即可按：

```text
RUN
```

程式會從 Pumping Program Phase 1 開始。

如果 Prime 已啟用：

```text
RUN
→ Prime phase
→ Prime volume 完成
→ 自動 Steady flow
→ Continuous 或完成 Steady target volume 後 STOP
```

如果 Prime 未啟用：

```text
RUN
→ 直接進入 Steady flow
```

---

## 13. STOP

每台面板的紅色：

```text
STOP
```

只控制該 Pump。

程式會先查 Pump 狀態，再依 NE-501 firmware 的 stopped / paused 狀態正確處理 STP，避免 Pump 已停止時把 `?NA` 當成真正故障。

---

## 14. 群組操作

### Select All Available

把所有 Online 且已完成 diameter verification 的 Pump 設為 Active。

### Clear Active

取消所有 Active。

### Apply Active

對所有 Active Pump 逐台執行 APPLY & VERIFY。

各 Pump 仍使用自己面板上的獨立參數。

### RUN Active

啟動所有 Active 且已完成 APPLY & VERIFY 的 Pump。

### STOP Active

停止所有 Active Pump。

### EMERGENCY STOP ALL

對所有 configured addresses 發送停止流程，無視 Active 狀態。

預設為：

```text
00 / 01 / 02 / 03
```

---

## 15. UI size

若 Windows 顯示比例較高，可使用：

```text
UI size
85%
100%
115%
130%
```

設定會記住。

四台 Pump panel 位於可捲動區域，視窗空間不足時使用垂直或水平 scroll bar，避免輸入框被壓縮。

---

## 16. Command / response log

視窗底部會顯示通訊紀錄，例如：

```text
TX 00 VER | RX Stopped | NE501V3.934
TX 00 DIA 10.00 | RX Stopped
TX 00 RAT ... | RX Stopped
```

這個 log 是除錯時最重要的資訊。

發生問題時，請保留：

- Pump address
- TX command
- RX response
- Error code

---

## 17. CSV Log 位置

Windows 預設：

```text
%LOCALAPPDATA%\NE501_Multi_Pump_Controller\logs\
```

每次開啟程式會建立新的 CSV。

欄位包括：

- timestamp
- address
- command
- status
- data
- error
- alarm
- raw_hex

可用 Excel 開啟。

---

## 18. 常見問題

### 18.1 COM port 無法 Connect

確認：

1. USB-RS232 有插入電腦
2. Device Manager 可看到 Prolific USB Serial COM Port
3. 選到正確 COM number
4. WinPumpTerm 已完全關閉
5. 其他 serial monitor 已關閉

### 18.2 Pump 顯示 Offline

確認：

- 該 Pump 已開電
- Network cable 串接方向正確
- 每台 address 唯一
- 19200 baud
- 前一台 Pump 有開電，因為 network chain 需要經過前方 Pump

### 18.3 Diameter 無法 Verified

確認：

- Pump 已停止
- 輸入範圍 0.10 - 50.00 mm
- Pump 有正常回覆 DIA

### 18.4 APPLY 出現 ?OOR

表示 Pump 認為某個值超出可接受範圍。

常見原因：

- Steady rate 超過該 syringe diameter 可用流速
- 體積值無法表示
- Prime rate 接近 firmware 上限

Prime rate 具有自動向下回退機制；Steady rate 則請調整使用者設定值。

### 18.5 ?NA

`?NA` 代表 command 在目前狀態不適用。

新版 STOP 流程已針對 NE501 V3.934 的 idle `STP ?NA` 做狀態判斷。

### 18.6 Prime 太快

將 Prime speed 往下調：

```text
Max → High → Medium → Low → Min
```

微流體系統建議從 Min / Low 開始評估。

---

## 19. Simulation mode

Port 下拉選單可選：

```text
Simulation mode (no hardware)
```

可測試：

- GUI
- Diameter workflow
- Prime settings
- Active selection
- RUN / STOP

Simulation mode 不會送指令到實體 COM port。

---

## 20. 關閉程式或 Disconnect

Disconnect 或關閉程式時，GUI 會詢問是否先對所有 Pump 發送 STOP。

一般操作建議選：

```text
Yes
```

確認 Pump 已停止後再移除電源或管路。

---

## 21. 建置最終 EXE

### 21.1 第一次建立 Python 環境

先安裝 Python 3.12 64-bit，再執行：

```text
setup_dev.bat
```

### 21.2 測試

```text
run_tests.bat
```

所有測試必須 PASS。

### 21.3 最終 Release

執行：

```text
build_final_release.bat
```

完成後會建立：

```text
release\NE501_Multi_Pump_Controller_v1.0.0\
```

內容包括：

```text
NE501_Multi_Pump_Controller.exe
config.json
User_Manual_Traditional_Chinese.pdf
User_Manual_Traditional_Chinese.md
FINAL_REVIEW.md
README.md
```

目標 Windows 電腦不需要另外安裝 Python，但仍需要 USB-RS232 的 Windows driver。

---

## 22. config.json

最終 EXE 會優先讀取與 EXE 同一資料夾的：

```text
config.json
```

預設內容：

```json
{
  "port": "COM4",
  "baudrate": 19200,
  "addresses": [0, 1, 2, 3],
  "window_title": "NE-501 Multi Pump Controller v1.0.0"
}
```

Pump addresses 必須：

- 介於 0 - 99
- 不可重複

修改 config.json 後重新開啟程式即可生效。

---

## 23. 最終建議操作 SOP

日常使用建議固定依以下順序：

```text
1. 開啟 4 台 Pump 電源
2. 確認 RS-232 / Network 串接
3. 開啟程式
4. Connect
5. Scan Pumps
6. 每台 SET & VERIFY DIAMETER
7. 設定 Prime / Steady flow
8. APPLY & VERIFY
9. 勾選需要的 Active Pump
10. RUN / RUN Active
11. 實驗結束 STOP / STOP Active
12. 確認 Pump 停止
13. Disconnect
14. 關閉 Pump 電源
```

---

## 24. 版本資訊

```text
Software: NE-501 Multi Pump Controller
Version: 1.0.0
Target pump: New Era NE-501 OEM
Default network: 00, 01, 02, 03
Default baud: 19200 / 8N1
GUI language: English
Manual language: Traditional Chinese
```

### 官方技術資料參考

- New Era Pump Systems - NE-500/NE-501 Multi-Phaser User Manual
- New Era Pump Systems - NE-1000/NE-500/NE-501 Rates and Specifications
- SyringePump.com Download / Driver page

本程式為針對目前四台 NE-501 實驗系統建立的控制工具。正式實驗 SOP 應同時包含管路、微流體晶片、最大容許壓力、液體相容性與實體斷電程序。
