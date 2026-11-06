param(
    [Parameter(Mandatory = $true)] [ValidateSet('x64', 'arm64')] [string]$Arch,
    [Parameter(Mandatory = $true)] [string]$Installer
)
$ErrorActionPreference = 'Stop'
$base = Join-Path $env:TEMP ("NE501-install-test-" + [guid]::NewGuid().ToString('N'))
$target = Join-Path $base 'app'
$userData = Join-Path $base 'user'
New-Item -ItemType Directory -Force -Path $base, $userData | Out-Null
$installer = (Resolve-Path $Installer).Path
$args = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR="{0}"' -f $target
$setup = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
if ($setup.ExitCode -ne 0) { throw "Installer returned $($setup.ExitCode)." }
$exe = Join-Path $target 'NE501_Multi_Pump_Controller.exe'
if (-not (Test-Path $exe)) { throw 'Installed executable is missing.' }

# Verify the PE machine field, independent of the host process architecture.
$reader = New-Object System.IO.BinaryReader([System.IO.File]::OpenRead($exe))
try {
    [void]$reader.BaseStream.Seek(0x3c, [System.IO.SeekOrigin]::Begin)
    $pe = $reader.ReadInt32()
    [void]$reader.BaseStream.Seek($pe, [System.IO.SeekOrigin]::Begin)
    if ($reader.ReadUInt32() -ne 0x4550) { throw 'Invalid PE signature.' }
    $machine = $reader.ReadUInt16()
    $expectedMachine = if ($Arch -eq 'arm64') { 0xaa64 } else { 0x8664 }
    if ($machine -ne $expectedMachine) { throw ('Unexpected PE machine: 0x{0:X}' -f $machine) }
} finally { $reader.Close() }

$expectedPlatform = if ($Arch -eq 'arm64') { 'win-arm64' } else { 'win-amd64' }
$oldQt = $env:QT_QPA_PLATFORM
$oldLocal = $env:LOCALAPPDATA
$report = Join-Path $base 'smoke.json'
try {
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:LOCALAPPDATA = $userData
    $proc = Start-Process -FilePath $exe -ArgumentList ('--smoke-test-report "{0}"' -f $report) -PassThru
    if (-not $proc.WaitForExit(60000)) { $proc.Kill(); throw 'Installed application timed out.' }
    if ($proc.ExitCode -ne 0 -or -not (Test-Path $report)) { throw 'Installed application smoke test failed.' }
    $smoke = Get-Content -Raw $report | ConvertFrom-Json
    if (-not $smoke.ok -or $smoke.python_platform -ne $expectedPlatform) { throw 'Wrong installed application architecture.' }
    $config = Join-Path $userData 'NE501_Timeline_UI_Preview\config.json'
    if (-not (Test-Path $config)) { throw 'User config was not created.' }
    $uninstaller = Join-Path $target 'unins000.exe'
    if (-not (Test-Path $uninstaller)) { throw 'Uninstaller is missing.' }
    $uninstall = Start-Process -FilePath $uninstaller -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' -Wait -PassThru
    if ($uninstall.ExitCode -ne 0 -or (Test-Path $exe)) { throw 'Uninstall failed.' }
    if (-not (Test-Path $config)) { throw 'Uninstall unexpectedly removed user configuration.' }
    Write-Host "Installer, architecture, GUI simulation and uninstall passed for $Arch."
} finally {
    $env:QT_QPA_PLATFORM = $oldQt
    $env:LOCALAPPDATA = $oldLocal
}
