# Build script for RaceCraft Desktop
# Run from project root: .\build.ps1

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("exe", "msi", "installer", "all")]
    [string]$Target = "exe"
)

Write-Host "=== RaceCraft Desktop Build Script ===" -ForegroundColor Cyan
Write-Host ""

# Ensure we're in virtual environment
if (-not $env:VIRTUAL_ENV) {
    Write-Host "WARNING: Not in virtual environment. Activate with: .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "Continuing anyway..." -ForegroundColor Yellow
    Write-Host ""
}

# Clean previous builds
Write-Host "Cleaning previous builds..." -ForegroundColor Green
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }

# Install/upgrade PyInstaller
Write-Host "Ensuring PyInstaller is installed..." -ForegroundColor Green
pip install --upgrade pyinstaller

# Build executable
if ($Target -eq "exe" -or $Target -eq "all") {
    Write-Host ""
    Write-Host "Building standalone executable..." -ForegroundColor Green
    pyinstaller RaceCraft.spec

    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "SUCCESS: Executable built at dist\RaceCraft.exe" -ForegroundColor Green
        $exePath = Resolve-Path "dist\RaceCraft.exe"
        $exeSize = (Get-Item $exePath).Length / 1MB
        Write-Host "Size: $([math]::Round($exeSize, 2)) MB" -ForegroundColor Cyan
    } else {
        Write-Host "ERROR: PyInstaller build failed" -ForegroundColor Red
        exit 1
    }
}

# Build MSI
if ($Target -eq "msi" -or $Target -eq "all") {
    Write-Host ""
    Write-Host "Building MSI installer..." -ForegroundColor Green
    pip install --upgrade cx_freeze
    python setup_cx_freeze.py bdist_msi

    if ($LASTEXITCODE -eq 0) {
        Write-Host "SUCCESS: MSI installer created in dist\" -ForegroundColor Green
    } else {
        Write-Host "ERROR: MSI build failed" -ForegroundColor Red
        exit 1
    }
}

# Build Inno Setup installer
if ($Target -eq "installer" -or $Target -eq "all") {
    Write-Host ""
    Write-Host "Building Inno Setup installer..." -ForegroundColor Green

    # Check if Inno Setup is installed
    $innoPath = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $innoPath)) {
        Write-Host "ERROR: Inno Setup not found at $innoPath" -ForegroundColor Red
        Write-Host "Download from: https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
    } else {
        # First build the EXE if not already done
        if (-not (Test-Path "dist\RaceCraft.exe")) {
            Write-Host "Building executable first..." -ForegroundColor Yellow
            pyinstaller RaceCraft.spec
        }

        # Compile installer
        & $innoPath "installer\setup.iss"

        if ($LASTEXITCODE -eq 0) {
            Write-Host "SUCCESS: Installer created in dist\" -ForegroundColor Green
        } else {
            Write-Host "ERROR: Inno Setup build failed" -ForegroundColor Red
            exit 1
        }
    }
}

Write-Host ""
Write-Host "=== Build Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Output directory: dist\" -ForegroundColor Green
if (Test-Path "dist") {
    Get-ChildItem "dist" -File | ForEach-Object {
        Write-Host "  - $($_.Name) ($([math]::Round($_.Length / 1MB, 2)) MB)" -ForegroundColor Cyan
    }
}
