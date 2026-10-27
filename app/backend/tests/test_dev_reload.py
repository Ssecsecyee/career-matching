import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("dev_runner", Path(__file__).resolve().parents[1] / "dev.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ReloadWatchTests(unittest.TestCase):
    def test_env_and_python_changes_are_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "src").mkdir()
            (root / "src/a.py").write_text("a=1", encoding="utf-8")
            (root / ".env").write_text("TEST_VALUE=one", encoding="utf-8")
            before = runner.signature(root)
            (root / ".env").write_text("TEST_VALUE=two-longer", encoding="utf-8")
            self.assertNotEqual(before, runner.signature(root))
            before = runner.signature(root)
            (root / "src/b.py").write_text("b=2", encoding="utf-8")
            self.assertNotEqual(before, runner.signature(root))

    def test_data_tests_and_pycache_are_not_watched(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before = runner.signature(root)
            for name in ("local-data/jobs.json", "tests/test_example.py", "src/__pycache__/cache.pyc"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ignored", encoding="utf-8")
            self.assertEqual(before, runner.signature(root))
