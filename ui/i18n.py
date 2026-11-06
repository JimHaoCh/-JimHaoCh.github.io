"""Central bilingual text catalog. Language changes never access a controller."""
from __future__ import annotations
import re
from functools import lru_cache
from PySide6.QtCore import QObject, Signal, QCoreApplication, QTranslator
from ne501.config import resource_path

class LanguageManager(QObject):
    changed = Signal()
    def __init__(self):
        super().__init__()
        self.language = 'zh_TW'
        self._qt_translator = None
    def set_language(self, language):
        language = 'en' if language == 'en' else 'zh_TW'
        if self.language==language and (language=='en' or self._qt_translator is not None): return
        app=QCoreApplication.instance()
        if app is not None:
            if self._qt_translator is not None:
                app.removeTranslator(self._qt_translator);self._qt_translator.deleteLater();self._qt_translator=None
            if language=='zh_TW':
                translator=QTranslator(app)
                if translator.load(str(resource_path('assets/translations/qtbase_zh_TW.qm'))):
                    app.installTranslator(translator);self._qt_translator=translator
        if self.language != language:
            self.language = language
            tr.cache_clear()
            self.changed.emit()

manager = LanguageManager()

# Canonical templates keep raw device values separate from translated messages.
# The msg prefix identifies nested application messages; raw placeholders remain exact.
CATALOG = [
('Manual Control','手動控制'),('Timeline Editor','流程編輯'),
('NE-501 Pump Controller • UI Preview','NE-501 幫浦控制系統・介面預覽'),
('Language','語言'),('UI size','字體尺寸'),('Port','連接埠'),('Refresh COM','重新搜尋'),
('Connect','連線'),('Disconnect','中斷連線'),('Scan Pumps','掃描幫浦'),
('Refresh status','更新狀態'),('Auto refresh (2 s)','自動更新（2 秒）'),
('Simulation mode (no hardware)','模擬模式（無設備）'),
('● Disconnected','● 尚未連線'),('● Connected {raw0}','● 已連線 {raw0}'),
('EMERGENCY STOP ALL','停止所有幫浦'),('Command / response log','指令／回應紀錄'),
('Show diagnostics','顯示通訊紀錄'),('Manual control: commands operate connected pumps.','手動控制：操作會傳送至已連線的幫浦。'),
('Select available','全選可用'),('Clear selection','清除勾選'),
('Apply selected','套用勾選'),('Start selected','啟動勾選'),('Stop selected','停止勾選'),
('{raw0} selected | Addresses: {raw1}','已勾選 {raw0} 台｜位址：{raw1}'),
('Select pumps for group actions.','請勾選要進行群組操作的幫浦。'),
('Ready for group actions.','勾選的幫浦已就緒。'),
('Needs attention: {raw0}','尚未就緒：{raw0}'),
('Pump {raw0} | Address {raw1}','幫浦 {raw0}｜位址 {raw1}'),
('Pump {raw0} settings','幫浦 {raw0} 設定'),
('Pump {raw0}','幫浦 {raw0}'),
('● Offline','● 未回應'),('● Online','● 已連線'),
('● STATUS UNCONFIRMED','● 狀態未確認'),('● STOP NOT CONFIRMED','● 停止未確認'),
('Not scanned','尚未掃描'),('No response','無回應'),('Check pump','請檢查幫浦'),
('Check pump and rescan','請檢查幫浦並重新掃描'),
('Edit','設定'),('Start','啟動'),('Stop','停止'),('Group','納入群組'),
('Click Edit to configure this pump.','按設定以編輯此台幫浦。'),
('Include this pump in group actions.','將此台幫浦納入群組操作。'),
('1  Verify syringe diameter','1  確認針筒內徑'),
('Inside diameter','針筒內徑'),('Set and verify','設定並回讀'),
('Diameter not verified','內徑尚未確認'),('✓ Verified: {raw0} mm','✓ 已確認：{raw0} mm'),
('Diameter changed — SET & VERIFY again','內徑已修改，請重新設定並回讀'),
('Pump offline — diameter verification required','幫浦未回應，重新連線後須確認內徑'),
('2  Delivery settings','2  輸送設定'),('Rate','流速'),('Direction','方向'),('Mode','模式'),
('Infuse','推注'),('Withdraw','抽取'),('Continuous','連續輸送'),('Target volume','定量輸送'),
('Volume','體積'),('Prime before delivery','前置輸送（Prime）'),
('Prime speed','前置速度'),('Prime volume','前置體積'),
('Max (100%)','最高（100%）'),('High (50%)','高（50%）'),('Medium (25%)','中（25%）'),('Low (10%)','低（10%）'),('Min (5%)','最低（5%）'),
('Prime uses the selected direction and volume, then switches to the main rate. Percentages refer to the diameter-dependent pump maximum.',
 '前置輸送依設定方向與體積運行，再切換至主流速。百分比代表依針筒內徑計算的幫浦上限。'),
('Calculated Prime rate: verify syringe diameter first','請先確認針筒內徑，再計算前置流速'),
('Calculated Prime rate: {raw0} mL/hr  ({raw1} µL/min)','前置流速估算：{raw0} mL/hr（{raw1} µL/min）'),
('Calculated Prime rate: —','前置流速估算：—'),
('Apply and verify','套用並回讀'),('Applied settings','已套用設定'),
('Not applied','尚未套用'),('Settings changed — apply again','設定已修改，請重新套用'),
('Ready','就緒'),('Verify diameter first','請先確認內徑'),('Apply settings first','請先套用設定'),
('Sending command…','傳送指令中…'),('Reported: {msg0}','設備回報：{msg0}'),
('Setpoint: {msg0} · {raw0} {raw1}','設定流速：{msg0}・{raw0} {raw1}'),
('Draft: {msg0} · {raw0} {raw1}','草稿流速：{msg0}・{raw0} {raw1}'),
('Applied: {msg0} · {raw0} {raw1}','已套用：{msg0}・{raw0} {raw1}'),
('Target: {raw0} {raw1}','目標體積：{raw0} {raw1}'),
('Until stopped','持續至停止'),
('Last checked: {raw0}','最後確認：{raw0}'),('No confirmed status yet','尚無已確認狀態'),
('Status needs refresh | {raw0}','狀態待更新｜{raw0}'),
('Last response: {msg0}','最後回應：{msg0}'),
('No device read-back yet','尚無設備回讀資料'),
('Read-back: {raw0} {raw1}','設備回讀：{raw0} {raw1}'),
('Summary: {msg0} · {raw0} {raw1} · {msg1}','摘要：{msg0}・{raw0} {raw1}・{msg1}'),
('Stop available after connecting; verify the response before assuming the pump stopped.',
 '連線後可送出停止指令，須確認設備回應才能判定已停止。'),
('Adjust application text and control size','調整應用程式文字及控制項尺寸'),
('Serial connection: 19200 baud / 8N1','串列連線：19200 baud／8N1'),
('連線後停止所有實際幫浦；時間軌模擬請使用頁面內的停止。','Stop all connected pumps; use the timeline Stop button for simulation.'),
('Log file: {raw0}','紀錄檔：{raw0}'),
('Close WinPumpTerm before connecting to the COM port.','連接 COM 埠前，請先關閉 WinPumpTerm。'),
('Unable to list COM ports: {msg0}','無法搜尋 COM 埠：{msg0}'),
('No Port Selected','尚未選擇連接埠'),('Select a COM port.','請選擇 COM 連接埠。'),
('Connected: {raw0}','已連線：{raw0}'),
('Operations in progress','操作進行中'),
('Wait for queued operations to finish before disconnecting.','請等候排程中的操作完成，再中斷連線。'),
('Send STOP to all four pumps before disconnecting?','中斷連線前，是否向所有幫浦送出停止指令？'),
('Disconnect Warning','中斷連線提醒'),('Disconnected','已中斷連線'),
('Pump {raw0}：No response','幫浦 {raw0}：無回應'),
('Scan completed: {raw0}/{raw1}  online','掃描完成：{raw0}/{raw1} 台已連線'),
('Diameter verified:  {raw0} mm','針筒內徑已確認：{raw0} mm'),
('Verification failed; check the pump response','回讀確認失敗，請檢查設備回應'),
('The diameter read back from the pump does not match the entered value.','設備回讀的內徑與輸入值不一致。'),
('Syringe diameter has not been verified','針筒內徑尚未確認'),
('Program verified; {raw0}; VOL unit {raw1}','程序已確認；{raw0}；體積單位 {raw1}'),
('Program verified; Prime {raw0} ≈ {raw1} mL/hr, then {raw2}; VOL unit {raw3}',
 '程序已確認；前置輸送 {raw0} ≈ {raw1} mL/hr，接續 {raw2}；體積單位 {raw3}'),
('Program verified; prime ≈ {raw0} mL/hr, then {raw1}','程序已確認；前置流速 ≈ {raw0} mL/hr，接續 {raw1}'),
('Program verified; {raw0}','程序已確認；{raw0}'),
('Program verified','程序已確認'),('No Active Pump','尚未勾選幫浦'),
('Select at least one active pump.','請至少勾選一台幫浦。'),
('Invalid Settings','設定無效'),
('Queued commands cancelled; an operation already in progress must finish first.','已取消待執行指令；目前執行中的通訊須先完成。'),
('STOP confirmed by pump response','已收到設備停止確認'),
('STOP not confirmed: {msg0}','停止尚未確認：{msg0}'),
('STOP NOT CONFIRMED: {msg0}','停止尚未確認：{msg0}'),
('STOP not confirmed','停止尚未確認'),
('Check these pumps directly; they may still be running:\n{msg0}','請直接檢查下列幫浦，運轉狀態尚未確認：\n{msg0}'),
('Operation skipped while STOP ALL is in progress','全部停止處理中，已略過一般操作'),
('Queued operation cancelled after STOP ALL request','全部停止要求後，已取消待執行操作'),
('Queued operation cancelled after STOP request','停止要求後，已取消待執行操作'),
('Earlier operation failed after STOP ALL request: {msg0}','全部停止要求後，先前操作回報失敗：{msg0}'),
('ERROR: {msg0}','錯誤：{msg0}'),('Error：{msg0}','錯誤：{msg0}'),
('Operation Failed','操作失敗'),('Not Connected','尚未連線'),
('Connect to the COM port first.','請先連接 COM 埠。'),('Pump is offline.','幫浦尚未回應。'),
('Set and verify the syringe inside diameter first.','請先設定並回讀針筒內徑。'),
('The pump is running. Press STOP before changing settings or starting again.','幫浦運轉中，請先停止，再修改設定或重新啟動。'),
('Settings are not applied. Click APPLY & VERIFY first.','設定尚未套用，請先按「套用並回讀」。'),
('Wait for queued operations to finish before closing.','請等候排程中的操作完成，再關閉程式。'),
('Close Application','關閉程式'),('Send STOP to all four pumps before closing?','關閉前，是否向所有幫浦送出停止指令？'),
('Close Warning','關閉提醒'),
('Group result','群組操作結果'),('Succeeded: {raw0} | Failed: {raw1} | Not sent: {raw2}','成功：{raw0}｜失敗：{raw1}｜未傳送：{raw2}'),
('Not sent after an earlier group error','前一台發生錯誤，此台尚未傳送'),
('Infusing','推注中'),('Withdrawing','抽取中'),('Stopped','已停止'),('Paused','已暫停'),('Pause phase','暫停階段'),
('Waiting for trigger','等待觸發'),('Purging','前置輸送中'),('Alarm','警報'),('Unknown','未知'),
('Pump reset / power interrupted','幫浦重設／電源中斷'),('Motor stalled','馬達停滯'),
('Safe-mode communication timeout','安全模式通訊逾時'),('Pumping program error','輸送程序錯誤'),
('Program phase out of range','程序階段超出範圍'),
('Command not applicable','指令不適用'),('Value out of range','數值超出範圍'),
('Invalid command','無效指令'),('Command ignored','指令未執行'),
('Error: {msg0}','錯誤：{msg0}'),('Alarm: {msg0}','警報：{msg0}'),('Final response: {msg0}','最後回應：{msg0}'),
('NE-501 numeric data must use at most four digits','NE-501 數值最多使用四位數字'),
('Pump values must be finite and non-negative','幫浦數值須為有限的非負數'),
('Pump numeric value exceeds the four-digit limit','數值超過幫浦四位數字限制'),
('Value is too small for the selected pump unit','數值低於目前單位可表示的範圍'),
('Rounded pump value exceeds the four-digit limit','四捨五入後超過幫浦四位數字限制'),
('Value cannot be represented in NE-501 numeric format','數值無法以 NE-501 格式表示'),
('Syringe diameter must be between 0.10 and 50.00 mm','針筒內徑須介於 0.10 至 50.00 mm'),
('Invalid Prime speed level: {raw0}','前置速度檔位無效：{raw0}'),
('Invalid flow-rate unit','流速單位無效'),('Invalid rate unit','流速單位無效'),
('Rate conversion must preserve min/hr time basis','換算流速須保留 min／hr 時間基準'),
('Unsupported rate conversion','不支援此流速換算'),('Flow rate must be greater than zero','流速須大於零'),
('Flow rate {raw0} {raw1} cannot be represented by the NE-501 numeric format','流速 {raw0} {raw1} 無法以 NE-501 格式表示'),
('Invalid volume unit','體積單位無效'),('Unsupported volume conversion','不支援此體積換算'),
("Prime/target volumes cannot share one NE-501 volume unit within the pump's numeric limits",'前置及目標體積無法在幫浦數值限制內使用同一單位'),
('{raw0} rejected: {msg0} (?{raw1})','{raw0} 被拒絕：{msg0}（?{raw1}）'),
('{raw0} blocked by alarm: {msg0} (A?{raw1})','{raw0} 因警報而受阻：{msg0}（A?{raw1}）'),
('{raw0} was not accepted by the pump','幫浦未接受 {raw0}'),
('Unable to open {raw0}: {msg0}','無法開啟 {raw0}：{msg0}'),
('Serial port is not connected','串列埠尚未連線'),
('Incomplete pump response (missing ETX): {raw0}','幫浦回應不完整（缺少 ETX）：{raw0}'),
('Pump did not respond before timeout','等候幫浦回應逾時'),('Serial communication failed: {msg0}','串列通訊失敗：{msg0}'),
('Response address mismatch: expected {raw0}, received {raw1}','回應位址不一致：預期 {raw0}，收到 {raw1}'),
('Prime rate was rejected by the pump','幫浦拒絕前置流速'),
('Steady flow rate must be greater than zero','主流速須大於零'),
('Invalid steady flow-rate unit','主流速單位無效'),('Invalid target-volume unit','目標體積單位無效'),
('Invalid prime-volume unit','前置體積單位無效'),('Invalid pumping direction','輸送方向無效'),
('Prime volume must be greater than zero','前置體積須大於零'),('Invalid Prime speed level','前置速度檔位無效'),
('Target volume must be greater than zero','目標體積須大於零'),
('Selected Prime speed is not above the steady-flow rate. Choose a higher Prime speed level or lower the steady-flow rate.',
 '所選前置流速未高於主流速，請提高前置檔位或降低主流速。'),
('Program read-back mismatch: {raw0}','程序回讀不一致：{raw0}'),
('Save','儲存'),('Discard','捨棄'),('Cancel','取消'),('Yes','是'),('No','否'),('OK','確定'),('Close','關閉'),('Retry','重試'),
('Open','開啟'),('File name:','檔案名稱：'),('Files of type:','檔案類型：'),('Look in:','查詢位置：'),
('Replace file','取代檔案'),('Replace the existing file?\n{raw0}','要取代現有檔案嗎？\n{raw0}'),
]
FLOW = [
('時間軌模擬預覽  ·  0.1 秒編輯刻度；裝置同步誤差待量測。','TIMELINE SIMULATION · 0.1 s editing grid; device timing remains unmeasured.'),
('示範流程','Example workflow'),('新建','New'),('開啟','Open'),('儲存','Save'),('另存','Save as'),('區塊設定','Clip settings'),
('|◀ 起點','|◀ Start'),('1 檢查流程','1 Check'),('2 ▶ 播放','2 ▶ Play'),('Ⅱ 暫停','Ⅱ Pause'),('■ 停止','■ Stop'),
('模擬播放速度；預設為實際時間 1×。','Simulation speed; 1× follows elapsed time.'),
('幫浦 {raw0}','Pump {raw0}'),('＋ 區塊','＋ Clip'),('復原','Undo'),('重做','Redo'),('分割','Split'),('吸附','Snap'),
('游標秒數；左右方向鍵移動 0.1 秒，Shift＋方向鍵移動 1 秒。','Playhead in seconds; arrows step 0.1 s, Shift+arrows step 1 s.'),
('游標 s','Time s'),('全程','Fit'),('選取','Focus'),
('→ 推注','→ Infuse'),('← 抽取','← Withdraw'),('開始 s','Start s'),('結束 s','End s'),('方向','Direction'),('流速','Rate'),('單位','Units'),
('套用','Apply'),('取消','Cancel'),('複製','Duplicate'),('刪除','Delete'),('流程總長度（秒）','Total duration (s)'),('套用總長','Apply duration'),('載入示範','Load example'),
('預估體積依設定計算。實際針筒、管路與裝置時序需驗證。','Volumes are calculated estimates. Syringes, tubing and device timing require validation.'),
('示範流程：可先拖曳區塊，再檢查並播放。','Example: drag clips, then check and play.'),
('復原 Ctrl+Z（時間軌取得焦點時）','Undo Ctrl+Z (timeline focus)'),('重做 Ctrl+Y','Redo Ctrl+Y'),
('在所選幫浦的游標位置尋找空位；也可雙擊軌道空白處。','Find a gap at the playhead on the selected pump; double-click an empty track to insert there.'),
('在游標處分割選取區塊 Ctrl+B','Split the selected clip at the playhead Ctrl+B'),
('放大選取區塊 F','Focus selected clip F'),
('拖曳時吸附到區塊邊界或游標；按住 Alt 暫時關閉。','Snap to clip edges or playhead; hold Alt to bypass.'),
('停止模擬並保留游標位置；「起點」回到 0。','Stop simulation and keep position; Start returns to zero.'),
('套用區塊設定 Enter','Apply clip settings Enter'),('取消尚未套用的設定','Discard unapplied field edits'),
('幫浦 {raw0} · 區塊設定','Pump {raw0} · Clip settings'),('持續時間：{raw0} 秒','Duration: {raw0} s'),
('預估體積：{raw0} µL','Estimated volume: {raw0} µL'),('點選區塊以設定','Select a clip to edit'),('持續時間：—','Duration: —'),('預估體積：—','Estimated volume: —'),
('{msg0} 請重新檢查流程。','{msg0} Check the workflow again.'),
('已調整區塊。','Clip adjusted.'),('此位置已有區塊，請選擇空白時間。','A clip occupies this position. Choose an empty gap.'),
('已新增 {raw0} 秒區塊。','Added a {raw0} s clip.'),('已在 {raw0} 新增 15 秒區塊。','Added a 15 s clip at {raw0}.'),
('已複製到 {raw0}。','Duplicated at {raw0}.'),('請將游標放在選取區塊內部，再按分割。','Place the playhead inside the selected clip before splitting.'),
('已分割為相鄰兩個區塊；方向與流速均保留。','Split into adjacent clips, preserving direction and rate.'),
('已刪除區塊；Ctrl+Z 可復原。','Clip deleted; Ctrl+Z restores it.'),('已復原。','Undone.'),('已重做。','Redone.'),
('請輸入完整且有效的時間與流速。','Enter valid, complete times and rate.'),('已套用設定。','Settings applied.'),
('已取消未套用的區塊修改。','Unapplied clip edits discarded.'),('請輸入有效的總長度。','Enter a valid total duration.'),
('已套用總長度。','Duration applied.'),('已取消總長度修改。','Duration edits discarded.'),
('請先新增至少一個區塊。','Add at least one clip first.'),
('流程資料檢查完成。播放為模擬；尚未量測實際幫浦同步。','Workflow checked. Playback is simulated; device synchronization is unmeasured.'),
('模擬播放中。停止會保留游標；「起點」回到 0。','Simulation playing. Stop keeps position; Start returns to zero.'),
('模擬播放完成。','Simulation completed.'),('已暫停；可移動游標再繼續，或停止後編輯。','Paused. Reposition and resume, or stop to edit.'),
('已停止，游標保留在 {raw0}。','Stopped at {raw0}.'),('已微調區塊。','Clip nudged.'),
('尚有未套用的設定','Unapplied settings'),('先套用目前設定？\n「否」會捨棄這次欄位修改。','Apply the field edits first?\nNo discards these field edits.'),
('流程尚未儲存','Unsaved workflow'),('要儲存目前流程嗎？','Save the current workflow?'),
('請先停止播放，並套用或取消欄位修改後儲存。','Stop playback and apply or discard field edits before saving.'),
('儲存流程','Save workflow'),('儲存失敗','Save failed'),('已儲存：{raw0}','Saved: {raw0}'),
('開啟流程','Open workflow'),('流程檔超過 1 MB。','Workflow file exceeds 1 MB.'),
('流程幫浦位址 {raw0} 與目前設定 {raw1} 不一致。','Workflow addresses {raw0} do not match configured addresses {raw1}.'),
('開啟失敗','Open failed'),('已開啟：{raw0}','Opened: {raw0}'),
('新流程：先選擇幫浦，再新增區塊。','New workflow: select a pump and add clips.'),('已載入示範流程。','Example loaded.'),
('推注','Infuse'),('抽取','Withdraw'),('暫停於 {msg0}','Paused at {msg0}'),
('推注 {raw0} {raw1}','Infuse {raw0} {raw1}'),('抽取 {raw0} {raw1}','Withdraw {raw0} {raw1}'),
('暫停','Paused'),('等待','Waiting'),('停止','Stopped'),('模擬 {raw0}：{msg0}','Sim {raw0}: {msg0}'),
('▶ 繼續','▶ Resume'),('模擬播放中 · 可暫停或停止。','Simulation running · Pause or stop available.'),
('已暫停 · 可定位游標並繼續；停止後可編輯。','Paused · Reposition and resume, or stop to edit.'),
('請先套用或取消右側區塊設定。','Apply or discard clip edits in the inspector.'),
('請先套用或取消流程總長度。','Apply or discard total-duration edits first.'),
('請選擇幫浦並新增區塊。','Select a pump and add clips.'),
('編輯後，按「1 檢查流程」再播放。','After editing, use 1 Check before playback.'),
('資料已檢查 · 按播放或時間軌空白鍵開始模擬。','Checked · Play or press Space on the timeline to simulate.'),
('示範／未命名流程','Example / Untitled workflow'),('尚未指定儲存檔案','No file selected yet'),
('四幫浦時間軌','Four-pump timeline'),('拖曳移動；左右邊界調整長度；Ctrl＋滾輪縮放。','Drag to move; trim edges; Ctrl+wheel to zoom.'),
('幫浦 / 位址','Pump / Address'),('{raw0} · 模擬','{raw0} · Simulation'),
('幫浦 {raw0}  {raw1} → {raw2}  ·  {raw3} 秒','Pump {raw0}  {raw1} → {raw2} · {raw3} s'),
('{msg0}  ·  此位置與區塊衝突；放開將取消。','{msg0} · Overlap; releasing cancels this drop.'),
('幫浦 {raw0} · {raw1} – {raw2}\n{raw3} {raw4} · {raw5} 秒\n拖曳移動；邊界調整長度；F 放大選取區塊。',
 'Pump {raw0} · {raw1} – {raw2}\n{raw3} {raw4} · {raw5} s\nDrag to move; trim edges; F to focus.'),
('雙擊空白處新增；Ctrl＋滾輪縮放；左右鍵移動游標 0.1 秒。','Double-click to insert; Ctrl+wheel to zoom; arrows seek 0.1 s.'),
('已取消衝突的拖曳；原區塊保持原位。','Conflicting drop cancelled; original clip retained.'),
('已取消拖曳。','Drag cancelled.'),('放大選取區塊  F','Focus selected clip  F'),
('複製  Ctrl+D','Duplicate  Ctrl+D'),('在游標分割  Ctrl+B','Split at playhead  Ctrl+B'),('刪除  Delete','Delete  Delete'),
('→ 推注  {raw0} {raw1}','→ Infuse  {raw0} {raw1}'),('← 抽取  {raw0} {raw1}','← Withdraw  {raw0} {raw1}'),
('總長度須介於 1 秒與 7 天之間。','Total duration must be between 1 s and 7 days.'),
('四台幫浦的位址必須介於 00–99，且不可重複。','Four distinct pump addresses between 00 and 99 are required.'),
('流程區塊超過上限。','Too many workflow clips.'),('區塊識別資料不正確。','Invalid clip identifiers.'),
('區塊時間或幫浦軌道超出範圍。','Clip time or pump track is outside the valid range.'),
('區塊方向或流速單位不正確。','Invalid clip direction or rate unit.'),
('流速須介於 0.0001–9999，最多四位小數。','Rate must be 0.0001–9999 with at most four decimal places.'),
('幫浦 {raw0} 的區塊超過上限。','Too many clips on pump {raw0}.'),
('幫浦 {raw0} 的時間區塊不可重疊。','Clips on pump {raw0} must not overlap.'),
('找不到選取區塊。','Selected clip was not found.'),('分割位置必須位於區塊內部。','Split position must be inside the clip.'),
('幫浦軌道或持續時間不正確。','Invalid pump track or duration.'),
('這條軌道沒有足夠的空白時間。','There is no sufficiently long gap on this track.'),
('流程檔格式不正確。','Invalid workflow file format.'),('流程檔必須包含四條幫浦軌道。','A workflow must contain four pump tracks.'),
('幫浦軌道資料不正確。','Invalid pump-track data.'),('單一幫浦的區塊超過 200 個。','A pump track contains more than 200 clips.'),
('區塊資料必須為物件。','Clip data must be an object.'),('無法讀取流程檔，請確認格式。','Unable to read workflow; check its format.'),
]
CATALOG.extend((en, zh) for zh, en in FLOW)


