# NE-501 v1.4.2 操作說明

## 名稱與判斷方式

| 介面位置 | 名稱 | 意義 |
| --- | --- | --- |
| 功能分頁 | 手動控制 | 操作連線中的幫浦，含獨立排氣與正式輸送 |
| 功能分頁 | 流程編輯 | 設計時間軸、檢查資料及預覽 |
| 連線狀態 | 示範模式 | 虛擬控制器連線，用於介面與指令操作練習 |
| 連線狀態 | 實機連線 | 開啟實體控制器連線；設備狀態逐台依回報確認 |
| 連線狀態 | 離線規劃 | 沒有控制器連線，仍可編輯流程 |
| 播放狀態 | 流程預覽 | 播放設定的時間軸、估算各段輸送量，不傳送幫浦啟動指令 |
| 資料入口 | 載入範例流程 | 載入內建範本，維持原本的連線類型 |

「流程編輯」分頁固定使用功能名稱。連線示範模式後切換分頁，控制器仍為虛擬幫浦；連線實機後載入範例，仍保留實機連線標示。範例內徑10 mm是資料範本，使用實際針筒時須重新填寫與確認。

## 裝好針筒與微流道後：手動路徑

1. **連線對應**：選連接埠，連線偵測；選本次使用的幫浦，核對位址與流體入口，勾選實體對應確認。練習操作時從連接埠清單選「示範模式（虛擬幫浦）」。
2. **針筒設定**：填入實際內徑d，單位mm。輸入值與設備回讀分列；容量mL與內徑mm使用不同欄位。需要時可單獨寫入內徑並回讀。
3. **管路／排氣**：檢查針筒固定、接頭與出口／閥路。選擇已完成或本次略過；需要排氣時展開定量操作，指定幫浦、方向、流速及體積，先寫入，再單獨啟動排氣。完成後依實際觀察確認管路狀態。
4. **手動設定**：設定正式流速、完整單位、方向、連續或定量。啟動前預送（Prime）保留在進階設定，含五檔速度。單台與群組各有核對入口。
5. **檢查啟動**：核對表列對象、流路、內徑、正式輸送、啟動前Prime與手動排氣設定量。寫入並回讀後，明確按下啟動。獨立排氣、啟動前Prime與正式輸送分別核對執行時機和用量。

改寫內徑或程序前撤銷該台舊驗證。寫入失敗或回讀不符後，需重新寫入並完整回讀；單獨重驗內徑會保留程序待確認狀態。

## 流程編輯路徑

1. **幫浦流路**：選擇幫浦，填寫流體與入口名稱；支援離線規劃。
2. **針筒設定**：逐台填入內徑，供流速與推桿速度換算。
3. **流程編輯**：新增區塊，設定方向、流速／單位、起訖時間。前段排氣／預充直接編排為區塊。保留拖曳、調整邊界、複製、分割、吸附、縮放、快捷鍵、復原／重做。
4. **檢查預覽**：核對全部啟用區塊的推進／抽取總量，檢查流程後預覽播放。分軌狀態使用「預覽」標示；暫停可定位游標，停止後可編輯。

獨立排氣與寫入設備操作位於手動模式。流程預覽不會執行實體幫浦的時間軸程序。0.1秒表示編輯刻度，實際多泵同步誤差仍需量測。

## 檔案、草稿與狀態

新空白流程顯示「未命名流程」。載入範例後另存檔，檔名會替換該標示。JSON保存時間軸、使用的幫浦、內徑及流體／入口；手動輸送值、設備驗證及管路確認屬目前工作階段。載入計畫後重新核對設備與管路。

流程區塊或總長度草稿可保留到切回流程時。共用準備資料更新會要求重新檢查流程。運轉、待停止與指令進行狀態由編輯器與摘要共用鎖定條件。

斷線後若仍有未確認停止的紀錄，狀態列保留幫浦清單。此時需回到手動連線、讀取狀態，再依設備回報處理。全域停止會停止預覽，並向所有已設定位址執行停止流程；結果逐台確認。

## 已知限制與後續建議

示範控制器以指令回覆為主，尚未依時間自動完成定量輸送或推進Prime階段。全域停止需等待當前程序設定／回讀批次完成。取消載入範例時，計畫資料會保留，頁面仍可能切到流程編輯。這些邏輯列為後續改善，詳見UI_REVIEW_v1.4.2.md。

## English naming guide

Manual Control and Timeline Editor are functional tabs. Demo mode identifies a virtual-pump connection; Real pump connection and Offline planning identify the other connection categories. Loading an example workflow changes planning data without switching the controller. Blank projects use Untitled workflow.

Timeline playback is Flow preview. It estimates volume and sends no pump start commands, including when a real controller is connected. Manual writes, independent priming and reviewed manual starts remain separate. Demo command acknowledgements do not yet model time-based finite delivery or Prime phase completion. Active configuration batches finish before the queued global STOP worker. Follow-up recommendations and reproducible cases are recorded in UI_REVIEW_v1.4.2.md.
