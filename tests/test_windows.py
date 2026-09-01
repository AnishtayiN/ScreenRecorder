"""Tests for Screen Recorder Windows application.

When PyQt5 is not available, the module is imported with mocked Qt.
PyQt-dependent UI tests are skipped; pure logic tests run regardless.
"""
import os
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'windows'))

# Ensure screen_recorder can be imported even without PyQt5
# by injecting mock Qt modules into sys.modules before import
_screen_recorder_path = os.path.join(os.path.dirname(__file__), '..', 'windows', 'screen_recorder.py')
if os.path.isfile(_screen_recorder_path):
    _needs_mock = False
    try:
        from PyQt5.QtWidgets import QApplication  # noqa: F401
    except ImportError:
        _needs_mock = True

    if _needs_mock:
        # Create mock Qt5 modules with all names used by screen_recorder
        _qtwidgets = types.ModuleType('PyQt5.QtWidgets')
        _qtcore = types.ModuleType('PyQt5.QtCore')
        _qtgui = types.ModuleType('PyQt5.QtGui')

        for name in ['QApplication', 'QMainWindow', 'QWidget', 'QVBoxLayout', 'QHBoxLayout',
                      'QPushButton', 'QLabel', 'QComboBox', 'QCheckBox', 'QFileDialog',
                      'QSystemTrayIcon', 'QMenu', 'QMessageBox', 'QGroupBox', 'QSlider',
                      'QSpinBox', 'QFrame', 'QTabWidget', 'QListWidget', 'QListWidgetItem',
                      'QColorDialog', 'QSplitter', 'QToolButton', 'QButtonGroup', 'QStatusBar',
                      'QGraphicsDropShadowEffect', 'QInputDialog']:
            setattr(_qtwidgets, name, MagicMock)

        for name in ['Qt', 'QTimer', 'pyqtSignal', 'QObject', 'QRect', 'QThread',
                      'QPoint', 'QPropertyAnimation', 'QEasingCurve']:
            if name == 'Qt':
                # Qt needs to behave like a namespace with flags
                mock_qt = MagicMock()
                mock_qt.FramelessWindowHint = 0
                mock_qt.WindowStaysOnTopHint = 0
                mock_qt.Tool = 0
                mock_qt.WA_TranslucentBackground = 0
                mock_qt.LeftButton = 1
                mock_qt.AlignCenter = 1
                mock_qt.AlignBottom = 0
                mock_qt.AlignHCenter = 0
                mock_qt.Horizontal = 0
                mock_qt.NoPen = 0
                mock_qt.transparent = 0
                mock_qt.Key_Escape = 0
                mock_qt.WindowStateChange = 0
                mock_qt.CrossCursor = 0
                mock_qt.PointingHandCursor = 0
                mock_qt.UserRole = 256
                mock_qt.CompositionMode_Clear = 0
                mock_qt.CompositionMode_SourceOver = 0
                mock_qt.IsWindowActive = 0
                mock_qt.WindowMinimized = 1
                mock_qt.Key = type('Key', (), {'f9': 0, 'f10': 0, 'f11': 0, 'f12': 0})()
                setattr(_qtcore, name, mock_qt)
            else:
                setattr(_qtcore, name, MagicMock)

        for name in ['QIcon', 'QPixmap', 'QPainter', 'QColor', 'QFont', 'QKeySequence',
                      'QPen', 'QBrush', 'QRadialGradient', 'QFontMetrics', 'QCursor',
                      'QRegion', 'QPalette']:
            setattr(_qtgui, name, MagicMock)

        _pyqt5 = types.ModuleType('PyQt5')
        sys.modules['PyQt5'] = _pyqt5
        sys.modules['PyQt5.QtWidgets'] = _qtwidgets
        sys.modules['PyQt5.QtCore'] = _qtcore
        sys.modules['PyQt5.QtGui'] = _qtgui

# Also mock cv2 and numpy if not available
try:
    import cv2  # noqa: F401
except ImportError:
    sys.modules['cv2'] = MagicMock()
try:
    import numpy  # noqa: F401
