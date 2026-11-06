#define MyAppName "NE-501 Timeline UI Preview"
#define MyAppVersion "1.1.1"
#define MyAppExeName "NE501_Multi_Pump_Controller.exe"

[Setup]
AppId={{4D6C2834-6DF7-4921-A9C4-CBA47318A511}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\NE501_Timeline_UI_Preview
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os or arm64
ArchitecturesInstallIn64BitMode=x64os or arm64
MinVersion=10.0.17763
OutputDir=..\release
OutputBaseFilename=NE501_Timeline_UI_Preview_Setup
SetupIconFile=..\assets\ne501.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
InfoBeforeFile=..\DISCLAIMER.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\UI_REVIEW_2026-11-06.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\fonts\OFL.txt"; DestDir: "{app}\docs\NotoSansCJK"; Flags: ignoreversion
Source: "..\assets\fonts\FONT_NOTICE.txt"; DestDir: "{app}\docs\NotoSansCJK"; Flags: ignoreversion
Source: "..\builds\arm64\NE501_Multi_Pump_Controller\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: PreferArm64Files
Source: "..\builds\x64\NE501_Multi_Pump_Controller\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: PreferX64Files
Source: "..\TIMELINE_PREVIEW_README_zh.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\QUICK_START_Traditional_Chinese.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\User_Manual_Traditional_Chinese.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\User_Manual_English.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\DISCLAIMER.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\REFERENCES.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\CITATION.cff"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function PreferArm64Files: Boolean;
begin
  Result := IsArm64;
end;

function PreferX64Files: Boolean;
begin
  Result := not PreferArm64Files and IsX64Compatible;
end;

function InitializeSetup: Boolean;
var Version: TWindowsVersion;
begin
  GetWindowsVersionEx(Version);
  Result := True;
  if IsArm64 and (Version.Build < 22000) then begin
    MsgBox('ARM64 requires Windows 11 or newer.', mbError, MB_OK);
    Result := False;
  end;
end;

