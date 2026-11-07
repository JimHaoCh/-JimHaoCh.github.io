# NE-501 v1.4.0 操作說明 / Operation guide

## 從裝好針筒與微流道開始

1. **連線對應**：選本次使用的幫浦，核對位址；可填流體名稱與晶片入口。確認實體對應後勾選確認框。COM 連線、模擬控制器與離線規劃有各自的標識。
2. **針筒設定**：逐台填入實際針筒內徑 d，單位 mm。輸入框從空白開始，以淺色底、大數值與內側直徑示意圖標示。容量 mL 與內徑 mm 分列；內徑支援設備允許的四位數字、小數點後最多三位。
3. **管路準備**：確認針筒固定、接頭、出口／閥路與排氣狀態；選需要排氣、已完成或本次略過。這是當次使用者確認。
4. **操作設定**：選手動控制或流程編輯。手動基本欄位是流速／單位、方向與連續／定量；Prime 五檔在進階設定中。流程保留拖曳、調整邊界、複製、分割、吸附、縮放、快捷鍵與復原／重做。
5. **檢查啟動**：核對表列幫浦、位址／流路、內徑、正式輸送、啟動前預送與管路準備設定量。手動先寫入並回讀，再明確按「啟動表列幫浦」。流程按「檢查模擬流程」後「模擬播放」。

底部一次指出一個待辦項目，提供定位按鈕。各步可直接切換；離線規劃保留編輯能力。只使用兩台時，以這兩台計算已輸入與設備回讀台數。

## 設定、回讀與啟動

- 「已輸入」表示規劃資料。「設備已回讀」表示目前連線取得的設備確認值。管路確認由使用者提供，模擬檢查由程式執行，介面分別標明來源。
- 手動的「寫入並回讀」串接內徑寫入／回讀及輸送程式寫入／回讀。設定後幫浦保持停止，啟動由獨立按鈕執行。
- 手動頁的「核對此幫浦」與「核對群組」導向第5步；摘要的操作範圍可選本次全部、所選單台或手動群組。啟動對象以表列為準。
- 修改內徑後，該台設備確認與管路準備狀態失效。修改流路對應後，重新確認實體對應。修改正式參數後，重新寫入並回讀。
- 流速／體積切換單位時換算數值；超出欄位範圍時保留原單位並顯示原因。設備數值格式可能進一步量化，請核對實際回讀值。
- 運轉中鎖定設定變更，時間軌供檢視。全域狀態列持續顯示運轉回報與狀態未知的幫浦。

## 選用的排氣／預充

第3步可展開定量準備控制：選對象、方向、流速／單位與體積／單位。流速及體積從空值開始；寫入後再按「僅啟動排氣」。停止後依觀察結果選「已完成」或保留需要處理的狀態。

管路準備是獨立的定量輸送。準備用量、正式啟動前的 Prime、正式輸送體積分列。管路準備量是設定紀錄，未經流量量測；未記錄的用量顯示未記錄。準備完成後等待使用者啟動正式輸送。

## 檔案與狀態

JSON 保存時間軌、各台內徑、本次使用選擇、流體與入口名稱。這些規劃欄位支援復原／重做。手動輸送參數與管路／設備確認屬目前工作階段；檔案不保存設備回讀證明。載入實驗規劃後需重新核對設備與管路。

舊版檔案缺少的欄位以相容預設處理；舊檔有區塊的軌道列入本次使用，缺少內徑時要求補入。未納入的軌道保留區塊，模擬時略過。示範流程須由「載入示範流程（模擬）」明確載入，內徑 10 mm 僅為示範資料。

## 停止與診斷

「停止所有幫浦」會停止模擬並向所有已設定位址的幫浦執行停止流程。各台停止結果須以回報確認；未回應顯示狀態未知。停止優先於佇列中的舊啟動工作。錯誤提示採非模態視窗，保留全域停止的操作入口。

繁體中文／English 與字體縮放保留資料與狀態。診斷可展開指令紀錄，CSV 每次啟動使用獨立檔名。

## English quick path

1. **Connect & map**: choose the pumps used, check physical addresses and fluid paths, then confirm the mapping.
2. **Syringes**: enter actual inside diameters in mm. New experiments start blank. Plan entries and current device read-backs have separate labels.
3. **Tubing**: confirm preparation, choose an explicit skip, or use bounded priming. Priming has its own write, start and stop actions.
4. **Operation**: choose manual delivery or timeline simulation. Startup Prime and conversion details are expandable. Each pump retains independent settings.
5. **Review & start**: inspect targets, directions, full units and volume stages. Write/read back manual settings, then explicitly start the listed pumps. Review buttons themselves send no motor commands.

Timeline playback is simulation only. Real pump operations are available through manual control and bounded priming. Hardware flow, tubing behavior and multi-pump synchronization need physical measurements. A 0.1 s editing grid does not establish hardware timing accuracy.
