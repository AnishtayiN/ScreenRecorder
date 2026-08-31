"""
Screen Recorder - Windows Desktop Application
A modern screen recorder with PyQt5 GUI
Supports Windows 7 through Windows 11
"""

import sys
import os
import time
import threading
import datetime
import json
from pathlib import Path

try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QComboBox, QCheckBox, QFileDialog,
        QSystemTrayIcon, QMenu, QAction, QMessageBox, QProgressBar,
        QGroupBox, QSlider, QSpinBox, QFrame, QShortcut, QSizePolicy
    )
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize, QSettings
    from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QKeySequence, QPen
    PYQT5 = True
except ImportError:
    PYQT5 = False

try:
    import mss
    import mss.tools
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

try:
    from pynput import keyboard as pynput_keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

APP_NAME = "Screen Recorder"
APP_VERSION = "1.0.0"
DEFAULT_FPS = 30
DEFAULT_QUALITY = 80
DEFAULT_OUTPUT_DIR = str(Path.home() / "Videos" / "ScreenRecorder")
CONFIG_FILE = str(Path.home() / ".screen_recorder_config.json")


class RecordingState:
    IDLE = 0
    RECORDING = 1
    PAUSED = 2


class RegionSelector(QWidget):
    """Overlay widget for selecting recording region"""
    region_selected = pyqtSignal(int, int, int, int)
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.start_pos = None
        self.end_pos = None
        self.is_selecting = False

    def start_selection(self):
        screen = QApplication.primaryScreen()
        geom = screen.geometry()
        self.setGeometry(geom)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Dark overlay
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        
        if self.start_pos and self.end_pos:
            region = self.get_region()
            # Clear selected area
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(region, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            
            # Draw border
            pen = QPen(QColor(0, 174, 255), 3, Qt.SolidLine)
            painter.setPen(pen)
            painter.drawRect(region)
            
            # Draw dimensions text
            text = f"{region.width()} x {region.height()}"
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
            text_rect = region.adjusted(0, -30, 0, 0)
            painter.drawText(text_rect, Qt.AlignBottom | Qt.AlignHCenter, text)

    def get_region(self):
        if not self.start_pos or not self.end_pos:
            return None
        x1 = min(self.start_pos.x(), self.end_pos.x())
        y1 = min(self.start_pos.y(), self.end_pos.y())
        x2 = max(self.start_pos.x(), self.end_pos.x())
        y2 = max(self.start_pos.y(), self.end_pos.y())
        from PyQt5.QtCore import QRect
        return QRect(x1, y1, x2 - x1, y2 - y1)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = event.pos()
            self.end_pos = event.pos()
            self.is_selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.end_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.is_selecting = False
            self.end_pos = event.pos()
            region = self.get_region()
            if region and region.width() > 10 and region.height() > 10:
                self.hide()
                self.region_selected.emit(region.x(), region.y(), region.width(), region.height())
            else:
                self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
            self.cancelled.emit()


class RecorderSignals(QObject):
    update_timer = pyqtSignal(str)
    update_progress = pyqtSignal(int)
    recording_finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)


