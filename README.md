# ONCards (PySide6 + Nuitka)

Local-first desktop flashcard app with onboarding, Ollama model setup, AI autofill, and random study mode.

<img width="512" height="512" alt="ONCards logo" src="https://github.com/user-attachments/assets/cd88364e-904a-41d1-87ff-0444d2cd70a7" />

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
