import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app_state import AppState
from utils import generate_output_filename


class PhaseOneStateTests(unittest.TestCase):
    def test_file_selection_reaches_every_subscriber(self):
        state = AppState()
        received = [[], [], [], []]
        for sink in received:
            state.subscribe(sink.append)

        selected = "/tmp/example.pdf"
        state.select_file(selected)

        self.assertTrue(all(values == [None, selected] for values in received))

    def test_filename_keeps_requested_extension(self):
        filename = generate_output_filename("/tmp/report.pdf", "to_excel", ".xlsx")
        self.assertTrue(filename.startswith("report_to_excel_"))
        self.assertTrue(filename.endswith(".xlsx"))

    def test_filename_accepts_extension_without_dot(self):
        filename = generate_output_filename("/tmp/report.pdf", "edited", "pdf")
        self.assertTrue(filename.endswith(".pdf"))


if __name__ == "__main__":
    unittest.main()
