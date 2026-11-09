"""Unit tests for U306 Mobile HUD status generator and exporter."""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.mobile_hud import (
    _fuel_color,
    _progress_bar,
    build_mobile_status,
    export_mobile_status,
)


class TestMobileHUD(unittest.TestCase):
    def test_fuel_color_and_bar(self):
        self.assertEqual(_fuel_color(85), "#10b981")
        self.assertEqual(_fuel_color(40), "#f59e0b")
        self.assertEqual(_fuel_color(10), "#ef4444")
        self.assertEqual(_fuel_color(None), "#888888")

        bar = _progress_bar(50, length=10)
        self.assertEqual(bar, "█████░░░░░")

    def test_build_and_export_mobile_status(self):
        root = Path(".")
        status = build_mobile_status(root)
        self.assertTrue(status.get("ok"))
        self.assertIn("tools", status)
        for t in ("codex", "claude", "antigravity", "haiku", "ollama"):
            self.assertIn(t, status["tools"])
            tool_data = status["tools"][t]
            self.assertIn("presence", tool_data)
            self.assertIn("tier", tool_data)
            self.assertIn("fuel_color", tool_data)
            self.assertIn("progress_bar", tool_data)

        self.assertIn("active_phase", status)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "test_status.json"
            exported = export_mobile_status(root, out_file)
            self.assertTrue(exported.is_file())
            content = json.loads(exported.read_text(encoding="utf-8"))
            self.assertTrue(content["ok"])
            self.assertEqual(content["tools"]["codex"]["name"], "Codex")


if __name__ == "__main__":
    unittest.main()
