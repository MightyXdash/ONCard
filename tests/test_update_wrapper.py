from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from studymate.services.update_service import UpdateService  # noqa: E402
from studymate.utils.paths import AppPaths  # noqa: E402


def _load_update_wrapper():
    module_path = ROOT / "packaging" / "update_wrapper.py"
    spec = importlib.util.spec_from_file_location("local_update_wrapper", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load update wrapper module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


update_wrapper = _load_update_wrapper()


class UpdateWrapperTests(unittest.TestCase):
    def test_find_inner_installer_prefers_named_installer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            (bundle / "aaa-helper.exe").write_bytes(b"x")
            expected = bundle / "ONCard-Installer-1.1.6.exe"
            expected.write_bytes(b"x")

            original = update_wrapper._bundle_dir
            update_wrapper._bundle_dir = lambda: bundle
            try:
                self.assertEqual(expected, update_wrapper._find_inner_installer())
            finally:
                update_wrapper._bundle_dir = original


class UpdateLauncherScriptTests(unittest.TestCase):
    def test_silent_launcher_contains_silent_flags_and_update_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = AppPaths(root)
            paths.ensure()
            service = UpdateService(paths)
            installer = paths.updates / "ONCard-Setup-1.1.6.exe"
            installer.write_bytes(b"x")

            launcher = service.create_post_exit_launcher(installer, 1234, silent=True)
            script = launcher.read_text(encoding="utf-8")

            self.assertIn("/VERYSILENT", script)
            self.assertIn("/SUPPRESSMSGBOXES", script)
            self.assertIn("/NORESTART", script)
            self.assertIn("/SILENTPATCH", script)
            self.assertIn("/UPDATEFLOW", script)


if __name__ == "__main__":
    unittest.main()
