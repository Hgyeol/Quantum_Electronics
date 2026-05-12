import plistlib
import unittest
from pathlib import Path

from scripts.render_signal_learning_launchd_plist import build_launchd_plist, render_plist


class RenderSignalLearningLaunchdPlistTests(unittest.TestCase):
    def test_builds_daily_collection_plist(self):
        plist = build_launchd_plist(
            repo_dir=Path("/repo"),
            python_executable="/repo/.venv/bin/python",
            hour=16,
            minute=10,
            stock_limit=5,
        )

        self.assertEqual(plist["Label"], "com.quantum-electronics.signal-learning-daily")
        self.assertEqual(plist["WorkingDirectory"], "/repo")
        self.assertEqual(plist["StartCalendarInterval"], {"Hour": 16, "Minute": 10})
        self.assertEqual(
            plist["ProgramArguments"],
            [
                "/repo/.venv/bin/python",
                "/repo/scripts/collect_daily_signal_learning_inputs.py",
                "--kis-auth",
                "--stock-limit",
                "5",
                "--run-workflow-if-ready",
            ],
        )
        self.assertEqual(plist["StandardOutPath"], "/repo/runtime/signal_learning_daily.out.log")
        self.assertEqual(plist["StandardErrorPath"], "/repo/runtime/signal_learning_daily.err.log")

    def test_can_force_kis_token_refresh(self):
        plist = build_launchd_plist(
            repo_dir=Path("/repo"),
            python_executable="/repo/.venv/bin/python",
            force_kis_token=True,
        )

        self.assertIn("--force-kis-token", plist["ProgramArguments"])

    def test_renders_valid_plist_bytes(self):
        rendered = render_plist(
            build_launchd_plist(
                repo_dir=Path("/repo"),
                python_executable="/repo/.venv/bin/python",
            )
        )

        parsed = plistlib.loads(rendered)
        self.assertEqual(parsed["Label"], "com.quantum-electronics.signal-learning-daily")


if __name__ == "__main__":
    unittest.main()
