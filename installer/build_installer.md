# Building Windows Installer for RaceCraft Desktop

## Option 1: cx_Freeze MSI (Easiest)

```bash
pip install cx_freeze
python setup_cx_freeze.py bdist_msi
```

Output: `dist/RaceCraft-0.1.0-win64.msi`

## Option 2: Inno Setup (Recommended for Distribution)

1. **Build executable first**:
   ```bash
   pip install pyinstaller
   pyinstaller RaceCraft.spec
   ```

2. **Download Inno Setup**: https://jrsoftware.org/isdl.php

3. **Create installer script** (`installer/setup.iss`)

4. **Compile with Inno Setup Compiler**

The Inno Setup script below creates a professional installer with:
- Start menu shortcuts
- Desktop shortcut option
- Uninstaller
- Auto-start option
- Registry entries

## Option 3: Advanced Installer (Commercial, Very Professional)

https://www.advancedinstaller.com/
- Free edition available
- GUI-based installer creation
- MSI output
- Code signing support
- Auto-update functionality

## Option 4: NSIS (Nullsoft Scriptable Install System)

Free, open-source, used by many popular apps.
More complex scripting than Inno Setup.

## Recommended Workflow

For initial development/testing:
- Use PyInstaller to create standalone EXE
- Distribute the EXE directly or in a ZIP

For public release:
- PyInstaller EXE + Inno Setup installer
- Code signing certificate ($100-300/year from DigiCert/Sectigo)
- Auto-update mechanism (PyUpdater or custom)

## Code Signing

Windows SmartScreen will warn about unsigned executables.
Get a code signing certificate from:
- DigiCert
- Sectigo (formerly Comodo)
- GlobalSign

Sign with signtool.exe:
```bash
signtool sign /f certificate.pfx /p password /tr http://timestamp.digicert.com RaceCraft.exe
```