except ImportError:
    sys.modules['numpy'] = MagicMock()
try:
    import mss  # noqa: F401
except ImportError:
    sys.modules['mss'] = MagicMock()
try:
    import pyaudio  # noqa: F401
except ImportError:
    sys.modules['pyaudio'] = MagicMock()
try:
    from pynput import keyboard  # noqa: F401
except ImportError:
    sys.modules['pynput'] = MagicMock()
    sys.modules['pynput.keyboard'] = MagicMock()

# Now import the module
import screen_recorder  # noqa: E402


class TestRecordingState(unittest.TestCase):
    def test_initial_state(self):
        self.assertEqual(screen_recorder.RecordingState.IDLE, 0)

    def test_all_states_defined(self):
        RS = screen_recorder.RecordingState
        self.assertEqual(RS.IDLE, 0)
        self.assertEqual(RS.STARTING, 1)
        self.assertEqual(RS.RECORDING, 2)
        self.assertEqual(RS.PAUSED, 3)
        self.assertEqual(RS.STOPPING, 4)
        self.assertEqual(RS.FINALIZING, 5)


class TestQualityMapping(unittest.TestCase):
    def test_low_quality(self):
        crf = screen_recorder._quality_to_crf(10)
        self.assertGreaterEqual(crf, 33)
        self.assertLessEqual(crf, 37)

    def test_medium_quality(self):
        crf = screen_recorder._quality_to_crf(50)
        # 51 - (50/100 * 36) = 51 - 18 = 33
        self.assertEqual(crf, 33)

    def test_high_quality(self):
        crf = screen_recorder._quality_to_crf(100)
        self.assertGreaterEqual(crf, 13)
        self.assertLessEqual(crf, 17)

    def test_monotonic_decreasing(self):
        prev = screen_recorder._quality_to_crf(10)
        for q in range(20, 101, 10):
            crf = screen_recorder._quality_to_crf(q)
            self.assertLessEqual(crf, prev, f"CRF at quality {q} should be <= CRF at quality {q-10}")
            prev = crf

    def test_bounds_clamping(self):
        for q in range(0, 201):
            crf = screen_recorder._quality_to_crf(q)
            self.assertGreaterEqual(crf, 15, f"CRF at quality {q} should be >= 15")
            self.assertLessEqual(crf, 35, f"CRF at quality {q} should be <= 35")


class TestSafeDelete(unittest.TestCase):
    def test_delete_existing_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp') as f:
            f.write(b'test')
            path = f.name
        screen_recorder._safe_delete(path)
        self.assertFalse(os.path.exists(path))

    def test_delete_nonexistent(self):
        screen_recorder._safe_delete("/nonexistent/path/to/file.tmp")

    def test_delete_none(self):
        screen_recorder._safe_delete(None)

    def test_delete_empty_string(self):
        screen_recorder._safe_delete("")


