param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('x64', 'arm64')]
    [string]$Arch,
    [string]$Python = ''
)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

function Run-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed with exit code $LASTEXITCODE" }
}

$expected = if ($Arch -eq 'arm64') { 'win-arm64' } else { 'win-amd64' }
$candidates = New-Object 'System.Collections.Generic.List[string]'
if ($Python) {
    $candidates.Add($Python)
} else {
    $subdir = if ($Arch -eq 'arm64') { 'Python312-arm64' } else { 'Python312' }
    foreach ($root in @($env:LOCALAPPDATA, $env:ProgramFiles)) {
        if ($root) {
            $candidates.Add((Join-Path $root "Programs\Python\$subdir\python.exe"))
            $candidates.Add((Join-Path $root "$subdir\python.exe"))
        }
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $tag = if ($Arch -eq 'arm64') { '-3.12-arm64' } else { '-3.12-64' }
        try {
            $launcherPath = & $launcher.Source $tag -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $launcherPath) { $candidates.Add(($launcherPath | Select-Object -Last 1).Trim()) }
        } catch { }
    }
    $commands = @(Get-Command python.exe -All -ErrorAction SilentlyContinue)
    foreach ($command in $commands) {
        if ($command.Source -and $command.Source -notmatch '\\Microsoft\\WindowsApps\\') { $candidates.Add($command.Source) }
    }
}

$selected = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    try {
        $raw = & $candidate -c 'import sys,sysconfig,json; print(json.dumps({"platform":sysconfig.get_platform(),"version":"%d.%d" % sys.version_info[:2]}))' 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $raw) { continue }
        $info = ($raw | Select-Object -Last 1) | ConvertFrom-Json
        if ($info.platform -eq $expected -and $info.version -eq '3.12') { $selected = $candidate; break }
    } catch { }
}
if (-not $selected) {
    $hint = if ($Arch -eq 'arm64') { 'Windows installer (ARM64)' } else { 'Windows installer (64-bit)' }
    throw "Python 3.12 for $expected was not found. Install $hint from https://www.python.org/downloads/release/python-31210/ and run the build again."
}
$Python = $selected
Write-Host "Using Python: $Python ($expected)"

$venv = Join-Path (Get-Location) ".build-venv-$Arch"
Run-Checked $Python @('-m', 'venv', $venv)
$vp = Join-Path $venv 'Scripts\python.exe'
Run-Checked $vp @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'requirements.txt', '-r', 'requirements-build.txt')
Run-Checked $vp @('build/fetch_ui_font.py')
Run-Checked $vp @('build/copy_qt_translation.py')
Run-Checked $vp @('-m', 'compileall', '-q', 'main.py', 'ne501', 'ui', 'tests')
Run-Checked $vp @('-m', 'unittest', 'discover', '-s', 'tests', '-v')

$dist = Join-Path (Get-Location) "builds\$Arch"
$work = Join-Path (Get-Location) "builds\work-$Arch"
$spec = Join-Path (Get-Location) "builds\spec-$Arch"
$projectRoot = (Get-Location).Path
$assetDir = Join-Path $projectRoot 'assets'
$configFile = Join-Path $projectRoot 'config.json'
$iconFile = Join-Path $assetDir 'ne501.ico'
$versionFile = Join-Path $projectRoot 'version_info.txt'
$entryFile = Join-Path $projectRoot 'main.py'
New-Item -ItemType Directory -Force -Path $dist, $work, $spec | Out-Null
Run-Checked $vp @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
    '--name', 'NE501_Multi_Pump_Controller', '--icon', $iconFile,
    '--add-data', "$assetDir;assets", '--add-data', "$configFile;.",
    '--hidden-import', 'serial.tools.list_ports_windows',
    '--version-file', $versionFile,
    '--distpath', $dist, '--workpath', $work, '--specpath', $spec, $entryFile
)

$exe = Join-Path $dist 'NE501_Multi_Pump_Controller\NE501_Multi_Pump_Controller.exe'
if (-not (Test-Path $exe)) { throw 'PyInstaller did not create the executable.' }
$licenseDir = Join-Path $dist 'NE501_Multi_Pump_Controller\THIRD_PARTY_LICENSES'
Run-Checked $vp @('build\collect_licenses.py', $licenseDir)
$smokeDir = Join-Path $env:TEMP ("NE501-smoke-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $smokeDir | Out-Null
$report = Join-Path $smokeDir 'report.json'
$oldQt = $env:QT_QPA_PLATFORM
$oldLocal = $env:LOCALAPPDATA
try {
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:LOCALAPPDATA = $smokeDir
    $proc = Start-Process -FilePath $exe -ArgumentList ('--smoke-test-report "{0}"' -f $report) -PassThru
    if (-not $proc.WaitForExit(60000)) { $proc.Kill(); throw 'GUI smoke test timed out.' }
    if ($proc.ExitCode -ne 0 -or -not (Test-Path $report)) { throw "GUI smoke test failed ($($proc.ExitCode))." }
    $smoke = Get-Content -Raw $report | ConvertFrom-Json
    if (-not $smoke.ok -or $smoke.python_platform -ne $expected) { throw 'Unexpected GUI smoke test result.' }
    Get-Content -Raw $report | Write-Host
    Copy-Item (Join-Path $smokeDir 'timeline-preview.png') (Join-Path (Get-Location) "builds\ui-preview-$Arch.png") -Force
} finally {
    $capture = Join-Path (Get-Location) "builds\ui-shots-$Arch"
    New-Item -ItemType Directory -Force -Path $capture | Out-Null
    if (Test-Path $smokeDir) { Get-ChildItem $smokeDir -Filter '*.png' | Copy-Item -Destination $capture -Force }
    $env:QT_QPA_PLATFORM = $oldQt
    $env:LOCALAPPDATA = $oldLocal
    Remove-Item -Recurse -Force $smokeDir -ErrorAction SilentlyContinue
}
Write-Host "Build passed: $exe"

