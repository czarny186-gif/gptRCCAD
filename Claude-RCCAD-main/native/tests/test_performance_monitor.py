import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen' if not os.environ.get('DISPLAY') and os.name != 'nt' else '')
os.environ.setdefault('RCCAD_WORKERS', '0')

from PySide6.QtWidgets import QApplication, QFileDialog
from rccad.performance_monitor import FrameSamples
from rccad.studio import StudioWindow


class MonitorTests(unittest.TestCase):
    def test_frame_samples_age_and_report_cpu_cost(self):
        samples = FrameSamples()
        samples.record(9.00, 9.01)
        samples.record(9.50, 9.51)
        self.assertEqual(samples.report(10.2), {'fps_1s': 1, 'fps_mean': 2.0, 'frame_cpu_ms': 10.0})
        self.assertEqual(samples.report(11.0)['fps_1s'], 0)

    def test_monitor_only_samples_while_visible_and_exports_json(self):
        app = QApplication.instance() or QApplication([])
        window = StudioWindow()
        try:
            self.assertIsNone(window.view.frame_samples)
            window.show_performance()
            monitor = window._performance_monitor
            self.assertTrue(monitor.timer.isActive())
            self.assertIs(window.view.frame_samples, monitor.samples)
            with tempfile.TemporaryDirectory() as name:
                path = Path(name) / 'report.json'
                with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), 'JSON')):
                    monitor.save()
                self.assertIn('"foreground_jobs": 0', path.read_text(encoding='utf-8'))
            monitor.close()
            self.assertFalse(monitor.timer.isActive())
            self.assertIsNone(window.view.frame_samples)
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()
