"""
Screen Recorder Pro v2.0 - Windows
Countdown, Floating Controls, Webcam PiP, Drawing Tools, GIF Export, Multi-Monitor
"""

import sys, os, time, threading, datetime, json, wave, math, subprocess, shutil, logging
from pathlib import Path

# ─── Logging ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("ScreenRecorder")

try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QComboBox, QCheckBox, QFileDialog,
        QSystemTrayIcon, QMenu, QMessageBox, QGroupBox, QSlider,
        QSpinBox, QFrame, QTabWidget, QListWidget, QListWidgetItem,
        QColorDialog, QSplitter, QToolButton, QButtonGroup, QStatusBar,
        QGraphicsDropShadowEffect, QInputDialog
    )
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QRect, QThread, QPoint, QPropertyAnimation, QEasingCurve
    from PyQt5.QtGui import (
        QIcon, QPixmap, QPainter, QColor, QFont, QKeySequence, QPen,
        QBrush, QRadialGradient, QFontMetrics, QCursor, QRegion, QPalette
    )
    HAS_PYQT5 = True
except ImportError:
    HAS_PYQT5 = False

try:
    import mss, mss.tools
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    import cv2, numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    from pynput import keyboard as pynput_kb
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False

APP_NAME = "Screen Recorder Pro"
APP_VERSION = "2.0.0"
OUTPUT_DIR = str(Path.home() / "Videos" / "ScreenRecorder")
CONFIG_FILE = str(Path.home() / ".screen_recorder_pro.json")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ─── FFmpeg Detection ───
def _find_ffmpeg():
    """Find ffmpeg on PATH or common locations. Returns path or None."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    # Common Windows locations
    for candidate in [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        os.path.expanduser(r"~\ffmpeg\bin\ffmpeg.exe"),
    ]:
        if os.path.isfile(candidate):
            return candidate
    return None


HAS_FFMPEG = _find_ffmpeg() is not None
FFMPEG_PATH = _find_ffmpeg()

if HAS_FFMPEG:
    log.info(f"FFmpeg found: {FFMPEG_PATH}")
else:
    log.warning("FFmpeg not found. Audio/video muxing disabled. Install FFmpeg for combined output.")


def _quality_to_crf(quality):
    """Map quality slider (10-100) to FFmpeg CRF value.
    quality 10  -> CRF 35 (low quality, small file)
    quality 50  -> CRF 25 (medium)
    quality 100 -> CRF 15 (high quality, large file)
    """
    return max(15, min(35, int(51 - (quality / 100.0 * 36))))


def _mux_audio_video(video_path, audio_path, output_path):
    """Mux separate video and audio files into a single media file using FFmpeg.
    Returns True on success, False on failure.
    """
    if not HAS_FFMPEG:
        log.warning("Cannot mux: FFmpeg not available")
        return False
    if not os.path.isfile(video_path):
        log.error(f"Mux failed: video file not found: {video_path}")
        return False
    if not os.path.isfile(audio_path):
        log.error(f"Mux failed: audio file not found: {audio_path}")
        return False
    cmd = [
        FFMPEG_PATH, "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]
    log.info(f"Muxing: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log.error(f"FFmpeg mux failed (rc={result.returncode}): {result.stderr[-500:]}")
            return False
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            log.info(f"Mux success: {output_path} ({os.path.getsize(output_path)} bytes)")
            return True
        log.error(f"Mux output file missing or empty: {output_path}")
        return False
    except subprocess.TimeoutExpired:
        log.error("FFmpeg mux timed out after 120s")
        return False
    except Exception as e:
        log.error(f"Mux exception: {e}")
        return False


def _safe_delete(path):
    """Safely delete a file, logging any errors."""
    try:
        if path and os.path.isfile(path):
            os.remove(path)
            log.info(f"Cleaned temp file: {path}")
    except OSError as e:
        log.warning(f"Could not delete temp file {path}: {e}")


class RecordingState:
    IDLE = 0
    STARTING = 1
    RECORDING = 2
    PAUSED = 3
    STOPPING = 4
    FINALIZING = 5
    ERROR = 6


class EngineSignals(QObject):
    timer_tick = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    frame_ready = pyqtSignal(object)
    countdown_tick = pyqtSignal(int)


class RecordingEngine:
    def __init__(self, signals: EngineSignals):
        self.sig = signals
        self.state = RecordingState.IDLE
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread = None
        self.frame_count = 0
        self.start_time = 0
        self.output_path = ""
        self.region = None
        self.monitor_index = 1
        self.fps = 30
        self.codec = "mp4v"
        self.ext = ".mp4"
        self.quality = 80
        self.audio_enabled = False
        self.audio_device_index = None
        self._audio_stream = None
        self._audio_frames = []
        self._audio_thread = None
        self.webcam_enabled = False
        self.webcam_index = 0
        self.webcam_pos = "bottom-right"
        self.webcam_scale = 0.25
        self._cap = None
        self.draw_overlay = None
        self.cursor_highlight = False
        self.cursor_radius = 20
        self._temp_video_path = None
        self._temp_audio_path = None
        self._dropped_frames = 0

    def _set_state(self, new_state):
        with self._lock:
            old = self.state
            self.state = new_state
            log.debug(f"State: {old} -> {new_state}")

    def _can_transition(self, target):
        """Check if transition to target state is valid."""
        with self._lock:
            valid = {
                RecordingState.IDLE: {RecordingState.STARTING},
                RecordingState.STARTING: {RecordingState.RECORDING, RecordingState.IDLE, RecordingState.ERROR},
                RecordingState.RECORDING: {RecordingState.PAUSED, RecordingState.STOPPING},
                RecordingState.PAUSED: {RecordingState.RECORDING, RecordingState.STOPPING},
                RecordingState.STOPPING: {RecordingState.FINALIZING},
                RecordingState.FINALIZING: {RecordingState.IDLE},
            }
            allowed = valid.get(self.state, set())
            if target not in allowed:
                log.warning(f"Invalid state transition: {self.state} -> {target}")
                return False
            return True

    def start(self, path):
        if not self._can_transition(RecordingState.STARTING):
            return False
        self._set_state(RecordingState.STARTING)
        self.output_path = path
        self.frame_count = 0
        self._dropped_frames = 0
        self._stop.clear()
        self._pause.clear()
        self._temp_video_path = None
        self._temp_audio_path = None
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)

        # Use temp files when FFmpeg is available for muxing
        if self.audio_enabled and HAS_FFMPEG:
            base = path.rsplit(".", 1)[0]
            self._temp_video_path = base + "_tmp_video.mp4"
            self._temp_audio_path = base + "_tmp_audio.wav"

        self._thread = threading.Thread(target=self._loop, name="video-capture", daemon=True)
        self._thread.start()
        if self.audio_enabled:
            self._audio_thread = threading.Thread(target=self._audio_loop, name="audio-capture", daemon=True)
            self._audio_thread.start()
        log.info(f"Recording started: {path} (audio={self.audio_enabled}, ffmpeg={HAS_FFMPEG})")
        return True

    def stop(self):
        if self.state in (RecordingState.IDLE, RecordingState.STOPPING, RecordingState.FINALIZING):
            log.warning(f"stop() called in state {self.state}, ignoring")
            return
        log.info("Stop requested")
        self._set_state(RecordingState.STOPPING)
        self._stop.set()
        self._pause.set()  # Unblock audio thread if paused

    def pause(self):
        if not self._can_transition(RecordingState.PAUSED):
            return
        self._set_state(RecordingState.PAUSED)
        self._pause.clear()
        log.info("Recording paused")

    def resume(self):
        if not self._can_transition(RecordingState.RECORDING):
            return
        self._set_state(RecordingState.RECORDING)
        self._pause.set()
        log.info("Recording resumed")

    def _audio_loop(self):
        if not HAS_PYAUDIO:
            return
        pa = None
        try:
            pa = pyaudio.PyAudio()
            dev_idx = self.audio_device_index
            # Validate device index
            if dev_idx is not None:
                try:
                    info = pa.get_device_info_by_index(dev_idx)
                    if info["maxInputChannels"] <= 0:
                        log.warning(f"Audio device {dev_idx} has no input channels, using default")
                        dev_idx = None
                except Exception:
                    log.warning(f"Audio device {dev_idx} not found, using default")
                    dev_idx = None
            self._audio_stream = pa.open(
                format=pyaudio.paInt16, channels=1, rate=44100,
                input=True, input_device_index=dev_idx,
                frames_per_buffer=1024
            )
            self._audio_frames = []
            while not self._stop.is_set():
                if self._pause.is_set():
                    try:
                        data = self._audio_stream.read(1024, exception_on_overflow=False)
                        self._audio_frames.append(data)
                    except IOError as e:
                        log.warning(f"Audio read overflow: {e}")
                    except Exception as e:
                        log.warning(f"Audio read error: {e}")
                        break
                else:
                    time.sleep(0.01)  # Yield while paused
            self._audio_stream.stop_stream()
            self._audio_stream.close()
            self._audio_stream = None

            # Write WAV
            if self._audio_frames:
                wav_path = self._temp_audio_path or (self.output_path.rsplit(".", 1)[0] + "_audio.wav")
                self._temp_audio_path = wav_path
                wf = wave.open(wav_path, "wb")
                wf.setnchannels(1)
                wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
                wf.setframerate(44100)
                wf.writeframes(b"".join(self._audio_frames))
                wf.close()
                log.info(f"Audio saved: {wav_path} ({len(self._audio_frames)} chunks)")
            else:
                log.warning("No audio frames captured")
        except Exception as e:
            log.error(f"Audio capture error: {e}")
            self.sig.error.emit(f"Audio error: {e}")
        finally:
            if pa is not None:
                try:
                    pa.terminate()
                except Exception:
                    pass

    def _get_cursor_pos(self):
        try:
            pos = QCursor.pos()
            return int(pos.x()), int(pos.y())
        except Exception:
            return -1, -1

    def _draw_cursor_highlight(self, frame, cx, cy, sx, sy):
        if not self.cursor_highlight or cx < 0:
            return
        fx = int(cx * sx)
        fy = int(cy * sy)
        r = self.cursor_radius
        overlay = frame.copy()
        cv2.circle(overlay, (fx, fy), r, (0, 174, 255), -1)
        cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)
        cv2.circle(frame, (fx, fy), r, (0, 174, 255), 2)
        cv2.circle(frame, (fx, fy), 4, (255, 255, 255), -1)

    def _loop(self):
        sct = None
        writer = None
        cam = None
        ffmpeg_proc = None
        final_path = self.output_path
        video_path = self._temp_video_path or self.output_path
        error_msg = None

        try:
            if not HAS_MSS:
                raise RuntimeError("mss not installed: pip install mss")
            if not HAS_CV2:
                raise RuntimeError("opencv not installed: pip install opencv-python")

            sct = mss.mss()
            if self.region:
                monitor = {"left": self.region[0], "top": self.region[1],
                           "width": self.region[2], "height": self.region[3]}
            else:
                mon_list = sct.monitors
                idx = min(self.monitor_index, len(mon_list) - 1)
                monitor = mon_list[idx]

            w = monitor["width"] & ~1
            h = monitor["height"] & ~1

            # Determine encoding approach
            use_ffmpeg_pipe = HAS_FFMPEG and self.audio_enabled and self._temp_video_path

            if use_ffmpeg_pipe:
                # Pipe raw frames directly to FFmpeg for encoding
                crf = _quality_to_crf(self.quality)
                cmd = [
                    FFMPEG_PATH, "-y",
                    "-f", "rawvideo", "-vcodec", "rawvideo",
                    "-s", f"{w}x{h}", "-pix_fmt", "bgr24",
                    "-r", str(self.fps),
                    "-i", "-",
                    "-c:v", "libx264", "-preset", "fast",
                    "-crf", str(crf),
                    "-pix_fmt", "yuv420p",
                    video_path,
                ]
                log.info(f"FFmpeg encode: CRF={crf}, {w}x{h}@{self.fps}fps -> {video_path}")
                ffmpeg_proc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
                writer = None
            else:
                # Fallback to OpenCV VideoWriter
                fourcc = cv2.VideoWriter_fourcc(*self.codec)
                writer = cv2.VideoWriter(video_path, fourcc, self.fps, (w, h))
                if not writer.isOpened():
                    raise RuntimeError(
                        f"Cannot open video writer with codec '{self.codec}'. "
                        "Try a different format or install FFmpeg."
                    )
                log.info(f"OpenCV writer: codec={self.codec}, {w}x{h}@{self.fps}fps -> {video_path}")

            # Webcam setup
            cam = None
            if self.webcam_enabled and HAS_CV2:
                try:
                    cam = cv2.VideoCapture(self.webcam_index)
                    if not cam.isOpened():
                        log.warning(f"Webcam {self.webcam_index} not available")
                        cam = None
                except Exception as e:
                    log.warning(f"Webcam open failed: {e}")
                    cam = None
            self._cap = cam

            self._set_state(RecordingState.RECORDING)
            self.start_time = time.time()
            self._pause.set()

            interval = 1.0 / self.fps
            while not self._stop.is_set():
                self._pause.wait()
                if self._stop.is_set():
                    break
                t0 = time.time()
                try:
                    img = sct.grab(monitor)
                    frame = np.array(img)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    if frame.shape[1] != w or frame.shape[0] != h:
                        frame = cv2.resize(frame, (w, h))

                    # cursor highlight
                    if self.cursor_highlight:
                        cx, cy = self._get_cursor_pos()
                        sx = w / monitor.get("width", w)
                        sy = h / monitor.get("height", h)
                        self._draw_cursor_highlight(frame, cx, cy, sx, sy)

                    # webcam PiP overlay
                    if cam and cam.isOpened():
                        ret, cam_frame = cam.read()
                        if ret:
                            cw = int(w * self.webcam_scale)
                            ch = int(cw * cam_frame.shape[0] / cam_frame.shape[1])
                            cam_small = cv2.resize(cam_frame, (cw, ch))
                            margin = 15
                            if self.webcam_pos == "top-left":
                                px, py = margin, margin
                            elif self.webcam_pos == "top-right":
                                px, py = w - cw - margin, margin
                            elif self.webcam_pos == "bottom-left":
                                px, py = margin, h - ch - margin
                            else:
                                px, py = w - cw - margin, h - ch - margin
                            px = max(0, min(px, w - cw))
                            py = max(0, min(py, h - ch))
                            mask = np.zeros((ch, cw), dtype=np.uint8)
                            cv2.rectangle(mask, (4, 4), (cw - 4, ch - 4), 255, -1)
                            roi = frame[py:py + ch, px:px + cw]
                            if roi.shape[:2] == mask.shape:
                                masked = cv2.bitwise_and(cam_small, cam_small, mask=mask)
                                mask_inv = cv2.bitwise_not(mask)
                                bg = cv2.bitwise_and(roi, roi, mask=mask_inv)
                                frame[py:py + ch, px:px + cw] = cv2.add(masked, bg)
                                cv2.rectangle(frame, (px + 2, py + 2), (px + cw - 2, py + ch - 2), (0, 174, 255), 2)

                    # draw overlay
                    if self.draw_overlay and self.draw_overlay.drawing_visible:
                        overlay = self.draw_overlay.get_overlay_frame(w, h)
                        if overlay is not None:
                            frame = cv2.add(frame, overlay)

                    # Write frame
                    if ffmpeg_proc and ffmpeg_proc.stdin:
                        try:
                            ffmpeg_proc.stdin.write(frame.tobytes())
                        except BrokenPipeError:
                            log.error("FFmpeg pipe broken")
                            break
                    elif writer:
                        writer.write(frame)

                    self.frame_count += 1

                    # Emit timer every ~1 second (not every frame)
                    if self.frame_count % max(1, self.fps) == 0:
                        elapsed = time.time() - self.start_time
                        hh = int(elapsed // 3600)
                        mm = int((elapsed % 3600) // 60)
                        ss = int(elapsed % 60)
                        self.sig.timer_tick.emit(f"{hh:02d}:{mm:02d}:{ss:02d}")

                except Exception as e:
                    self._dropped_frames += 1
                    if self._dropped_frames <= 3:
                        log.warning(f"Frame error ({self._dropped_frames}): {e}")
                    elif self._dropped_frames == 4:
                        log.warning("Suppressing further frame error messages")
                    break

                dt = time.time() - t0
                sl = max(0, interval - dt)
                if sl > 0:
                    time.sleep(sl)

        except Exception as e:
            error_msg = str(e)
            log.error(f"Recording error: {e}")
        finally:
            # ── Cleanup resources in deterministic order ──
            if writer:
                try:
                    writer.release()
                except Exception as e:
                    log.warning(f"Writer release error: {e}")

            if ffmpeg_proc:
                try:
                    if ffmpeg_proc.stdin and not ffmpeg_proc.stdin.closed:
                        ffmpeg_proc.stdin.close()
                    ffmpeg_proc.wait(timeout=15)
                    if ffmpeg_proc.returncode != 0:
                        stderr_out = ffmpeg_proc.stderr.read().decode(errors="replace") if ffmpeg_proc.stderr else ""
                        log.error(f"FFmpeg exited with code {ffmpeg_proc.returncode}: {stderr_out[-500:]}")
                        if not error_msg:
                            error_msg = "FFmpeg encoding failed"
                except subprocess.TimeoutExpired:
                    log.warning("FFmpeg process timeout, force killing")
                    ffmpeg_proc.kill()
                except Exception as e:
                    log.warning(f"FFmpeg cleanup error: {e}")

            if cam:
                try:
                    cam.release()
                except Exception as e:
                    log.warning(f"Webcam release error: {e}")

            if sct:
                try:
                    sct.close()
                except Exception as e:
                    log.warning(f"Screen capture close error: {e}")

            self._cap = None

            # ── Wait for audio thread ──
            if self._audio_thread and self._audio_thread.is_alive():
                log.info("Waiting for audio thread to finish...")
                self._audio_thread.join(timeout=10)
                if self._audio_thread.is_alive():
                    log.warning("Audio thread did not stop within 10s")

            # ── Finalize / Mux ──
            self._set_state(RecordingState.FINALIZING)
            try:
                if not error_msg:
                    if self._temp_video_path and self._temp_audio_path and os.path.isfile(self._temp_audio_path):
                        # Mux video + audio into final file
                        log.info("Muxing audio + video...")
                        if _mux_audio_video(self._temp_video_path, self._temp_audio_path, final_path):
                            log.info(f"Final output: {final_path}")
                        else:
                            log.error("Mux failed, falling back to video-only output")
                            shutil.copy2(self._temp_video_path, final_path)
                    elif self._temp_audio_path and os.path.isfile(self._temp_audio_path):
                        # Audio-only (no video captured), just use WAV
                        final_path = self._temp_audio_path
                        self._temp_audio_path = None

                    # Verify output
                    if os.path.isfile(final_path) and os.path.getsize(final_path) > 0:
                        log.info(f"Recording complete: {final_path} ({os.path.getsize(final_path)} bytes, "
                                 f"{self.frame_count} frames, {self._dropped_frames} dropped)")
                    elif not error_msg:
                        error_msg = "Output file is empty or missing"
            except Exception as e:
                log.error(f"Finalization error: {e}")
                if not error_msg:
                    error_msg = f"Finalization error: {e}"
            finally:
                # ── Cleanup temp files ──
                _safe_delete(self._temp_video_path)
                _safe_delete(self._temp_audio_path)
                self._temp_video_path = None
                self._temp_audio_path = None

                # ── Emit result ──
                self._set_state(RecordingState.IDLE)
                if error_msg:
                    self.sig.error.emit(error_msg)
                elif os.path.isfile(final_path) and os.path.getsize(final_path) > 0:
                    self.sig.finished.emit(final_path)
                else:
                    self.sig.error.emit("Recording produced no output")


def get_monitors():
    if not HAS_MSS:
        return ["Primary"]
    sct = mss.mss()
    result = []
    for i, m in enumerate(sct.monitors):
        if i == 0:
            continue
        result.append(f"Monitor {i}: {m['width']}x{m['height']} @ ({m['left']},{m['top']})")
    sct.close()
    return result if result else ["Primary"]


def get_audio_devices():
    if not HAS_PYAUDIO:
        return []
    try:
        pa = pyaudio.PyAudio()
        devices = []
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                devices.append((i, info["name"][:40]))
        pa.terminate()
        return devices
    except Exception as e:
        log.warning(f"Could not enumerate audio devices: {e}")
        return []


def get_webcam_list():
    if not HAS_CV2:
        return []
    cams = []
    for i in range(4):
        try:
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                cams.append((i, f"Camera {i}"))
                cap.release()
        except Exception as e:
            log.debug(f"Webcam {i} probe failed: {e}")
    return cams


def get_video_duration(path):
    """Get video duration in seconds using OpenCV."""
    if not HAS_CV2:
        return 0
    try:
        cap = cv2.VideoCapture(path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        if fps > 0:
            return frames / fps
    except Exception as e:
        log.debug(f"Could not read duration for {path}: {e}")
    return 0


def convert_to_gif(video_path, output_path, fps=10, max_width=480):
    """Convert a video file to GIF."""
    if not HAS_CV2:
        return False
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return False
        orig_fps = cap.get(cv2.CAP_PROP_FPS)
        frames = []
        skip = max(1, int(orig_fps / fps))
        count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if count % skip == 0:
                h, w = frame.shape[:2]
                if w > max_width:
                    ratio = max_width / w
                    frame = cv2.resize(frame, (max_width, int(h * ratio)))
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frames.append(frame_rgb)
            count += 1
        cap.release()
        if not frames:
            return False
        # Write GIF manually using PIL
        try:
            from PIL import Image
            pil_frames = [Image.fromarray(f) for f in frames]
            duration = int(1000 / fps)
            pil_frames[0].save(
                output_path, save_all=True, append_images=pil_frames[1:],
                duration=duration, loop=0, optimize=True
            )
            return True
        except ImportError:
            return False
    except Exception:
        return False


class CountdownOverlay(QWidget):
    """Full-screen countdown overlay (3, 2, 1) before recording starts."""
    countdown_done = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(0.85)
        self._count = 3
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._scale = 1.0
        self._scale_timer = QTimer(self)
        self._scale_timer.timeout.connect(self._animate)
        self._scale_timer.setInterval(16)

    def start(self):
        self._count = 3
        self._scale = 1.0
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self.showFullScreen()
        self.raise_()
        self._timer.start(800)
        self._scale_timer.start()

    def _tick(self):
        self._count -= 1
        self._scale = 1.0
        self.update()
        if self._count <= 0:
            self._timer.stop()
            self._scale_timer.stop()
            self.hide()
            self.countdown_done.emit()

    def _animate(self):
        self._scale = max(0.6, self._scale - 0.025)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))
        text = str(max(1, self._count))
        p.save()
        center = self.rect().center()
        p.translate(center)
        p.scale(self._scale, self._scale)
        # glow
        for i in range(3):
            alpha = 40 - i * 12
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 174, 255, alpha))
            p.drawEllipse(QPoint(0, 0), 120 + i * 30, 120 + i * 30)
        # number
        font = QFont("Segoe UI", 120, QFont.Bold)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRect(-200, -150, 400, 300), Qt.AlignCenter, text)
        p.restore()
        p.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._timer.stop()
            self._scale_timer.stop()
            self.hide()
            self.countdown_done.emit()


class FloatingControlBar(QWidget):
    """Mini floating control bar shown during recording."""
    sig_stop = pyqtSignal()
    sig_pause = pyqtSignal()
    sig_draw = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedHeight(48)
        self.setMinimumWidth(320)
        self._drag_pos = None
        self._paused = False
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        # recording indicator dot
        self.dot_lbl = QLabel("●")
        self.dot_lbl.setStyleSheet("color: #e74c3c; font-size: 14px;")
        layout.addWidget(self.dot_lbl)

        # timer
        self.timer_lbl = QLabel("00:00:00")
        self.timer_lbl.setFont(QFont("Consolas", 13, QFont.Bold))
        self.timer_lbl.setStyleSheet("color: #e74c3c; background: transparent;")
        layout.addWidget(self.timer_lbl)

        layout.addSpacing(8)

        # pause button
        self.pause_btn = QPushButton("⏸")
        self.pause_btn.setFixedSize(32, 32)
        self.pause_btn.setToolTip("Pause / Resume")
        self.pause_btn.setStyleSheet("""
            QPushButton { background: #f39c12; color: white; border: none; border-radius: 16px; font-size: 14px; }
            QPushButton:hover { background: #e67e22; }
        """)
        self.pause_btn.clicked.connect(self._on_pause)
        layout.addWidget(self.pause_btn)

        # draw toggle
        self.draw_btn = QPushButton("✏")
        self.draw_btn.setFixedSize(32, 32)
        self.draw_btn.setToolTip("Toggle Drawing")
        self.draw_btn.setStyleSheet("""
            QPushButton { background: #3498db; color: white; border: none; border-radius: 16px; font-size: 14px; }
            QPushButton:hover { background: #2980b9; }
        """)
        self.draw_btn.clicked.connect(self.sig_draw.emit)
        layout.addWidget(self.draw_btn)

        # stop button
        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setFixedSize(32, 32)
        self.stop_btn.setToolTip("Stop Recording")
        self.stop_btn.setStyleSheet("""
            QPushButton { background: #e74c3c; color: white; border: none; border-radius: 16px; font-size: 14px; }
            QPushButton:hover { background: #c0392b; }
        """)
        self.stop_btn.clicked.connect(self.sig_stop.emit)
        layout.addWidget(self.stop_btn)

    def _on_pause(self):
        self._paused = not self._paused
        if self._paused:
            self.pause_btn.setText("▶")
            self.dot_lbl.setStyleSheet("color: #f39c12; font-size: 14px;")
            self.timer_lbl.setStyleSheet("color: #f39c12; background: transparent;")
        else:
            self.pause_btn.setText("⏸")
            self.dot_lbl.setStyleSheet("color: #e74c3c; font-size: 14px;")
            self.timer_lbl.setStyleSheet("color: #e74c3c; background: transparent;")
        self.sig_pause.emit()

    def update_timer(self, t):
        self.timer_lbl.setText(t)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(20, 20, 35, 220))
        p.setPen(QPen(QColor(0, 174, 255, 100), 1))
        p.drawRoundedRect(self.rect(), 14, 14)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


class DrawingOverlay(QWidget):
    """Transparent overlay for drawing on screen during recording."""
    closed = pyqtSignal()

    def __init__(self, draw_tools_ref):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.tools_ref = draw_tools_ref
        self.drawing_visible = False
        self.current_tool = "pen"
        self.current_color = QColor(255, 0, 0)
        self.pen_width = 3
        self._strokes = []
        self._current_stroke = []
        self._start_pos = None
        self._drawing = False

    def activate_tool(self, tool):
        self.current_tool = tool
        self.setCursor(Qt.CrossCursor)

    def start_overlay(self):
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self._strokes.clear()
        self.drawing_visible = True
        self.showFullScreen()
        self.raise_()

    def stop_overlay(self):
        self.drawing_visible = False
        self.hide()

    def clear_all(self):
        self._strokes.clear()
        self.update()

    def get_overlay_frame(self, w, h):
        if not self._strokes:
            return None
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        sx = w / self.width()
        sy = h / self.height()
        for tool, color, width, points in self._strokes:
            c = (color.blue(), color.green(), color.red())
            pw = max(1, int(width * sx))
            if tool in ("pen", "eraser"):
                ec = (0, 0, 0) if tool == "eraser" else c
                for i in range(1, len(points)):
                    p1 = (int(points[i - 1].x() * sx), int(points[i - 1].y() * sy))
                    p2 = (int(points[i].x() * sx), int(points[i].y() * sy))
                    if tool == "eraser":
                        cv2.line(frame, p1, p2, ec, pw * 4)
                    else:
                        cv2.line(frame, p1, p2, ec, pw)
            elif tool == "arrow" and len(points) >= 2:
                p1 = (int(points[0].x() * sx), int(points[0].y() * sy))
                p2 = (int(points[-1].x() * sx), int(points[-1].y() * sy))
                cv2.arrowedLine(frame, p1, p2, c, pw, tipLength=0.3)
            elif tool == "rect" and len(points) >= 2:
                p1 = (int(points[0].x() * sx), int(points[0].y() * sy))
                p2 = (int(points[-1].x() * sx), int(points[-1].y() * sy))
                cv2.rectangle(frame, p1, p2, c, pw)
            elif tool == "circle" and len(points) >= 2:
                p1 = (int(points[0].x() * sx), int(points[0].y() * sy))
                p2 = (int(points[-1].x() * sx), int(points[-1].y() * sy))
                cx = (p1[0] + p2[0]) // 2
                cy = (p1[1] + p2[1]) // 2
                rx = abs(p2[0] - p1[0]) // 2
                ry = abs(p2[1] - p1[1]) // 2
                cv2.ellipse(frame, (cx, cy), (rx, ry), 0, 0, 360, c, pw)
        return frame

    def paintEvent(self, event):
        if not self.drawing_visible:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for tool, color, width, points in self._strokes:
            pen = QPen(color if tool != "eraser" else QColor(255, 255, 255),
                       width if tool != "eraser" else width * 4)
            painter.setPen(pen)
            if tool in ("pen", "eraser") and len(points) >= 2:
                for i in range(1, len(points)):
                    painter.drawLine(points[i - 1], points[i])
            elif tool == "arrow" and len(points) >= 2:
                painter.drawLine(points[0], points[-1])
                dx = points[-1].x() - points[-2].x()
                dy = points[-1].y() - points[-2].y()
                angle = math.atan2(dy, dx)
                hl = 15
                for da in [2.7, 3.6]:
                    ax = points[-1].x() - hl * math.cos(angle - math.pi + da)
                    ay = points[-1].y() - hl * math.sin(angle - math.pi + da)
                    painter.drawLine(points[-1].x(), points[-1].y(), int(ax), int(ay))
            elif tool == "rect" and len(points) >= 2:
                r = QRect(points[0], points[-1]).normalized()
                painter.drawRect(r)
            elif tool == "circle" and len(points) >= 2:
                r = QRect(points[0], points[-1]).normalized()
                painter.drawEllipse(r)
            elif tool == "text" and len(points) >= 1:
                painter.setPen(QPen(color))
                painter.setFont(QFont("Segoe UI", 14, QFont.Bold))
                painter.drawText(points[0], self.tools_ref.get_text_input() if hasattr(self.tools_ref, 'get_text_input') else "Text")

    def mousePressEvent(self, event):
        if not self.drawing_visible:
            return
        if event.button() == Qt.LeftButton:
            self._start_pos = event.pos()
            self._current_stroke = [event.pos()]
            self._drawing = True
        elif event.button() == Qt.RightButton:
            if self._strokes:
                self._strokes.pop()
                self.update()

    def mouseMoveEvent(self, event):
        if self._drawing:
            self._current_stroke.append(event.pos())
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drawing and event.button() == Qt.LeftButton:
            self._drawing = False
            if self._current_stroke:
                self._strokes.append((
                    self.current_tool,
                    self.current_color,
                    self.pen_width,
                    list(self._current_stroke)
                ))
                self._current_stroke = []
                self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.stop_overlay()
            self.closed.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(600, 750)
        self.resize(640, 780)
        self.signals = EngineSignals()
        self.engine = RecordingEngine(self.signals)
        self.region_selector = None
        self.settings_data = {}
        self.hotkey_listener = None
        self.selected_region = None
        self.draw_overlay = None
        self.floating_bar = None
        self.countdown = None
        self.recording_history = []
        self.audio_devices = get_audio_devices()
        self.webcam_list = get_webcam_list()
        self.monitor_list = get_monitors()
        self.signals.timer_tick.connect(self._on_tick)
        self.signals.finished.connect(self._on_finished)
        self.signals.error.connect(self._on_error)
        self._init_ui()
        self._init_tray()
        self._init_hotkeys()
        self._load_settings()
        self._center()
        self._update_file_count()
        self._refresh_history()

    # ─── UI ──────────────────────────────────────────────────────
    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(0, 0, 0, 0)

        # gradient header
        hdr = QWidget()
        hdr.setFixedHeight(110)
        hdr.setStyleSheet("""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 #1a1a2e, stop:0.5 #16213e, stop:1 #0f3460);
        """)
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(20, 15, 20, 10)
        hl.setAlignment(Qt.AlignCenter)
        t = QLabel(f"🎬  {APP_NAME}")
        t.setFont(QFont("Segoe UI", 20, QFont.Bold))
        t.setStyleSheet("color: white;")
        t.setAlignment(Qt.AlignCenter)
        hl.addWidget(t)
        sub = QLabel(f"v{APP_VERSION}  •  Webcam PiP  •  Audio  •  Draw  •  GIF  •  Floating Controls")
        sub.setFont(QFont("Segoe UI", 9))
        sub.setStyleSheet("color: #8899aa;")
        sub.setAlignment(Qt.AlignCenter)
        hl.addWidget(sub)
        root.addWidget(hdr)

        # scrollable body
        scroll = QWidget()
        sl = QVBoxLayout(scroll)
        sl.setSpacing(6)
        sl.setContentsMargins(16, 8, 16, 8)

        # timer
        self.timer_lbl = QLabel("00:00:00")
        self.timer_lbl.setFont(QFont("Consolas", 36, QFont.Bold))
        self.timer_lbl.setAlignment(Qt.AlignCenter)
        self.timer_lbl.setStyleSheet(
            "color: #00aeff; background: #1a1a2e; border-radius: 14px; padding: 14px;")
        sl.addWidget(self.timer_lbl)

        self.status_lbl = QLabel("● Ready")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setFont(QFont("Segoe UI", 10))
        self.status_lbl.setStyleSheet("color: #4CAF50;")
        sl.addWidget(self.status_lbl)

        # ── tabs ──
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #333; border-radius: 8px; background: #161b22; }
            QTabBar::tab { background: #0d1117; color: #aaa; padding: 8px 16px;
                           border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }
            QTabBar::tab:selected { background: #161b22; color: #00aeff; font-weight: bold; }
        """)

        # ─── Tab 1: Settings ───
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        l1.setSpacing(8)

        mr = QHBoxLayout()
        mr.addWidget(QLabel("🖥  Monitor:"))
        self.monitor_combo = QComboBox()
        self.monitor_combo.addItems(self.monitor_list)
        mr.addWidget(self.monitor_combo, 1)
        l1.addLayout(mr)

        rr = QHBoxLayout()
        rr.addWidget(QLabel("📐  Region:"))
        self.region_combo = QComboBox()
        self.region_combo.addItems(["Full Screen", "Custom Region"])
        self.region_combo.currentIndexChanged.connect(self._on_region_changed)
        rr.addWidget(self.region_combo, 1)
        l1.addLayout(rr)

        fr = QHBoxLayout()
        fr.addWidget(QLabel("🎞  FPS:"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(10, 120)
        self.fps_spin.setValue(30)
        self.fps_spin.setSuffix(" FPS")
        fr.addWidget(self.fps_spin, 1)
        l1.addLayout(fr)

        qr = QHBoxLayout()
        qr.addWidget(QLabel("⭐  Quality:"))
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(10, 100)
        self.quality_slider.setValue(80)
        self.quality_slider.valueChanged.connect(
            lambda v: self.quality_lbl.setText(f"{v}%"))
        qr.addWidget(self.quality_slider, 1)
        self.quality_lbl = QLabel("80%")
        self.quality_lbl.setMinimumWidth(35)
        qr.addWidget(self.quality_lbl)
        l1.addLayout(qr)

        cr = QHBoxLayout()
        cr.addWidget(QLabel("📦  Format:"))
        self.codec_combo = QComboBox()
        fmt_items = ["MP4 (H.264)", "AVI (MJPEG fallback)", "MKV (H.264)"]
        if HAS_FFMPEG:
            fmt_items = ["MP4 (H.264+AAC)", "AVI (H.264+AAC)", "MKV (H.264+AAC)"]
        self.codec_combo.addItems(fmt_items)
        cr.addWidget(self.codec_combo, 1)
        l1.addLayout(cr)

        # FFmpeg status indicator
        ffmpeg_row = QHBoxLayout()
        if HAS_FFMPEG:
            ffmpeg_lbl = QLabel("✅  FFmpeg detected — audio/video muxing enabled")
            ffmpeg_lbl.setStyleSheet("color: #4CAF50; font-size: 10px;")
        else:
            ffmpeg_lbl = QLabel("⚠  FFmpeg not found — audio saved as separate WAV. Install FFmpeg for muxing.")
            ffmpeg_lbl.setStyleSheet("color: #f39c12; font-size: 10px;")
        ffmpeg_row.addWidget(ffmpeg_lbl)
        l1.addLayout(ffmpeg_row)

        ar = QHBoxLayout()
        ar.addWidget(QLabel("🎤  Audio:"))
        self.audio_check = QCheckBox("Record audio")
        self.audio_check.setChecked(True)
        ar.addWidget(self.audio_check)
        self.audio_combo = QComboBox()
        for idx, name in self.audio_devices:
            self.audio_combo.addItem(name, idx)
        if not self.audio_devices:
            self.audio_combo.addItem("No devices found")
            self.audio_check.setEnabled(False)
        ar.addWidget(self.audio_combo, 1)
        l1.addLayout(ar)

        # Delay start
        dr = QHBoxLayout()
        dr.addWidget(QLabel("⏱  Delay Start:"))
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 30)
        self.delay_spin.setValue(0)
        self.delay_spin.setSuffix(" sec")
        self.delay_spin.setToolTip("0 = no countdown, 1-30 = countdown before recording")
        dr.addWidget(self.delay_spin, 1)
        l1.addLayout(dr)

        # Cursor highlight
        self.cursor_check = QCheckBox("Highlight mouse cursor during recording")
        self.cursor_check.setChecked(False)
        self.cursor_check.setStyleSheet("color: #f39c12;")
        l1.addWidget(self.cursor_check)

        tabs.addTab(w1, "⚙ Settings")

        # ─── Tab 2: Webcam ───
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        l2.setSpacing(10)

        self.webcam_check = QCheckBox("Enable Webcam Overlay (PiP)")
        self.webcam_check.setChecked(False)
        self.webcam_check.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.webcam_check.setStyleSheet("color: #00aeff;")
        l2.addWidget(self.webcam_check)

        wr1 = QHBoxLayout()
        wr1.addWidget(QLabel("Camera:"))
        self.webcam_combo = QComboBox()
        for idx, name in self.webcam_list:
            self.webcam_combo.addItem(name, idx)
        if not self.webcam_list:
            self.webcam_combo.addItem("No camera found")
        wr1.addWidget(self.webcam_combo, 1)
        l2.addLayout(wr1)

        wr2 = QHBoxLayout()
        wr2.addWidget(QLabel("Position:"))
        self.webcam_pos_combo = QComboBox()
        self.webcam_pos_combo.addItems(
            ["Bottom-Right", "Top-Right", "Top-Left", "Bottom-Left"])
        wr2.addWidget(self.webcam_pos_combo, 1)
        l2.addLayout(wr2)

        wr3 = QHBoxLayout()
        wr3.addWidget(QLabel("Size:"))
        self.webcam_size_slider = QSlider(Qt.Horizontal)
        self.webcam_size_slider.setRange(10, 50)
        self.webcam_size_slider.setValue(25)
        self.webcam_size_slider.valueChanged.connect(
            lambda v: self.webcam_size_lbl.setText(f"{v}%"))
        wr3.addWidget(self.webcam_size_slider, 1)
        self.webcam_size_lbl = QLabel("25%")
        wr3.addWidget(self.webcam_size_lbl)
        l2.addLayout(wr3)

        tabs.addTab(w2, "🤳 Webcam")

        # ─── Tab 3: Drawing Tools ───
        w3 = QWidget()
        l3 = QVBoxLayout(w3)
        l3.setSpacing(8)

        self.draw_check = QCheckBox("Show Drawing Toolbar During Recording")
        self.draw_check.setChecked(False)
        self.draw_check.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.draw_check.setStyleSheet("color: #f39c12;")
        l3.addWidget(self.draw_check)

        tbr = QHBoxLayout()
        tbr.setSpacing(6)
        self.draw_tools = {}
        for tool_name, icon in [("pen", "✏"), ("arrow", "➤"), ("rect", "▭"),
                                 ("circle", "○"), ("eraser", "⌫")]:
            btn = QToolButton()
            btn.setText(icon)
            btn.setCheckable(True)
            btn.setFixedSize(40, 40)
            btn.setFont(QFont("Segoe UI", 14))
            btn.setToolTip(tool_name.capitalize())
            btn.setStyleSheet("""
                QToolButton { background: #1a1a2e; color: #aaa; border: 1px solid #333;
                              border-radius: 8px; }
                QToolButton:checked { background: #00aeff; color: white; border-color: #00aeff; }
            """)
            btn.clicked.connect(lambda checked, n=tool_name: self._select_draw_tool(n))
            self.draw_tools[tool_name] = btn
            tbr.addWidget(btn)
        l3.addLayout(tbr)

        clr_row = QHBoxLayout()
        clr_row.addWidget(QLabel("Color:"))
        self.draw_color = QColor(255, 0, 0)
        self.color_btn = QPushButton("  ")
        self.color_btn.setFixedSize(30, 30)
        self._update_color_btn()
        self.color_btn.clicked.connect(self._pick_color)
        clr_row.addWidget(self.color_btn)
        clr_row.addSpacing(10)
        clr_row.addWidget(QLabel("Width:"))
        self.pen_width_slider = QSlider(Qt.Horizontal)
        self.pen_width_slider.setRange(1, 10)
        self.pen_width_slider.setValue(3)
        clr_row.addWidget(self.pen_width_slider, 1)
        l3.addLayout(clr_row)

        tabs.addTab(w3, "✏ Draw")

        # ─── Tab 4: GIF Export ───
        w4 = QWidget()
        l4 = QVBoxLayout(w4)
        l4.setSpacing(10)

        gif_title = QLabel("🎬  GIF Export")
        gif_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        gif_title.setStyleSheet("color: #9b59b6;")
        l4.addWidget(gif_title)

        gif_desc = QLabel("Convert your last recording to an animated GIF.\nSelect a video file from History or browse manually.")
        gif_desc.setStyleSheet("color: #888;")
        gif_desc.setWordWrap(True)
        l4.addWidget(gif_desc)

        gif_fps_row = QHBoxLayout()
        gif_fps_row.addWidget(QLabel("GIF FPS:"))
        self.gif_fps_spin = QSpinBox()
        self.gif_fps_spin.setRange(5, 30)
        self.gif_fps_spin.setValue(10)
        self.gif_fps_spin.setSuffix(" fps")
        gif_fps_row.addWidget(self.gif_fps_spin, 1)
        l4.addLayout(gif_fps_row)

        gif_w_row = QHBoxLayout()
        gif_w_row.addWidget(QLabel("Max Width:"))
        self.gif_width_spin = QSpinBox()
        self.gif_width_spin.setRange(240, 1920)
        self.gif_width_spin.setValue(480)
        self.gif_width_spin.setSuffix(" px")
        self.gif_width_spin.setSingleStep(80)
        gif_w_row.addWidget(self.gif_width_spin, 1)
        l4.addLayout(gif_w_row)

        self.gif_status = QLabel("")
        self.gif_status.setStyleSheet("color: #2ecc71;")
        l4.addWidget(self.gif_status)

        gif_btns = QHBoxLayout()
        self.gif_convert_btn = QPushButton("🔄  Convert Selected to GIF")
        self.gif_convert_btn.setMinimumHeight(40)
        self.gif_convert_btn.setStyleSheet("""
            QPushButton { background: #9b59b6; color: white; border: none; border-radius: 8px;
                          font-weight: bold; font-size: 11pt; padding: 8px 16px; }
            QPushButton:hover { background: #8e44ad; }
        """)
        self.gif_convert_btn.clicked.connect(self._convert_to_gif)
        gif_btns.addWidget(self.gif_convert_btn)
        l4.addLayout(gif_btns)

        gif_browse = QHBoxLayout()
        self.gif_file_lbl = QLabel("No file selected")
        self.gif_file_lbl.setStyleSheet("color: #888; font-size: 10px;")
        gif_browse.addWidget(self.gif_file_lbl, 1)
        gif_browse_btn = QPushButton("Browse Video")
        gif_browse_btn.setFixedHeight(28)
        gif_browse_btn.clicked.connect(self._browse_gif_source)
        gif_browse.addWidget(gif_browse_btn)
        l4.addLayout(gif_browse)

        l4.addStretch()
        tabs.addTab(w4, "🎞 GIF")

        # ─── Tab 5: History ───
        w5 = QWidget()
        l5 = QVBoxLayout(w5)
        self.history_list = QListWidget()
        self.history_list.setStyleSheet("""
            QListWidget { background: #0d1117; color: #ccc; border: 1px solid #333;
                          border-radius: 6px; padding: 4px; }
            QListWidget::item { padding: 8px; border-bottom: 1px solid #222; }
            QListWidget::item:selected { background: #16213e; }
        """)
        self.history_list.itemDoubleClicked.connect(self._play_file)
        l5.addWidget(self.history_list)

        hb = QHBoxLayout()
        open_btn = QPushButton("📂 Open Folder")
        open_btn.clicked.connect(self._open_output_folder)
        hb.addWidget(open_btn)
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._refresh_history)
        hb.addWidget(refresh_btn)
        play_btn = QPushButton("▶ Play Selected")
        play_btn.clicked.connect(self._play_selected)
        hb.addWidget(play_btn)
        del_btn = QPushButton("🗑 Delete Selected")
        del_btn.setStyleSheet("color: #e74c3c;")
        del_btn.clicked.connect(self._delete_selected)
        hb.addWidget(del_btn)
        l5.addLayout(hb)

        tabs.addTab(w5, "📋 History")

        sl.addWidget(tabs)

        # hotkey hint
        hk = QLabel("⌨  F9 = Record/Stop   F10 = Pause   F11 = Screenshot   F12 = GIF Export")
        hk.setAlignment(Qt.AlignCenter)
        hk.setStyleSheet("color: #666; font-size: 10px; padding: 4px;")
        sl.addWidget(hk)

        # controls
        ctrls = QHBoxLayout()
        ctrls.setSpacing(10)
        self.record_btn = self._make_btn("⏺  Record", "#e74c3c")
        self.record_btn.clicked.connect(self._toggle_rec)
        ctrls.addWidget(self.record_btn)
        self.pause_btn = self._make_btn("⏸  Pause", "#f39c12")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._toggle_pause)
        ctrls.addWidget(self.pause_btn)
        self.ss_btn = self._make_btn("📷  Screenshot", "#2ecc71")
        self.ss_btn.clicked.connect(self._screenshot)
        ctrls.addWidget(self.ss_btn)
        sl.addLayout(ctrls)

        # output folder
        fo = QHBoxLayout()
        fo.addWidget(QLabel("📁"))
        self.folder_lbl = QLabel(OUTPUT_DIR)
        self.folder_lbl.setStyleSheet("color: #888; font-size: 10px;")
        self.folder_lbl.setWordWrap(True)
        fo.addWidget(self.folder_lbl, 1)
        browse = QPushButton("Browse")
        browse.setFixedHeight(28)
        browse.clicked.connect(self._browse)
        fo.addWidget(browse)
        sl.addLayout(fo)

        self.file_count_lbl = QLabel("")
        self.file_count_lbl.setAlignment(Qt.AlignCenter)
        self.file_count_lbl.setStyleSheet("color: #555; font-size: 10px; padding-bottom: 4px;")
        sl.addWidget(self.file_count_lbl)

        # ─── Developer Card ───
        dev_frame = QFrame()
        dev_frame.setStyleSheet("""
            QFrame {
                background: #161b22; border: 1px solid #333;
                border-radius: 12px; padding: 4px;
            }
        """)
        dev_layout = QVBoxLayout(dev_frame)
        dev_layout.setContentsMargins(16, 14, 16, 14)
        dev_layout.setSpacing(8)

        dev_title = QLabel("👤  Developer")
        dev_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        dev_title.setStyleSheet("color: white; background: transparent; padding: 0;")
        dev_layout.addWidget(dev_title)

        def _make_link_row(icon, title, subtitle, url):
            row = QFrame()
            row.setCursor(Qt.PointingHandCursor)
            row.setStyleSheet("""
                QFrame { background: #0d1117; border: 1px solid #333; border-radius: 8px;
                         padding: 6px; }
                QFrame:hover { border-color: #00aeff; }
            """)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(12, 8, 12, 8)
            rl.setSpacing(10)
            ic = QLabel(icon)
            ic.setFont(QFont("Segoe UI", 16))
            ic.setStyleSheet("background: transparent; padding: 0;")
            rl.addWidget(ic)
            txt_col = QVBoxLayout()
            txt_col.setSpacing(1)
            tl = QLabel(title)
            tl.setFont(QFont("Segoe UI", 10, QFont.Bold))
            tl.setStyleSheet("color: white; background: transparent; padding: 0;")
            txt_col.addWidget(tl)
            sl2 = QLabel(subtitle)
            sl2.setFont(QFont("Segoe UI", 9))
            sl2.setStyleSheet("color: #00aeff; background: transparent; padding: 0;")
            txt_col.addWidget(sl2)
            rl.addLayout(txt_col, 1)
            arrow = QLabel("→")
            arrow.setFont(QFont("Segoe UI", 12))
            arrow.setStyleSheet("color: #555; background: transparent; padding: 0;")
            rl.addWidget(arrow)
            row.mousePressEvent = lambda e, u=url: __import__('webbrowser').open(u)
            return row

        dev_layout.addWidget(_make_link_row("✈️", "Telegram", "@AnishtayiN", "https://t.me/AnishtayiN"))
        dev_layout.addWidget(_make_link_row("🐙", "GitHub", "github.com/AnishtayiN", "https://github.com/AnishtayiN"))

        star_btn = QPushButton("⭐  Star on GitHub")
        star_btn.setMinimumHeight(36)
        star_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        star_btn.setCursor(Qt.PointingHandCursor)
        star_btn.setStyleSheet("""
            QPushButton { background: #0088cc; color: white; border: none;
                          border-radius: 8px; padding: 6px; }
            QPushButton:hover { background: #00aeff; }
        """)
        star_btn.clicked.connect(lambda: __import__('webbrowser').open("https://github.com/AnishtayiN/ScreenRecorder"))
        dev_layout.addWidget(star_btn)

        sl.addWidget(dev_frame)

        root.addWidget(scroll, 1)

        # status bar
        sb = QStatusBar()
        sb.setStyleSheet("background: #0d1117; color: #666; border-top: 1px solid #222;")
        sb.showMessage("Ready  •  Right-click drawing = Undo  •  Esc = Close drawing overlay")
        self.setStatusBar(sb)

        # global dark
        self.setStyleSheet("""
            QMainWindow { background: #0d1117; }
            QWidget { background: transparent; color: #e6e6e6; }
            QComboBox, QSpinBox { background: #161b22; color: #e6e6e6; border: 1px solid #333; padding: 5px; border-radius: 5px; }
            QComboBox:hover, QSpinBox:hover { border: 1px solid #00aeff; }
            QComboBox QAbstractItemView { background: #161b22; color: #e6e6e6; selection-background-color: #16213e; }
            QSlider::groove:horizontal { height: 5px; background: #333; border-radius: 2px; }
            QSlider::handle:horizontal { background: #00aeff; width: 15px; height: 15px; margin: -5px 0; border-radius: 7px; }
            QCheckBox { color: #aaa; spacing: 6px; }
            QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; border: 2px solid #555; background: #161b22; }
            QCheckBox::indicator:checked { background: #00aeff; border-color: #00aeff; }
            QGroupBox { color: #ccc; border: 1px solid #333; border-radius: 8px; margin-top: 8px; padding-top: 14px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
            QToolTip { background: #161b22; color: #e6e6e6; border: 1px solid #00aeff; padding: 4px; border-radius: 4px; }
        """)

    def _make_btn(self, text, color):
        btn = QPushButton(text)
        btn.setMinimumHeight(48)
        btn.setMinimumWidth(130)
        btn.setFont(QFont("Segoe UI", 11, QFont.Bold))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{ background: {color}; color: white; border: none;
                           border-radius: 10px; padding: 8px 18px; }}
            QPushButton:hover {{ background: {color}dd; }}
            QPushButton:pressed {{ background: {color}aa; }}
            QPushButton:disabled {{ background: #333; color: #666; }}
        """)
        return btn

    # ─── tray ──
    def _init_tray(self):
        self.tray = QSystemTrayIcon(self)
        pix = QPixmap(32, 32)
        pix.fill(QColor(0, 174, 255))
        p = QPainter(pix)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawEllipse(8, 8, 16, 16)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(13, 13, 6, 6)
        p.end()
        self.tray.setIcon(QIcon(pix))
        self.tray.setToolTip(APP_NAME)
        self.tray_menu = QMenu()
        self.tray_menu.addAction("Show").triggered.connect(self._show)
        self.tray_pause_action = self.tray_menu.addAction("Pause")
        self.tray_pause_action.triggered.connect(self._toggle_pause)
        self.tray_pause_action.setEnabled(False)
        self.tray_menu.addAction("Stop").triggered.connect(self._stop_rec)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("Quit").triggered.connect(self._quit)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(
            lambda r: self._show() if r == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    # ─── hotkeys ──
    def _init_hotkeys(self):
        if not HAS_PYNPUT:
            return
        def on_press(key):
            try:
                if key == pynput_kb.Key.f9:
                    QTimer.singleShot(0, self._toggle_rec)
                elif key == pynput_kb.Key.f10:
                    QTimer.singleShot(0, self._toggle_pause)
                elif key == pynput_kb.Key.f11:
                    QTimer.singleShot(0, self._screenshot)
                elif key == pynput_kb.Key.f12:
                    QTimer.singleShot(0, self._convert_to_gif)
            except Exception as e:
                log.warning(f"Hotkey handler error: {e}")
        try:
            l = pynput_kb.Listener(on_press=on_press)
            l.daemon = True
            l.start()
            log.info("Hotkey listener started (F9/F10/F11/F12)")
        except Exception as e:
            log.warning(f"Could not start hotkey listener: {e}")

    # ─── settings persistence ──
    def _load_settings(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE) as f:
                    c = json.load(f)
                self.fps_spin.setValue(c.get("fps", 30))
                self.quality_slider.setValue(c.get("quality", 80))
                self.codec_combo.setCurrentIndex(c.get("codec", 0))
                self.folder_lbl.setText(c.get("output", OUTPUT_DIR))
                self.monitor_combo.setCurrentIndex(c.get("monitor", 0))
                self.audio_check.setChecked(c.get("audio", True))
                self.webcam_check.setChecked(c.get("webcam", False))
                self.webcam_size_slider.setValue(c.get("webcam_size", 25))
                self.webcam_pos_combo.setCurrentIndex(c.get("webcam_pos", 0))
                self.draw_check.setChecked(c.get("draw", False))
                self.delay_spin.setValue(c.get("delay", 0))
                self.cursor_check.setChecked(c.get("cursor_highlight", False))
                self.gif_fps_spin.setValue(c.get("gif_fps", 10))
                self.gif_width_spin.setValue(c.get("gif_width", 480))
                log.info("Settings loaded")
        except json.JSONDecodeError:
            log.warning("Settings file corrupted, using defaults")
        except Exception as e:
            log.warning(f"Could not load settings: {e}")

    def _save_settings(self):
        c = {
            "fps": self.fps_spin.value(),
            "quality": self.quality_slider.value(),
            "codec": self.codec_combo.currentIndex(),
            "output": self.folder_lbl.text(),
            "monitor": self.monitor_combo.currentIndex(),
            "audio": self.audio_check.isChecked(),
            "webcam": self.webcam_check.isChecked(),
            "webcam_size": self.webcam_size_slider.value(),
            "webcam_pos": self.webcam_pos_combo.currentIndex(),
            "draw": self.draw_check.isChecked(),
            "delay": self.delay_spin.value(),
            "cursor_highlight": self.cursor_check.isChecked(),
            "gif_fps": self.gif_fps_spin.value(),
            "gif_width": self.gif_width_spin.value(),
        }
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(c, f)
        except Exception as e:
            log.warning(f"Could not save settings: {e}")

    # ─── codec ──
    def _codec_info(self):
        """Return (opencv_fourcc, extension) for the selected format.
        When FFmpeg is available, the actual encoding uses FFmpeg's libx264.
        The opencv fallback codec is only used when FFmpeg is not available.
        """
        i = self.codec_combo.currentIndex()
        if i == 0:
            return "mp4v", ".mp4"
        elif i == 1:
            return "MJPG", ".avi"
        return "mp4v", ".mkv"

    def _make_path(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        _, ext = self._codec_info()
        return os.path.join(self.folder_lbl.text(), f"recording_{ts}{ext}")

    # ─── drawing tools ──
    def _select_draw_tool(self, name):
        for k, b in self.draw_tools.items():
            b.setChecked(k == name)
        if self.draw_overlay:
            self.draw_overlay.activate_tool(name)

    def _pick_color(self):
        c = QColorDialog.getColor(self.draw_color, self)
        if c.isValid():
            self.draw_color = c
            if self.draw_overlay:
                self.draw_overlay.current_color = c
            self._update_color_btn()

    def _update_color_btn(self):
        self.color_btn.setStyleSheet(
            f"background: {self.draw_color.name()}; border: 2px solid #555; border-radius: 6px;")

    # ─── recording ──
    def _toggle_rec(self):
        # Check all non-IDLE states (STARTING, RECORDING, PAUSED, STOPPING, FINALIZING)
        if self.engine.state == RecordingState.IDLE:
            self._start_rec()
        elif self.engine.state in (RecordingState.RECORDING, RecordingState.PAUSED, RecordingState.STARTING):
            self._stop_rec()

    def _start_rec(self):
        path = self._make_path()
        # engine settings
        if self.region_combo.currentIndex() == 1 and self.selected_region:
            self.engine.region = self.selected_region
        else:
            self.engine.region = None
        self.engine.monitor_index = self.monitor_combo.currentIndex() + 1
        self.engine.fps = self.fps_spin.value()
        self.engine.quality = self.quality_slider.value()
        codec, _ = self._codec_info()
        self.engine.codec = codec
        self.engine.ext = _
        self.engine.audio_enabled = self.audio_check.isChecked()
        if self.audio_check.isChecked() and self.audio_devices:
            self.engine.audio_device_index = self.audio_combo.currentData()
        self.engine.webcam_enabled = self.webcam_check.isChecked()
        if self.webcam_list:
            self.engine.webcam_index = self.webcam_combo.currentData()
        pos_map = {"Bottom-Right": "bottom-right", "Top-Right": "top-right",
                   "Top-Left": "top-left", "Bottom-Left": "bottom-left"}
        self.engine.webcam_pos = pos_map.get(self.webcam_pos_combo.currentText(), "bottom-right")
        self.engine.webcam_scale = self.webcam_size_slider.value() / 100.0
        self.engine.cursor_highlight = self.cursor_check.isChecked()

        # drawing overlay
        if self.draw_check.isChecked():
            self.draw_overlay = DrawingOverlay(self)
            self.draw_overlay.current_color = self.draw_color
            self.draw_overlay.pen_width = self.pen_width_slider.value()
            self.engine.draw_overlay = self.draw_overlay
        else:
            self.engine.draw_overlay = None

        self._pending_path = path

        # countdown
        delay = self.delay_spin.value()
        if delay > 0:
            self.countdown = CountdownOverlay()
            self.countdown.countdown_done.connect(self._on_countdown_done)
            self.countdown.start()
        else:
            self._actually_start_recording()

    def _on_countdown_done(self):
        self._actually_start_recording()

    def _actually_start_recording(self):
        path = self._pending_path
        if self.engine.start(path):
            self.record_btn.setText("⏹  Stop")
            self.record_btn.setStyleSheet(
                "QPushButton { background: #555; color: white; border: none; border-radius: 10px;"
                " padding: 8px 18px; font-weight: bold; font-size: 11pt; }"
                "QPushButton:hover { background: #666; }")
            self.pause_btn.setEnabled(True)
            self.tray_pause_action.setEnabled(True)
            self.status_lbl.setText("● Recording...")
            self.status_lbl.setStyleSheet("color: #e74c3c; font-weight: bold;")
            self.setWindowOpacity(0.85)
            self._lock_settings(True)

            # floating control bar
            if self.draw_overlay:
                self.draw_overlay.start_overlay()
            self.floating_bar = FloatingControlBar()
            self.floating_bar.sig_stop.connect(self._stop_rec)
            self.floating_bar.sig_pause.connect(self._toggle_pause)
            self.floating_bar.sig_draw.connect(self._toggle_draw_from_float)
            self.signals.timer_tick.connect(self.floating_bar.update_timer)
            screen = QApplication.primaryScreen().geometry()
            self.floating_bar.move(screen.width() // 2 - 160, 10)
            self.floating_bar.show()

    def _toggle_draw_from_float(self):
        if self.draw_overlay and self.draw_overlay.drawing_visible:
            self.draw_overlay.stop_overlay()
        elif self.draw_overlay:
            self.draw_overlay.start_overlay()

    def _stop_rec(self):
        if self.engine.state in (RecordingState.IDLE, RecordingState.STOPPING, RecordingState.FINALIZING):
            return
        self.engine.stop()
        if self.draw_overlay:
            self.draw_overlay.stop_overlay()
            self.draw_overlay = None
        if self.floating_bar:
            try:
                self.signals.timer_tick.disconnect(self.floating_bar.update_timer)
            except (TypeError, RuntimeError):
                pass  # Signal not connected or already disconnected
            self.floating_bar.close()
            self.floating_bar = None
        self.record_btn.setText("⏺  Record")
        self.record_btn.setStyleSheet(
            "QPushButton { background: #e74c3c; color: white; border: none; border-radius: 10px;"
            " padding: 8px 18px; font-weight: bold; font-size: 11pt; }"
            "QPushButton:hover { background: #c0392b; }"
            "QPushButton:disabled { background: #333; color: #666; }")
        self.pause_btn.setEnabled(False)
        self.tray_pause_action.setEnabled(False)
        self.pause_btn.setText("⏸  Pause")
        self.status_lbl.setText("● Processing...")
        self.status_lbl.setStyleSheet("color: #f39c12;")
        self.setWindowOpacity(1.0)
        self._lock_settings(False)

    def _toggle_pause(self):
        if self.engine.state == RecordingState.RECORDING:
            self.engine.pause()
            self.pause_btn.setText("▶  Resume")
            self.status_lbl.setText("● Paused")
            self.status_lbl.setStyleSheet("color: #f39c12;")
        elif self.engine.state == RecordingState.PAUSED:
            self.engine.resume()
            self.pause_btn.setText("⏸  Pause")
            self.status_lbl.setText("● Recording...")
            self.status_lbl.setStyleSheet("color: #e74c3c; font-weight: bold;")

    def _lock_settings(self, lock):
        for w in [self.monitor_combo, self.region_combo, self.fps_spin,
                  self.quality_slider, self.codec_combo, self.audio_check,
                  self.webcam_check, self.draw_check, self.delay_spin,
                  self.cursor_check]:
            w.setEnabled(not lock)

    # ─── screenshot ──
    def _screenshot(self):
        if not HAS_MSS:
            return
        try:
            with mss.mss() as sct:
                mon = sct.monitors[min(self.monitor_combo.currentIndex() + 1,
                                       len(sct.monitors) - 1)]
                img = sct.grab(mon)
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                p = os.path.join(self.folder_lbl.text(), f"screenshot_{ts}.png")
                os.makedirs(os.path.dirname(p), exist_ok=True)
                mss.tools.to_png(img.rgb, img.size, output=p)
                self.tray.showMessage("Screenshot Saved", p, QSystemTrayIcon.Information, 2000)
                self._refresh_history()
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

    # ─── region ──
    def _on_region_changed(self, idx):
        if idx == 1:
            if self.region_selector is None:
                self.region_selector = RegionSelector()
                self.region_selector.region_selected.connect(self._on_region_sel)
                self.region_selector.cancelled.connect(
                    lambda: self.region_combo.setCurrentIndex(0))
            self.region_selector.start_overlay()

    def _on_region_sel(self, x, y, w, h):
        self.selected_region = (x, y, w, h)
        self.status_lbl.setText(f"● Region: {w}x{h}")

    # ─── callbacks ──
    def _on_tick(self, t):
        self.timer_lbl.setText(t)

    def _on_finished(self, path):
        log.info(f"Recording finished: {path}")
        self.status_lbl.setText("● Ready")
        self.status_lbl.setStyleSheet("color: #4CAF50;")
        self.timer_lbl.setText("00:00:00")
        if path and os.path.exists(path):
            sz = os.path.getsize(path)
            sz_str = f"{sz // 1048576} MB" if sz >= 1048576 else f"{sz // 1024} KB"
            dur = get_video_duration(path)
            dur_str = f"  •  {int(dur//60)}:{int(dur%60):02d}" if dur > 0 else ""
            self.tray.showMessage("Recording Saved", f"{os.path.basename(path)}\n{sz_str}{dur_str}",
                                  QSystemTrayIcon.Information, 3000)
        self._update_file_count()
        self._refresh_history()

    def _on_error(self, msg):
        log.error(f"Engine error: {msg}")
        self.status_lbl.setText(f"● {msg[:80]}")
        self.status_lbl.setStyleSheet("color: #e74c3c;")
        self.tray.showMessage("Recording Error", msg, QSystemTrayIcon.Warning, 3000)
        # Only call _stop_rec if we're not already stopped
        if self.engine.state != RecordingState.IDLE:
            self._stop_rec()
        # Reset UI if not already handled
        if self.engine.state == RecordingState.IDLE:
            self.timer_lbl.setText("00:00:00")
            self.record_btn.setText("⏺  Record")
            self.record_btn.setStyleSheet(
                "QPushButton { background: #e74c3c; color: white; border: none; border-radius: 10px;"
                " padding: 8px 18px; font-weight: bold; font-size: 11pt; }"
                "QPushButton:hover { background: #c0392b; }"
                "QPushButton:disabled { background: #333; color: #666; }")
            self.pause_btn.setEnabled(False)
            self.tray_pause_action.setEnabled(False)
            self.setWindowOpacity(1.0)
            self._lock_settings(False)

    # ─── GIF ──
    def _browse_gif_source(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video for GIF", self.folder_lbl.text(),
            "Video Files (*.mp4 *.avi *.mkv);;All Files (*)")
        if path:
            self._gif_source = path
            self.gif_file_lbl.setText(os.path.basename(path))

    def _convert_to_gif(self):
        source = getattr(self, '_gif_source', None)
        if not source or not os.path.exists(source):
            # try selected history item
            item = self.history_list.currentItem()
            if item:
                source = item.data(Qt.UserRole)
            if not source or not os.path.exists(source):
                QMessageBox.information(self, "GIF Export", "Select a video file first.\n\nDouble-click History or use Browse Video.")
                return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(self.folder_lbl.text(), f"animation_{ts}.gif")
        self.gif_status.setText("⏳ Converting... please wait")
        self.gif_convert_btn.setEnabled(False)
        QApplication.processEvents()

        fps = self.gif_fps_spin.value()
        max_w = self.gif_width_spin.value()

        def do_convert():
            result = convert_to_gif(source, out, fps=fps, max_width=max_w)
            QTimer.singleShot(0, lambda: self._gif_done(result, out))

        threading.Thread(target=do_convert, daemon=True).start()

    def _gif_done(self, success, path):
        self.gif_convert_btn.setEnabled(True)
        if success:
            sz = os.path.getsize(path) if os.path.exists(path) else 0
            sz_str = f"{sz // 1048576} MB" if sz >= 1048576 else f"{sz // 1024} KB"
            self.gif_status.setText(f"✅ Saved: {os.path.basename(path)} ({sz_str})")
            self.tray.showMessage("GIF Saved", path, QSystemTrayIcon.Information, 2000)
            self._refresh_history()
        else:
            self.gif_status.setText("❌ Conversion failed. Install Pillow: pip install Pillow")

    # ─── history ──
    def _refresh_history(self):
        self.history_list.clear()
        d = self.folder_lbl.text()
        if not os.path.isdir(d):
            return
        files = sorted(Path(d).glob("*.*"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files:
            if f.suffix.lower() in (".mp4", ".avi", ".mkv", ".png", ".gif", ".wav"):
                sz = f.stat().st_size
                dt = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                sz_str = f"{sz // 1048576} MB" if sz >= 1048576 else f"{sz // 1024} KB"
                dur_str = ""
                if f.suffix.lower() in (".mp4", ".avi", ".mkv"):
                    dur = get_video_duration(str(f))
                    if dur > 0:
                        dur_str = f"  •  {int(dur//60)}:{int(dur%60):02d}"
                icon = "🎬" if f.suffix.lower() in (".mp4", ".avi", ".mkv") else \
                       "🎞" if f.suffix.lower() == ".gif" else \
                       "📸" if f.suffix.lower() == ".png" else "🔊"
                item = QListWidgetItem(f"{icon}  {f.name}  •  {sz_str}{dur_str}  •  {dt}")
                item.setData(Qt.UserRole, str(f))
                self.history_list.addItem(item)

    def _play_selected(self):
        item = self.history_list.currentItem()
        if item:
            path = item.data(Qt.UserRole)
            if path and os.path.exists(path):
                os.startfile(path)

    def _play_file(self, item):
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            os.startfile(path)

    def _delete_selected(self):
        item = self.history_list.currentItem()
        if not item:
            return
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            r = QMessageBox.question(self, "Delete File",
                                     f"Delete {os.path.basename(path)}?",
                                     QMessageBox.Yes | QMessageBox.No)
            if r == QMessageBox.Yes:
                try:
                    os.remove(path)
                    self._refresh_history()
                    self._update_file_count()
                except Exception as e:
                    QMessageBox.warning(self, "Error", str(e))

    def _open_output_folder(self):
        d = self.folder_lbl.text()
        if os.path.isdir(d):
            os.startfile(d)

    def _update_file_count(self):
        d = self.folder_lbl.text()
        if os.path.isdir(d):
            n = len([f for f in os.listdir(d) if f.endswith((".mp4", ".avi", ".mkv"))])
            g = len([f for f in os.listdir(d) if f.endswith(".gif")])
            parts = []
            if n:
                parts.append(f"{n} recording{'s' if n != 1 else ''}")
            if g:
                parts.append(f"{g} GIF{'s' if g != 1 else ''}")
            self.file_count_lbl.setText(", ".join(parts) + " saved" if parts else "")
        else:
            self.file_count_lbl.setText("")

    # ─── misc ──
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Output Folder", self.folder_lbl.text())
        if d:
            self.folder_lbl.setText(d)
            self._update_file_count()
            self._refresh_history()

    def _center(self):
        g = QApplication.primaryScreen().geometry()
        s = self.geometry()
        self.move((g.width() - s.width()) // 2, (g.height() - s.height()) // 2)

    def _show(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _quit(self):
        if self.engine.state not in (RecordingState.IDLE, RecordingState.FINALIZING):
            self.engine.stop()
            # Wait briefly for cleanup
            time.sleep(0.5)
        if self.floating_bar:
            self.floating_bar.close()
        self._save_settings()
        QApplication.quit()

    def closeEvent(self, e):
        if self.engine.state not in (RecordingState.IDLE, RecordingState.FINALIZING):
            r = QMessageBox.question(self, "Recording Active",
                                     "Stop recording and quit?", QMessageBox.Yes | QMessageBox.No)
            if r == QMessageBox.Yes:
                self._stop_rec()
                e.accept()
            else:
                e.ignore()
        else:
            self._save_settings()
            e.accept()

    def changeEvent(self, e):
        if e.type() == e.WindowStateChange and self.isMinimized():
            self.hide()
            self.tray.showMessage(APP_NAME, "Minimized to tray", QSystemTrayIcon.Information, 1500)


class RegionSelector(QWidget):
    region_selected = pyqtSignal(int, int, int, int)
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self._start = None
        self._end = None
        self._dragging = False

    def start_overlay(self):
        g = QApplication.primaryScreen().geometry()
        self.setGeometry(g)
        self._start = None
        self._end = None
        self.showFullScreen()
        self.raise_()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if self._start and self._end:
            r = QRect(self._start, self._end).normalized()
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(r, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(0, 174, 255), 3))
            p.drawRect(r)
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Segoe UI", 12, QFont.Bold))
            p.drawText(r.adjusted(0, -28, 0, 0), Qt.AlignBottom | Qt.AlignHCenter,
                       f"{r.width()} x {r.height()}")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._start = e.pos()
            self._end = e.pos()
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._end = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self._end = e.pos()
            r = QRect(self._start, self._end).normalized()
            if r.width() > 10 and r.height() > 10:
                self.hide()
                self.region_selected.emit(r.x(), r.y(), r.width(), r.height())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
            self.cancelled.emit()


def main():
    if not HAS_PYQT5:
        print("ERROR: PyQt5 required. pip install PyQt5")
        sys.exit(1)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
