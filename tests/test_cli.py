from __future__ import annotations

import contextlib
import io
import unittest

from goal_cli.cli import main


class CliTests(unittest.TestCase):
    def test_run_help_has_no_multi_cycle_flag(self) -> None:
        output = io.StringIO()

        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(output):
            main(["run", "--help"])

        self.assertEqual(raised.exception.code, 0)
        help_text = output.getvalue()
        self.assertNotIn("--max-cycles", help_text)
        self.assertIn("Maximum wall-clock minutes for this heartbeat", help_text)

    def test_top_level_help_has_no_cycle_alias(self) -> None:
        output = io.StringIO()

        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(output):
            main(["--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertNotIn("cycle", output.getvalue())

    def test_doctor_help_exposes_separate_smoke_timeout(self) -> None:
        output = io.StringIO()

        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(output):
            main(["doctor", "--help"])

        self.assertEqual(raised.exception.code, 0)
        help_text = output.getvalue()
        self.assertIn("--timeout-seconds", help_text)
        self.assertIn("--smoke-timeout-seconds", help_text)
        self.assertIn("except the optional Codex", help_text)
        self.assertIn("smoke check", help_text)


if __name__ == "__main__":
    unittest.main()
