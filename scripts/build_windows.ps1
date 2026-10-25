$ErrorActionPreference = "Stop"

# Build the Windows single-file executable with PyInstaller.
#
# Output:
#   dist\DesktopSmartOrganizer.exe – unsigned executable.
# NOTE: the binary is not code-signed; SmartScreen may warn on first launch.

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

python -m PyInstaller --noconfirm --clean --onefile --windowed main.py --name DesktopSmartOrganizer

if (-not (Test-Path "dist\DesktopSmartOrganizer.exe")) {
    Write-Error "dist\DesktopSmartOrganizer.exe was not produced"
    exit 1
}

Write-Output "Built dist\DesktopSmartOrganizer.exe"
