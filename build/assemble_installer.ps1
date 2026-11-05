$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
foreach ($arch in @('x64', 'arm64')) {
    $exe = "builds\$arch\NE501_Multi_Pump_Controller\NE501_Multi_Pump_Controller.exe"
    if (-not (Test-Path $exe)) { throw "Missing $arch build: $exe" }
}
$candidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe')
)
$iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw 'Install Inno Setup 6.3+ or 7, then run this script again.' }
& $iscc 'build\installer.iss'
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }
$installer = 'release\NE501_Multi_Pump_Setup_v1.0.1.exe'
if (-not (Test-Path $installer)) { throw 'The installer file was not produced.' }
Get-FileHash $installer -Algorithm SHA256 | Format-List
Write-Host "Installer ready: $installer"
