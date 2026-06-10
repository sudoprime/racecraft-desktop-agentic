# Building and Packaging RaceCraft Desktop

## Quick Start

### 1. Setup Virtual Environment

```powershell
# Create virtual environment
python -m venv venv

# Activate (PowerShell)
.\venv\Scripts\Activate.ps1

# If you get execution policy error:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Activate (Command Prompt)
venv\Scripts\activate.bat

# Install dependencies
pip install -r requirements.txt
```

### 2. Run in Development Mode

```powershell
python -m racecraft.app
```

### 3. Build Distribution Packages

```powershell
# Build standalone EXE
.\build.ps1 -Target exe

# Build MSI installer
.\build.ps1 -Target msi

# Build Inno Setup installer (requires Inno Setup installed)
.\build.ps1 -Target installer

# Build everything
.\build.ps1 -Target all
```

## Distribution Options Comparison

| Method | Size | Pros | Cons | Best For |
|--------|------|------|------|----------|
| **Standalone EXE** | ~150MB | Easy, single file | Large, unsigned warnings | Quick testing, internal use |
| **MSI Installer** | ~150MB | Professional, Windows native | Requires admin | Corporate deployment |
| **Inno Setup** | ~80MB | Small, customizable | Extra tool required | Public distribution |
| **ZIP Archive** | ~150MB | Simple | Manual setup | Beta testers |

## Detailed Build Instructions

### Option 1: PyInstaller (Standalone EXE)

**Best for**: Quick distribution, testing, portability

```powershell
# Install PyInstaller
pip install pyinstaller

# Build using spec file (recommended)
pyinstaller RaceCraft.spec

# Or build directly (less control)
pyinstaller --onefile --windowed --name RaceCraft --icon=assets/icon.ico racecraft/app.py
```

**Output**: `dist/RaceCraft.exe` (~150-200MB)

**Pros**:
- Single executable file
- No installation needed
- Works on any Windows system

**Cons**:
- Large file size (includes Python interpreter + libraries)
- Slower startup time
- Windows Defender may flag (unsigned)

**Reducing size**:
- Use `--exclude-module` for unused packages
- Use UPX compression (already enabled in spec)
- Remove debug symbols

### Option 2: cx_Freeze (EXE + Dependencies)

**Best for**: Faster startup, smaller per-file sizes

```powershell
pip install cx_freeze

# Build executable
python setup_cx_freeze.py build

# Build MSI installer
python setup_cx_freeze.py bdist_msi
```

**Output**:
- `build/exe.win-amd64-3.11/` folder with EXE + DLLs
- `dist/RaceCraft-0.1.0-win64.msi` (for MSI build)

**Pros**:
- Faster startup than PyInstaller
- Native MSI creation
- Smaller individual files

**Cons**:
- Folder of files (not single EXE)
- Slightly more complex

### Option 3: Inno Setup (Professional Installer)

**Best for**: Public distribution, professional appearance

**Prerequisites**:
1. Download Inno Setup: https://jrsoftware.org/isdl.php
2. Install to default location

**Steps**:
```powershell
# 1. Build EXE first
pyinstaller RaceCraft.spec

# 2. Build installer
.\build.ps1 -Target installer

# Or manually compile
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss
```

**Output**: `dist/RaceCraft-Setup-0.1.0.exe` (~80MB compressed)

**Features**:
- Professional installer wizard
- Start menu shortcuts
- Desktop icon option
- Auto-start option
- Clean uninstaller
- Much smaller than raw EXE (LZMA compression)

**Customization**:
Edit `installer/setup.iss` to change:
- Company name
- Install location
- Shortcuts
- Registry entries
- Prerequisites

### Option 4: ZIP Distribution

**Best for**: Beta testing, power users

```powershell
# Build EXE
pyinstaller RaceCraft.spec

# Create ZIP
Compress-Archive -Path dist\RaceCraft.exe,assets,config -DestinationPath dist\RaceCraft-v0.1.0.zip
```

## Code Signing (Removing Windows SmartScreen Warnings)

Unsigned executables trigger Windows SmartScreen warnings. To fix:

### 1. Get a Code Signing Certificate

**Options**:
- **DigiCert** ($299/year) - Most trusted
- **Sectigo/Comodo** ($199/year) - Popular
- **SSL.com** ($249/year) - Good reputation
- **SignPath** (Free for open source!) - https://about.signpath.io/

**For open source projects**: SignPath Foundation offers free code signing!

### 2. Sign the Executable

```powershell
# Using signtool.exe (comes with Windows SDK)
signtool sign /f "certificate.pfx" /p "password" /tr "http://timestamp.digicert.com" /td sha256 /fd sha256 "dist\RaceCraft.exe"

# Verify signature
signtool verify /pa "dist\RaceCraft.exe"
```

### 3. Build Reputation

Even with a certificate, new executables may trigger warnings until they build reputation through downloads. This takes time (weeks/months).

## Building for Different Python Versions

If users have different Python versions:

```powershell
# Build with specific Python
C:\Python311\python.exe -m PyInstaller RaceCraft.spec

# Or use virtual environment with specific version
py -3.11 -m venv venv311
.\venv311\Scripts\Activate.ps1
pip install -r requirements.txt
pyinstaller RaceCraft.spec
```

## Troubleshooting

### "Module not found" errors

Add to `RaceCraft.spec` hidden imports:
```python
hiddenimports=[
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'qasync',
    'keyring.backends.Windows',
    # Add other missing modules here
],
```

### Large file size

Exclude unused modules:
```python
excludes=[
    'tkinter',
    'unittest',
    'email',
    'http.server',
    'matplotlib',  # If not used
    'numpy',       # If not used
],
```

### Antivirus false positives

- Code sign the executable
- Submit to antivirus vendors (VirusTotal, etc.)
- Use reputable packaging tools
- Avoid obfuscation

### "Application failed to start"

- Check Python version compatibility
- Ensure all dependencies in requirements.txt
- Test on clean Windows VM
- Check Windows Event Viewer for errors

## Automated Build (CI/CD)

### GitHub Actions Example

Create `.github/workflows/build.yml`:

```yaml
name: Build Windows Executable

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: windows-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pyinstaller

    - name: Build executable
      run: pyinstaller RaceCraft.spec

    - name: Upload artifact
      uses: actions/upload-artifact@v3
      with:
        name: RaceCraft-Windows
        path: dist/RaceCraft.exe
```

## Distribution Checklist

Before releasing:

- [ ] Test on clean Windows 10/11 VM
- [ ] Test with and without internet connection
- [ ] Verify system tray functionality
- [ ] Test authentication flow
- [ ] Check file size is reasonable
- [ ] Code sign executable (if possible)
- [ ] Create README.txt with installation instructions
- [ ] Test uninstaller (for MSI/Inno Setup)
- [ ] Scan with VirusTotal
- [ ] Create GitHub release with binaries

## Recommended Workflow

**For development/testing**:
1. Run directly: `python -m racecraft.app`

**For alpha/beta releases**:
1. Build with PyInstaller: `.\build.ps1 -Target exe`
2. Distribute ZIP file

**For public v1.0 release**:
1. Get code signing certificate
2. Build with PyInstaller
3. Sign executable
4. Create Inno Setup installer
5. Upload to GitHub Releases

**For enterprise deployment**:
1. Build MSI with cx_Freeze
2. Sign MSI
3. Deploy via Group Policy or SCCM
