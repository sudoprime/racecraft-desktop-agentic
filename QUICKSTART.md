# RaceCraft Desktop - Quick Start Guide

## Test mode (no sim required)

The app can generate simulated telemetry and stream it through the real
upload path (OAuth PKCE login → `/api/streaming` session → gzipped chunks →
AI analysis) without any simulator installed. This is how the automated E2E
environment exercises the full platform.

```bash
# Headless: one simulated session, then exit (works on Linux/Windows, no UI)
python -m racecraft.headless \
    --api-url http://<racecraft-host>:30080 \
    --email dev@racecraft.local --password 'DevPassword123!' \
    --laps 4 --time-scale 10 --wait

# GUI test mode: tray app runs, but with a simulated game instead of a real sim
python -m racecraft.app --test --api-url http://<racecraft-host>:30080 \
    --email dev@racecraft.local --password 'DevPassword123!'
```

All flags have env-var equivalents for unattended setups: `RACECRAFT_API_URL`,
`RACECRAFT_EMAIL`, `RACECRAFT_PASSWORD`, `RACECRAFT_TEST_LAPS`,
`RACECRAFT_TEST_TIMESCALE`.

- `--time-scale N` emits frames N× faster than real time while keeping
  data timestamps honest (a 6-minute session generates in ~36s at 10×).
- Auth: with `--email/--password` the app signs in via SuperTokens and then
  drives the real PKCE desktop-token flow server-side
  (`/api/auth/desktop/authorize` → `/api/auth/desktop/token`). Without
  credentials, the GUI opens the system browser (production flow).
- The simulated profile is the platform's standard 8-corner synthetic lap
  (same family as `deploy/helm/racecraft/files/generate_mock_chunks.py` in
  the platform repo), driven through an accel/brake controller so braking
  points and corner exits look like real driving to the coaching pipeline.

## For Developers

### 1. Setup Environment (First Time Only)

```powershell
# Clone the repository (if not already done)
cd C:\Users\bryan\Documents\GitHub\racecraft-desktop

# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# If you get an error about execution policy:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
# Then try activating again

# Install dependencies
pip install -r requirements.txt
```

### 2. Run the Application

```powershell
# Make sure venv is activated (you should see (venv) in your prompt)
python -m racecraft.app
```

### 3. Development Workflow

```powershell
# Always activate venv first
.\venv\Scripts\Activate.ps1

# Run the app
python -m racecraft.app

# Install new packages
pip install package-name
pip freeze > requirements.txt  # Update requirements

# Run tests (when available)
pytest

# Format code
black racecraft/

# Deactivate venv when done
deactivate
```

## For End Users

### Download and Install

**Option 1: Standalone Executable** (Easiest)
1. Download `RaceCraft.exe` from releases
2. Double-click to run
3. Windows may show SmartScreen warning - click "More info" → "Run anyway"

**Option 2: MSI Installer** (Recommended)
1. Download `RaceCraft-Setup-0.1.0.exe` or `.msi`
2. Run installer
3. Follow wizard
4. Launch from Start Menu

**Option 3: From Source** (Advanced)
1. Install Python 3.11+
2. Download/clone repository
3. Follow developer setup above

### First Launch

1. RaceCraft will minimize to system tray (look for icon near clock)
2. Right-click tray icon → "Show RaceCraft"
3. Authentication window will appear
4. Follow authentication prompts (TODO: actual auth flow)
5. Once authenticated, app runs in background

### Usage

- **Show window**: Click tray icon or right-click → "Show RaceCraft"
- **Exit**: Right-click tray icon → "Exit"
- **Minimize**: Close window (doesn't exit, just hides to tray)

## Building Executables

### Quick Build

```powershell
# Build standalone EXE
.\build.ps1

# Build everything (EXE, MSI, Installer)
.\build.ps1 -Target all
```

See [BUILDING.md](BUILDING.md) for detailed instructions.

## Project Structure

```
racecraft-desktop/
├── racecraft/           # Main application code
│   ├── ui/             # PyQt6 UI components
│   │   ├── main_window.py  # Main window
│   │   └── tray.py         # System tray icon
│   ├── app.py          # Application entry point
│   ├── auth.py         # Authentication service
│   └── models.py       # Data models
├── assets/             # Icons and resources
├── config/             # Configuration files
├── tests/              # Unit tests
├── installer/          # Installer scripts
├── requirements.txt    # Python dependencies
└── RaceCraft.spec     # PyInstaller build config
```

## Common Issues

### "Module not found" when running

```powershell
# Make sure you're in the virtual environment
.\venv\Scripts\Activate.ps1

# Reinstall dependencies
pip install -r requirements.txt
```

### "Python not found"

Install Python 3.11+ from https://www.python.org/downloads/

Make sure to check "Add Python to PATH" during installation.

### PowerShell won't run scripts

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### App crashes on startup

Check logs (TODO: implement logging)

### Tray icon doesn't appear

- Check if icon.png exists in assets/
- Windows may hide tray icons - click "^" near system clock

## Next Steps

- Read [CLAUDE.md](CLAUDE.md) for full architecture documentation
- Read [BUILDING.md](BUILDING.md) for packaging details
- Check [README.md](README.md) for project overview

## Getting Help

- GitHub Issues: [Report bugs](https://github.com/yourusername/racecraft-desktop/issues)
- Documentation: See CLAUDE.md for detailed technical docs
- Discord: (TODO: create Discord server)

## Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/my-feature`
3. Make changes
4. Test thoroughly
5. Commit: `git commit -am 'Add my feature'`
6. Push: `git push origin feature/my-feature`
7. Create Pull Request
