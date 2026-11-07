# NE-501 v1.4.1 操作說明 / Operation guide

## 先選操作模式

模式切換固定在步驟列上方。手動控制使用五步；流程模式使用四步。幫浦選擇、流體／入口名稱與針筒內徑跨模式共用，管路確認與設備回讀另行記錄。

| 模式 | 路徑 |
| --- | --- |
| 手動控制 | 1 連線對應 → 2 針筒設定 → 3 管路／排氣 → 4 手動設定 → 5 檢查啟動 |
| 流程模式（模擬） | 1 幫浦流路 → 2 針筒設定 → 3 流程編輯 → 4 檢查模擬 |

## 手動控制：裝好針筒與微流道後

1. 選擇連線埠，連線並偵測幫浦；選本次使用的幫浦，核對位址與晶片入口，勾選實體對應確認。連線可選實體設備或模擬控制器。
2. 輸入實際針筒內徑 d，單位 mm。新實驗從空白開始。內徑以淺底深字、大數值與示意圖標示；針筒容量使用 mL。需要時可單獨寫入內徑並回讀。
3. 確認針筒固定、管路接頭與出口／閥路。逐台選擇「已完成」或「本次略過」。需要排氣時展開手動定量操作，選幫浦、方向、完整流速單位及目標體積，先寫入，再按「僅啟動排氣」。停止後依實際觀察確認管路狀態。
4. 設定正式流速／單位、方向與連續或定量輸送。啟動前預送（Prime）保留在進階設定中，含五檔速度。每台幫浦保留自己的參數，也能選取群組。
5. 按「核對此幫浦」或「核對群組」，核對表列對象與用量，寫入設定並回讀，再按「啟動表列幫浦」。核對按鈕只開啟摘要；啟動對象以表列為準。單台核對時，底部提示依該台判斷待辦事項。

### 三項用量與執行時機

| 項目 | 執行時機 | 摘要記錄 |
| --- | --- | --- |
| 立即排氣／預充 | 手動第3步按下排氣啟動 | 手動排氣設定量 |
| 啟動前預送（Prime） | 正式啟動時，於正式輸送前執行 | 啟動前預送量 |
| 正式輸送 | 按下啟動表列幫浦後 | 正式流速、方向與連續／目標量 |

排氣設定量表示寫入的計畫值，實際送液量仍需量測。改寫內徑或輸送程序前，程式會撤銷該台既有的程序驗證。寫入失敗、逾時或回讀不符時，排氣需重新寫入並完整回讀；單獨重驗內徑無法恢復舊排氣的啟動權限。

## 流程模式：前段準備直接編入時間軸

1. 選擇使用的幫浦，填寫流體與入口名稱。此路徑支援離線規劃。
2. 逐台填入針筒內徑，供流速／推桿速度換算。設備寫入與獨立排氣位於手動模式。
3. 加入時間軸區塊，設定方向、流速／單位及時間。需要前段排氣／預充時，直接使用前段區塊；可搭配複製、分割、拖曳、調整邊界、吸附、縮放、快捷鍵及復原／重做。
4. 核對幫浦流路、內徑與全部啟用區塊的推進／抽取總量，再檢查模擬流程及播放。摘要使用四欄，前段準備區塊也計入總量。

流程模式沒有獨立排氣頁。流程播放為模擬，不會向幫浦發送啟動命令；0.1秒為編輯刻度，設備同步誤差尚待實機量測。

## 跨模式草稿、鎖定與檔案

- 流程區塊或總長度尚未套用時，可切回手動操作；返回流程時草稿保留。修改共用內徑、流體或入口會更新流程資料、保留草稿，並要求重新檢查流程。既有草稿仍須明確套用或取消。
- 修改內徑後，相關設備與管路確認需重新完成。無關的區塊編輯會保留尚未完成的內徑輸入，避免以舊值通過模擬檢查。
- 幫浦運轉、等待停止或指令尚未完成時，時間軸編輯器與摘要中的模擬入口採相同鎖定條件。停止與狀態顯示保留在共用區。
- JSON 保存時間軸、內徑、本次使用選擇、流體與入口名稱；手動參數、管路確認及設備回讀屬目前工作階段。匯入檔案會要求重新確認設備與管路。
- 繁體中文／English 與85–130%縮放保留設定。全域停止會停止模擬並向全部已設定位址的幫浦執行停止流程，逐台列出確認結果。

## English paths

Choose the mode above the step bar. **Manual Control** has five steps: connect/map, syringes, optional manual priming, manual settings, and review/start. **Timeline simulation** has four: pumps/paths, syringes, timeline editor, and check/simulate.

Immediate priming is a finite manual delivery with separate write, start and stop actions. Optional startup Prime runs when the reviewed manual program starts. Both planned quantities appear separately in the manual summary. Any DIA or program rewrite invalidates the old program proof before dispatch; complete read-back is required to arm priming again, including after a failed write.

Author initial preparation directly as timeline blocks. The flow summary counts all included blocks and shows no manual priming or startup Prime columns. Playback is simulation only. Independent device writes and bounded priming are restricted to Manual Control, including direct action handlers.

Unapplied block and duration drafts survive switching to manual control and shared metadata edits. Shared changes invalidate the flow check. Single-pump review guidance uses the same targets as the start action. Timeline editor and review playback share the operation gate while pumps run, STOP is pending, or commands are in progress. Global stop remains available.

Actual delivery, tubing behavior and multi-pump timing require hardware measurements. Validation scope is recorded in UI_REVIEW_v1.4.1.md.
