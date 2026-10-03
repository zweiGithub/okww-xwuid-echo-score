"""Distribution checks require only Python's standard library."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "tools" / "package_echo_score.py"
CACHE_DIRECTORIES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "diagnostics"}


def expected_files(source):
    """Independent file list, so the test cannot share a builder omission."""
    return {
        "echo-score/" + path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
        and not CACHE_DIRECTORIES.intersection(path.relative_to(source).parts)
        and path.suffix.lower() not in {".pyc", ".pyo"}
        and path.name != ".DS_Store"
    }


class PackageBuilderTests(unittest.TestCase):
    def build(self, source, target):
        self.assertTrue(PACKAGER.is_file(), "The deterministic ZIP builder is missing")
        result = subprocess.run(
            [sys.executable, str(PACKAGER), "--source", str(source), "--output", str(target)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_archive_matches(self, archive, expected):
        with zipfile.ZipFile(archive) as package:
            self.assertIsNone(package.testzip())
            self.assertEqual(package.namelist(), sorted(expected))
            for name, contents in expected.items():
                self.assertEqual(package.read(name), contents, name)

    def test_builder_preserves_file_bytes_and_excludes_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "manifest.json").write_bytes(b'{"version": "0.4.0"}\n')
            (source / "nested").mkdir()
            (source / "nested" / "data.bin").write_bytes(bytes(range(256)))
            for cache in sorted(CACHE_DIRECTORIES):
                (source / cache).mkdir()
                (source / cache / "cached").write_bytes(b"do not distribute")
            for name in ("module.pyc", "module.pyo", ".DS_Store"):
                (source / name).write_bytes(b"do not distribute")
            (source / "nested" / "__pycache__").mkdir()
            (source / "nested" / "__pycache__" / "cached.pyc").write_bytes(b"cache")
            archive = root / "package.zip"
            self.build(source, archive)
            self.assert_archive_matches(archive, {
                "echo-score/manifest.json": b'{"version": "0.4.0"}\n',
                "echo-score/nested/data.bin": bytes(range(256)),
            })

    def test_builder_is_deterministic_when_source_metadata_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            for name in ("z.py", "a.py"):
                (source / name).write_bytes(b"# stable bytes\n")
            first = root / "first.zip"
            second = root / "second.zip"
            self.build(source, first)
            for path in source.iterdir():
                os.utime(path, (1700000000, 1700000000))
                path.chmod(0o600)
            self.build(source, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_builder_packages_current_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "echo-score.zip"
            source = ROOT / "echo-score"
            self.build(source, archive)
            self.assert_archive_matches(archive, expected_files(source))


class DistributionArchiveTests(unittest.TestCase):
    def test_package_retains_license_and_project_attributions(self):
        self.assertTrue((ROOT / 'echo-score' / 'LICENSE').exists())
        self.assertEqual((ROOT / 'echo-score' / 'LICENSE').read_bytes(), (ROOT / 'LICENSE').read_bytes())
        readme=(ROOT / 'echo-score' / 'README.md').read_text()
        self.assertIn('https://github.com/ok-oldking/ok-wuthering-waves',readme)
        self.assertIn('https://github.com/Loping151/XutheringWavesUID',readme)


    def test_distributed_archive_matches_current_source_bytes(self):
        expected = expected_files(ROOT / "echo-score")
        with zipfile.ZipFile(ROOT / "echo-score.zip") as archive:
            self.assertIsNone(archive.testzip())
            files = [name for name in archive.namelist() if not name.endswith("/")]
            self.assertEqual(sorted(files), sorted(expected),
                             "Run python tools/package_echo_score.py after source changes")
            for name, contents in expected.items():
                self.assertEqual(archive.read(name), contents,
                                 f"Stale distribution file: {name}")


if __name__ == "__main__":
    unittest.main()
