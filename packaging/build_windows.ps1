# Build NOVA for Windows: the folder dist\NOVA (NOVA.exe + everything it needs), a .zip of it and,
# when Inno Setup is installed, the setup program dist\NOVA-<version>-setup.exe.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#
# The build is not code-signed: Windows SmartScreen will warn the first time the setup program is run on another PC.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) { python -m venv .venv }
$py = ".venv\Scripts\python.exe"
& $py -m pip install --quiet -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "installing the packages failed" }

$dist = if ($env:NOVA_DIST) { $env:NOVA_DIST } else { "dist" }      # NOVA_DIST=dist_next builds next to an app that is still open
if (Get-Process -Name "NOVA" -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*\$dist\NOVA\*" }) {
    throw "NOVA is running from $dist\NOVA - quit it first (or build elsewhere: `$env:NOVA_DIST = 'dist_next')"
}
Remove-Item -Recurse -Force "build_$dist", $dist -ErrorAction SilentlyContinue
& $py -m PyInstaller --noconfirm --distpath $dist --workpath "build_$dist" NOVA-windows.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$app = Join-Path $dist "NOVA"

Write-Host "> self-test"                          # with a throw-away data folder: the build never touches your own
$env:NOVA_DATA_DIR = Join-Path ([System.IO.Path]::GetTempPath()) ("nova_selftest_" + [guid]::NewGuid().ToString("N"))
$env:NOVA_NO_MIGRATE = "1"
& (Join-Path $app "NOVA-cli.exe") --selftest
if ($LASTEXITCODE -ne 0) { throw "the packaged app failed its self-test" }
Remove-Item -Recurse -Force $env:NOVA_DATA_DIR -ErrorAction SilentlyContinue
Remove-Item Env:\NOVA_DATA_DIR, Env:\NOVA_NO_MIGRATE

$version = (Select-String -Path "paths.py" -Pattern '^__version__\s*=\s*"(.*)"').Matches[0].Groups[1].Value
$zip = Join-Path $dist "NOVA-$version-windows.zip"
Write-Host "> zip"
Compress-Archive -Path $app -DestinationPath $zip -Force

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    Write-Host "> setup program"
    & $iscc /Qp "/DAppVersion=$version" "/DSourceDir=$((Resolve-Path $app).Path)" "/DOutputDir=$((Resolve-Path $dist).Path)" "packaging\nova.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
    Write-Host "done: $app , $zip and $dist\NOVA-$version-setup.exe"
} else {
    Write-Host "Inno Setup is not installed - no setup program was made (the folder and the .zip are complete)."
    Write-Host "done: $app and $zip"
}
