from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packaging.version import Version  # noqa: E402

from studymate.constants import APP_NAME  # noqa: E402
from studymate.version import APP_PUBLISHER, APP_VERSION  # noqa: E402


def main() -> int:
    arg = (sys.argv[1] if len(sys.argv) > 1 else "version").lower()
    if arg == "version":
        print(APP_VERSION)
    elif arg == "publisher":
        print(APP_PUBLISHER)
    elif arg == "appname":
        print(APP_NAME)
    elif arg == "fileversion":
        version = Version(APP_VERSION)
        parts = [version.major, version.minor, version.micro]
        build = version.pre[1] if version.pre else version.post if version.post is not None else 0
        parts.append(int(build or 0))
        print(".".join(str(part) for part in parts))
    else:
        raise SystemExit(f"Unsupported field: {arg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
