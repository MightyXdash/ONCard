from pathlib import Path
import os
import sys
import traceback


def _write_startup_log(message: str) -> None:
    local_appdata = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    log_dir = local_appdata / "ONCards" / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "startup_error.log"
    log_path.write_text(message, encoding="utf-8")


def main() -> int:
    root = Path(__file__).resolve().parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    try:
        from studymate.app import run_app  # noqa: E402
    except ModuleNotFoundError as exc:
        missing = exc.name or "dependency"
        print(f"Startup failed: missing Python package '{missing}'.")
        print("Install dependencies with: pip install -r requirements.txt")
        _write_startup_log(f"Startup failed: missing Python package '{missing}'.\n")
        return 1
    except Exception:
        print("Startup failed while importing app modules.")
        _write_startup_log("Startup failed while importing app modules.\n" + traceback.format_exc())
        traceback.print_exc()
        return 1

    try:
        return run_app()
    except Exception:
        print("ONCards encountered an unexpected error.")
        _write_startup_log("ONCards encountered an unexpected error.\n" + traceback.format_exc())
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
