# ONCards (PySide6 + Nuitka)

Local-first desktop flashcard app with onboarding, Ollama model setup, AI autofill, and random study mode.

## Quick Start
1. Install Python 3.11+.
2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
3. Run the app:
   ```powershell
   python main.py
   ```

## Windows Packaging
Build the Windows app and installer with:
```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build_windows.ps1
```

This produces:
- a Nuitka standalone build in `build/nuitka/`
- an Inno Setup installer in `build/installer/`

## Where To Put Icons and Banners
- Icons list: `assets/icons/ICON_MANIFEST.txt`
- Banner list: `assets/banners/BANNER_MANIFEST.txt`

Drop your PNG files into the listed folders using the exact filenames.

## Data Storage
- Dev mode uses the repo-local `data/` folder.
- Packaged Windows builds use:
  - `%AppData%\ONCards` for config/cards/history/backups
  - `%LocalAppData%\ONCards` for updater/runtime temp files

## Notes
- On first launch, onboarding setup is required.
- Model installer uses Ollama CLI (`ollama pull ...`).
- Grading uses streamed feedback for display and structured JSON for saved results.
- Startup checks GitHub Releases for a newer ONCards installer.