CATALOG.extend([
('Stop pending — awaiting response','正在停止，等候設備回應'),
('Only online pumps with a verified diameter are included.','僅勾選已連線且內徑已確認的幫浦。'),
('Wait for the current operation to finish.','請等待目前操作完成。'),
('A timeline requires four pump addresses.','時間軌需要四個幫浦位址。'),
('Time must be a finite number','時間須為有限數值'),('Time must be in 0.1-second increments','時間須以 0.1 秒為單位'),
('Total duration must be an integer','總長度必須為整數'),('Pump index must be an integer','幫浦索引必須為整數'),
('Start must be an integer','開始時間必須為整數'),('End must be an integer','結束時間必須為整數'),
('● Example / Untitled workflow','● 示範／未命名流程'),
('Last response: —','最後回應：—'),
('Low','低'),('High','高'),('Medium','中'),('Max','最高'),('Min','最低'),
])

_exact = {}
_patterns = []
def _pattern(template):
    names = re.findall(r'\{(\w+)\}', template)
    if not names:
        return None
    parts = re.split(r'(\{\w+\})', template)
    if not re.search(r'[A-Za-z\u3400-\u9fff]', re.sub(r'\{\w+\}', '', template)):
        return None
    seen = set()
    regex = ''
    for part in parts:
        if part.startswith('{') and part.endswith('}'):
            name = part[1:-1]
            regex += '(?P='+name+')' if name in seen else '(?P<'+name+'>.*?)'
            seen.add(name)
        else:
            regex += re.escape(part)
    return re.compile('^'+regex+'$', re.DOTALL)

for en, zh in CATALOG:
    for source in (en, zh):
        pattern = _pattern(source)
        if pattern is None:
            _exact[source] = (en, zh)
        else:
            _patterns.append((len(re.sub(r'\{\w+\}', '', source)), pattern, en, zh))
_patterns.sort(key=lambda p:p[0], reverse=True)

@lru_cache(maxsize=4096)
def tr(source: str, _depth=0) -> str:
    source = str(source)
    index = 0 if manager.language == 'en' else 1
    pair = _exact.get(source)
    if pair is not None:
        return pair[index]
    if _depth < 5:
        for _, pattern, en, zh in _patterns:
            match = pattern.fullmatch(source)
            if match:
                values = {key: tr(value, _depth+1) if key.startswith('msg') else value for key,value in match.groupdict().items()}
                return (en, zh)[index].format_map(values)
        for separator in (' | ', '\n'):
            if separator in source:
                return separator.join(tr(part,_depth+1) for part in source.split(separator))
    return source