class ScreenRecorderEngine:
    """Core screen recording engine"""
    
    def __init__(self, signals: RecorderSignals):
        self.signals = signals
        self.state = RecordingState.IDLE
        self.writer = None
        self.sct = None
        self.region = None
        self.fps = DEFAULT_FPS
        self.quality = DEFAULT_QUALITY
        self.codec = 'mp4v'
        self.output_path = ""
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread = None
        self.frame_count = 0
        self.start_time = 0
        self.audio_enabled = False

    def start(self, output_path, region=None, fps=30, quality=80, codec='mp4v'):
        if self.state != RecordingState.IDLE:
            return False
        
        self.output_path = output_path
        self.region = region
        self.fps = fps
        self.quality = quality
        self.codec = codec
        self.frame_count = 0
        self._stop_event.clear()
        self._pause_event.clear()
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self.state = RecordingState.IDLE
        self._stop_event.set()
        self._pause_event.set()

    def pause(self):
        if self.state == RecordingState.RECORDING:
            self.state = RecordingState.PAUSED
            self._pause_event.clear()

    def resume(self):
        if self.state == RecordingState.PAUSED:
            self.state = RecordingState.RECORDING
            self._pause_event.set()

    def _record_loop(self):
        try:
            if not MSS_AVAILABLE:
                self.signals.error_occurred.emit("mss library not available. Install it with: pip install mss")
                return
            if not OPENCV_AVAILABLE:
                self.signals.error_occurred.emit("opencv-python not available. Install it with: pip install opencv-python")
                return

            self.sct = mss.mss()
            
            if self.region:
                monitor = {
                    "left": self.region[0],
                    "top": self.region[1],
                    "width": self.region[2],
                    "height": self.region[3]
                }
            else:
                monitor = self.sct.monitors[1]  # Primary monitor

            width = monitor["width"]
            height = monitor["height"]

            fourcc = cv2.VideoWriter_fourcc(*self.codec)
            self.writer = cv2.VideoWriter(self.output_path, fourcc, self.fps, (width, height))

            if not self.writer.isOpened():
                self.signals.error_occurred.emit("Failed to create video file. Check codec settings.")
                return

            self.state = RecordingState.RECORDING
            self.start_time = time.time()
            self._pause_event.set()

            frame_interval = 1.0 / self.fps

            while not self._stop_event.is_set():
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                frame_start = time.time()
                
                try:
                    img = self.sct.grab(monitor)
                    frame = np.array(img)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    self.writer.write(frame)
                    self.frame_count += 1
                except Exception as e:
                    self.signals.error_occurred.emit(f"Frame capture error: {str(e)}")
                    break

                elapsed = time.time() - self.start_time
                h = int(elapsed // 3600)
                m = int((elapsed % 3600) // 60)
                s = int(elapsed % 60)
                self.signals.update_timer.emit(f"{h:02d}:{m:02d}:{s:02d}")

                frame_time = time.time() - frame_start
                sleep_time = max(0, frame_interval - frame_time)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except Exception as e:
            self.signals.error_occurred.emit(f"Recording error: {str(e)}")
        finally:
            if self.writer:
                self.writer.release()
                self.writer = None
            if self.sct:
                self.sct.close()
                self.sct = None
            
            if self.state != RecordingState.IDLE and self.output_path:
                self.signals.recording_finished.emit(self.output_path)
            self.state = RecordingState.IDLE


class ModernButton(QPushButton):
    """Styled modern button"""
    def __init__(self, text, color="#00aeff", parent=None):
        super().__init__(text, parent)
        self.setMinimumHeight(45)
        self.setMinimumWidth(120)
        self.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {color}dd;
            }}
            QPushButton:pressed {{
                background-color: {color}aa;
            }}
            QPushButton:disabled {{
                background-color: #555;
                color: #999;
            }}
        """)


class ScreenRecorderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(520, 620)
        self.setFixedSize(520, 620)
        
        self.signals = RecorderSignals()
        self.engine = ScreenRecorderEngine(self.signals)
        self.region_selector = RegionSelector()
        self.settings = QSettings("ScreenRecorder", "ScreenRecorder")
        
        self.selected_region = None
        self.selected_region_name = "Full Screen"
        self.hotkey_listener = None
        
        self._connect_signals()
        self._init_ui()
        self._init_tray()
        self._init_hotkeys()
        self._load_settings()
        
        self.center_window()

    def center_window(self):
        screen = QApplication.primaryScreen().geometry()
        size = self.geometry()
        self.move(
            (screen.width() - size.width()) // 2,
            (screen.height() - size.height()) // 2
        )

    def _connect_signals(self):
        self.signals.update_timer.connect(self._on_timer_update)
        self.signals.recording_finished.connect(self._on_recording_finished)
        self.signals.error_occurred.connect(self._on_error)
        self.region_selector.region_selected.connect(self._on_region_selected)
        self.region_selector.cancelled.connect(self._on_region_cancelled)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 15, 20, 15)

        # Title
        title = QLabel(f"🎬 {APP_NAME}")
        title.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #ffffff; margin-bottom: 5px;")
        layout.addWidget(title)

        version_label = QLabel(f"v{APP_VERSION} • Windows 7-11")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet("color: #888; font-size: 11px; margin-bottom: 10px;")
        layout.addWidget(version_label)

        # Timer display
        self.timer_label = QLabel("00:00:00")
        self.timer_label.setFont(QFont("Consolas", 32, QFont.Bold))
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setStyleSheet("color: #00aeff; background: #1a1a2e; border-radius: 12px; padding: 15px;")
        layout.addWidget(self.timer_label)

        # Status
        self.status_label = QLabel("● Ready")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(QFont("Segoe UI", 10))
        self.status_label.setStyleSheet("color: #4CAF50; margin: 5px;")
        layout.addWidget(self.status_label)

        # Settings group
        settings_group = QGroupBox("⚙ Settings")
        settings_group.setFont(QFont("Segoe UI", 10, QFont.Bold))
        settings_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #333;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                color: #ccc;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
            }
        """)
        settings_layout = QVBoxLayout(settings_group)

        # Region selection
        region_row = QHBoxLayout()
        region_row.addWidget(QLabel("Capture Area:"))
        self.region_combo = QComboBox()
        self.region_combo.addItems(["Full Screen", "Custom Region", "Primary Monitor"])
        self.region_combo.currentIndexChanged.connect(self._on_region_changed)
        self.region_combo.setStyleSheet("QComboBox { padding: 6px; border-radius: 5px; }")
        region_row.addWidget(self.region_combo)
        settings_layout.addLayout(region_row)

        # FPS
        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("Frame Rate:"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(10, 120)
        self.fps_spin.setValue(DEFAULT_FPS)
        self.fps_spin.setSuffix(" FPS")
        self.fps_spin.setStyleSheet("QSpinBox { padding: 6px; border-radius: 5px; }")
        fps_row.addWidget(self.fps_spin)
        settings_layout.addLayout(fps_row)

        # Quality slider
        quality_row = QHBoxLayout()
        quality_row.addWidget(QLabel("Quality:"))
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(10, 100)
        self.quality_slider.setValue(DEFAULT_QUALITY)
        self.quality_slider.valueChanged.connect(self._on_quality_change)
        quality_row.addWidget(self.quality_slider)
        self.quality_label = QLabel(f"{DEFAULT_QUALITY}%")
        self.quality_label.setMinimumWidth(40)
        quality_row.addWidget(self.quality_label)
        settings_layout.addLayout(quality_row)

        # Codec
        codec_row = QHBoxLayout()
        codec_row.addWidget(QLabel("Format:"))
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["MP4 (mp4v)", "AVI (XVID)", "MKV (X264)"])
        self.codec_combo.setStyleSheet("QComboBox { padding: 6px; border-radius: 5px; }")
        codec_row.addWidget(self.codec_combo)
        settings_layout.addLayout(codec_row)

        layout.addWidget(settings_group)

        # Hotkey info
        hotkey_label = QLabel("⌨ Hotkeys: F9 = Start/Stop  •  F10 = Pause/Resume  •  F11 = Screenshot")
        hotkey_label.setAlignment(Qt.AlignCenter)
        hotkey_label.setStyleSheet("color: #888; font-size: 10px; padding: 5px;")
        layout.addWidget(hotkey_label)

        # Control buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.record_btn = ModernButton("⏺ Record", "#e74c3c")
        self.record_btn.clicked.connect(self._toggle_recording)
        btn_layout.addWidget(self.record_btn)

        self.pause_btn = ModernButton("⏸ Pause", "#f39c12")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._toggle_pause)
        btn_layout.addWidget(self.pause_btn)

        self.screenshot_btn = ModernButton("📷 Screenshot", "#2ecc71")
        self.screenshot_btn.clicked.connect(self._take_screenshot)
        btn_layout.addWidget(self.screenshot_btn)

        layout.addLayout(btn_layout)

        # Output folder
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("📁 Output:"))
        self.folder_label = QLabel(DEFAULT_OUTPUT_DIR)
        self.folder_label.setStyleSheet("color: #aaa; font-size: 10px;")
        self.folder_label.setWordWrap(True)
        folder_row.addWidget(self.folder_label, 1)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_folder)
        browse_btn.setStyleSheet("QPushButton { padding: 5px 12px; border-radius: 5px; }")
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)

        # System tray checkbox
        self.tray_check = QCheckBox("Minimize to system tray")
        self.tray_check.setChecked(True)
        self.tray_check.setStyleSheet("color: #aaa;")
        layout.addWidget(self.tray_check)

        # Apply dark theme
        self.setStyleSheet("""
            QMainWindow { background-color: #0d1117; }
            QWidget { background-color: #0d1117; color: #e6e6e6; }
            QComboBox, QSpinBox {
                background-color: #161b22;
                color: #e6e6e6;
                border: 1px solid #333;
                padding: 5px;
            }
            QComboBox:hover, QSpinBox:hover {
                border: 1px solid #00aeff;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #333;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #00aeff;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QGroupBox { color: #ccc; }
            QCheckBox { color: #aaa; }
            QCheckBox::indicator {
                width: 16px; height: 16px;
                border-radius: 3px;
                border: 2px solid #555;
                background: #161b22;
            }
            QCheckBox::indicator:checked {
                background: #00aeff;
                border-color: #00aeff;
            }
        """)

    def _init_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray_icon = self._create_tray_icon()
        self.tray.setIcon(self.tray_icon)
        self.tray.setToolTip(APP_NAME)
        
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show")
        show_action.triggered.connect(self._show_window)
        stop_action = tray_menu.addAction("Stop Recording")
        stop_action.triggered.connect(self._stop_recording)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self._quit_app)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _create_tray_icon(self):
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(0, 174, 255))
        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawEllipse(8, 8, 16, 16)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(13, 13, 6, 6)
        painter.end()
        return QIcon(pixmap)

    def _init_hotkeys(self):
        if not PYNPUT_AVAILABLE:
            return
        
        def on_press(key):
            try:
                if key == pynput_keyboard.Key.f9:
                    self._toggle_recording()
                elif key == pynput_keyboard.Key.f10:
                    self._toggle_pause()
                elif key == pynput_keyboard.Key.f11:
                    self._take_screenshot()
            except Exception:
                pass

        try:
            self.hotkey_listener = pynput_keyboard.Listener(on_press=on_press)
            self.hotkey_listener.daemon = True
            self.hotkey_listener.start()
        except Exception:
            pass

    def _load_settings(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                self.fps_spin.setValue(config.get('fps', DEFAULT_FPS))
                self.quality_slider.setValue(config.get('quality', DEFAULT_QUALITY))
                self.codec_combo.setCurrentIndex(config.get('codec_index', 0))
                self.folder_label.setText(config.get('output_dir', DEFAULT_OUTPUT_DIR))
        except Exception:
            pass

    def _save_settings(self):
        config = {
            'fps': self.fps_spin.value(),
            'quality': self.quality_slider.value(),
            'codec_index': self.codec_combo.currentIndex(),
            'output_dir': self.folder_label.text()
        }
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f)
        except Exception:
            pass

    def _get_codec_settings(self):
        idx = self.codec_combo.currentIndex()
        if idx == 0:
            return 'mp4v', '.mp4'
        elif idx == 1:
            return 'XVID', '.avi'
        else:
            return 'X264', '.mk4'

    def _generate_filename(self):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        _, ext = self._get_codec_settings()
        return os.path.join(self.folder_label.text(), f"recording_{timestamp}{ext}")

    def _on_quality_change(self, value):
        self.quality_label.setText(f"{value}%")

    def _on_region_changed(self, index):
        if index == 1:  # Custom Region
            self.region_selector.region_selected.connect(self._on_region_selected, Qt.UniqueConnection)
            self.region_selector.start_selection()

    def _on_region_selected(self, x, y, w, h):
        self.selected_region = (x, y, w, h)
        self.selected_region_name = f"Region ({w}x{h})"
        self.status_label.setText(f"● Region selected: {w}x{h} at ({x},{y})")

    def _on_region_cancelled(self):
        self.region_combo.setCurrentIndex(0)
        self.selected_region = None
        self.selected_region_name = "Full Screen"

    def _toggle_recording(self):
        if self.engine.state == RecordingState.IDLE:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        output = self._generate_filename()
        codec, _ = self._get_codec_settings()
        region = self.selected_region
        
        if self.region_combo.currentIndex() == 0:
            region = None  # Full screen
        elif self.region_combo.currentIndex() == 2:
            region = None  # Primary monitor (handled by mss)

        success = self.engine.start(
            output_path=output,
            region=region,
            fps=self.fps_spin.value(),
            quality=self.quality_slider.value(),
            codec=codec
        )

        if success:
            self.record_btn.setText("⏹ Stop")
            self.record_btn.setStyleSheet("""
                QPushButton {
                    background-color: #555;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 8px 20px;
                    font-weight: bold;
                    font-size: 11pt;
                }
            """)
            self.pause_btn.setEnabled(True)
            self.status_label.setText("● Recording...")
            self.status_label.setStyleSheet("color: #e74c3c; margin: 5px; font-weight: bold;")
            self.setWindowOpacity(0.9)
            
            for combo in [self.region_combo, self.fps_spin, self.codec_combo]:
                combo.setEnabled(False)
            self.quality_slider.setEnabled(False)

    def _stop_recording(self):
        self.engine.stop()
        self.record_btn.setText("⏺ Record")
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 20px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #c0392b; }
            QPushButton:disabled { background-color: #555; color: #999; }
        """)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("⏸ Pause")
        self.status_label.setText("● Processing...")
        self.status_label.setStyleSheet("color: #f39c12; margin: 5px;")
        self.setWindowOpacity(1.0)

        for combo in [self.region_combo, self.fps_spin, self.codec_combo]:
            combo.setEnabled(True)
        self.quality_slider.setEnabled(True)

    def _toggle_pause(self):
        if self.engine.state == RecordingState.RECORDING:
            self.engine.pause()
            self.pause_btn.setText("▶ Resume")
            self.status_label.setText("● Paused")
            self.status_label.setStyleSheet("color: #f39c12; margin: 5px;")
        elif self.engine.state == RecordingState.PAUSED:
            self.engine.resume()
            self.pause_btn.setText("⏸ Pause")
            self.status_label.setText("● Recording...")
            self.status_label.setStyleSheet("color: #e74c3c; margin: 5px; font-weight: bold;")

    def _take_screenshot(self):
        try:
            if not MSS_AVAILABLE:
                QMessageBox.warning(self, "Error", "mss library not available!")
                return
            
            with mss.mss() as sct:
                if self.selected_region:
                    monitor = {
                        "left": self.selected_region[0],
                        "top": self.selected_region[1],
                        "width": self.selected_region[2],
                        "height": self.selected_region[3]
                    }
                else:
                    monitor = sct.monitors[1]
                
                img = sct.grab(monitor)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                path = os.path.join(self.folder_label.text(), f"screenshot_{timestamp}.png")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                mss.tools.to_png(img.rgb, img.size, output=path)
                
                self.tray.showMessage("Screenshot Saved", path, QSystemTrayIcon.Information, 2000)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Screenshot failed: {str(e)}")

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", self.folder_label.text())
        if folder:
            self.folder_label.setText(folder)

    def _on_timer_update(self, time_str):
        self.timer_label.setText(time_str)

    def _on_recording_finished(self, path):
        self.status_label.setText("● Ready")
        self.status_label.setStyleSheet("color: #4CAF50; margin: 5px;")
        self.timer_label.setText("00:00:00")
        self.tray.showMessage(
            "Recording Saved",
            f"File: {path}\nFrames: {self.engine.frame_count}",
            QSystemTrayIcon.Information, 3000
        )

    def _on_error(self, msg):
        self.status_label.setText(f"● Error: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c; margin: 5px;")
        QMessageBox.critical(self, "Recording Error", msg)
        self._stop_recording()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_window()

    def _show_window(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event):
        if self.engine.state != RecordingState.IDLE:
            reply = QMessageBox.question(
                self, "Recording Active",
                "Recording is in progress. Stop and quit?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._stop_recording()
                event.accept()
            else:
                event.ignore()
        else:
            self._save_settings()
            event.accept()

    def _quit_app(self):
        if self.engine.state != RecordingState.IDLE:
            self.engine.stop()
        self._save_settings()
        QApplication.quit()

    def changeEvent(self, event):
        if event.type() == event.WindowStateChange:
            if self.isMinimized() and self.tray_check.isChecked():
                self.hide()
                self.tray.showMessage(
                    APP_NAME,
                    "Minimized to system tray. Double-click to restore.",
                    QSystemTrayIcon.Information, 1500
                )


def main():
    if not PYQT5:
        print("ERROR: PyQt5 is required. Install with: pip install PyQt5")
        sys.exit(1)
    
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)
    
    window = ScreenRecorderWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