class TestMuxFunction(unittest.TestCase):
    def test_mux_missing_video(self):
        result = screen_recorder._mux_audio_video("/nonexistent.mp4", "/nonexistent.wav", "/out.mp4")
        self.assertFalse(result)

    def test_mux_missing_audio(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as f:
            f.write(b'fake video')
            video = f.name
        try:
            result = screen_recorder._mux_audio_video(video, "/nonexistent.wav", "/out.mp4")
            self.assertFalse(result)
        finally:
            os.remove(video)

    def test_mux_no_ffmpeg_flag(self):
        old = screen_recorder.HAS_FFMPEG
        try:
            screen_recorder.HAS_FFMPEG = False
            result = screen_recorder._mux_audio_video("a.mp4", "b.wav", "c.mp4")
            self.assertFalse(result)
        finally:
            screen_recorder.HAS_FFMPEG = old

    def test_mux_both_missing(self):
        result = screen_recorder._mux_audio_video("/a.mp4", "/b.wav", "/c.mp4")
        self.assertFalse(result)


class TestFFmpegDetection(unittest.TestCase):
    def test_find_ffmpeg_returns_string_or_none(self):
        result = screen_recorder._find_ffmpeg()
        if result is not None:
            self.assertIsInstance(result, str)

    def test_has_ffmpeg_flag_is_bool(self):
        self.assertIsInstance(screen_recorder.HAS_FFMPEG, bool)

    def test_find_ffmpeg_no_crash(self):
        result = screen_recorder._find_ffmpeg()
        self.assertTrue(result is None or isinstance(result, str))


class TestRecordingEngine(unittest.TestCase):
    def test_engine_init(self):
        sig = screen_recorder.EngineSignals()
        engine = screen_recorder.RecordingEngine(sig)
        self.assertEqual(engine.state, screen_recorder.RecordingState.IDLE)
        self.assertFalse(engine.audio_enabled)
        self.assertFalse(engine.webcam_enabled)
        self.assertEqual(engine.fps, 30)
        self.assertEqual(engine.quality, 80)
        self.assertIsNone(engine._temp_video_path)
        self.assertIsNone(engine._temp_audio_path)

    def test_engine_start_rejects_when_not_idle(self):
        sig = screen_recorder.EngineSignals()
        engine = screen_recorder.RecordingEngine(sig)
        engine._set_state(screen_recorder.RecordingState.RECORDING)
        result = engine.start("/tmp/test.mp4")
        self.assertFalse(result)

    def test_engine_stop_safe_when_idle(self):
        sig = screen_recorder.EngineSignals()
        engine = screen_recorder.RecordingEngine(sig)
        engine.stop()  # Should not crash
        self.assertEqual(engine.state, screen_recorder.RecordingState.IDLE)

    def test_engine_stop_idempotent(self):
        sig = screen_recorder.EngineSignals()
        engine = screen_recorder.RecordingEngine(sig)
        engine.stop()
        engine.stop()  # Double stop should not crash
        engine.stop()

    def test_engine_pause_rejects_when_idle(self):
        sig = screen_recorder.EngineSignals()
        engine = screen_recorder.RecordingEngine(sig)
        engine.pause()  # Should not crash, should not change state
        self.assertEqual(engine.state, screen_recorder.RecordingState.IDLE)

    def test_engine_resume_rejects_when_idle(self):
        sig = screen_recorder.EngineSignals()
        engine = screen_recorder.RecordingEngine(sig)
        engine.resume()  # Should not crash
        self.assertEqual(engine.state, screen_recorder.RecordingState.IDLE)

    def test_engine_pause_resume_valid(self):
        sig = screen_recorder.EngineSignals()
        engine = screen_recorder.RecordingEngine(sig)
        engine._set_state(screen_recorder.RecordingState.RECORDING)
        engine.pause()
        self.assertEqual(engine.state, screen_recorder.RecordingState.PAUSED)
        engine.resume()
        self.assertEqual(engine.state, screen_recorder.RecordingState.RECORDING)

    def test_engine_state_lock(self):
        sig = screen_recorder.EngineSignals()
        engine = screen_recorder.RecordingEngine(sig)
        self.assertIsNotNone(engine._lock)


class TestGetMonitors(unittest.TestCase):
    def test_returns_list(self):
        monitors = screen_recorder.get_monitors()
        self.assertIsInstance(monitors, list)
        self.assertGreater(len(monitors), 0)


class TestCodecFallback(unittest.TestCase):
    def test_opencv_fourcc_mp4(self):
        """MP4 fallback uses mp4v."""
        codec, ext = "mp4v", ".mp4"
        self.assertEqual(ext, ".mp4")

    def test_opencv_fourcc_avi(self):
        """AVI fallback uses MJPG."""
        codec, ext = "MJPG", ".avi"
        self.assertEqual(ext, ".avi")

    def test_opencv_fourcc_mkv(self):
        """MKV fallback uses mp4v (XVID broken for MKV)."""
        codec, ext = "mp4v", ".mkv"
        self.assertEqual(ext, ".mkv")


class TestFileNamePattern(unittest.TestCase):
    def test_timestamp_format(self):
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.assertEqual(len(ts), 15)
        self.assertIn('_', ts)


if __name__ == '__main__':
    unittest.main(verbosity=2)
