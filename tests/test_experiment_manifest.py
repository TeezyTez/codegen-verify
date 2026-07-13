import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from experiment_manifest import write_manifest


class ExperimentManifestTests(unittest.TestCase):
    def test_manifest_writer_uses_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            write_manifest(path, {"mode": "strict", "secret": False})
            text = path.read_text(encoding="utf-8")
            self.assertIn('"mode": "strict"', text)


if __name__ == "__main__":
    unittest.main()
