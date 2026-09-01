# 🎬 Screen Recorder Pro v2.0

A cross-platform screen recording application for **Windows** and **Android**.

![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Android-blue)
![Windows](https://img.shields.io/badge/Windows-7%20to%2011-brightgreen)
![Android](https://img.shields.io/badge/Android-7.0%2B-brightgreen)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ Features

### Windows (v2.0)
- 🖥️ Full screen & custom region recording
- 📸 Multi-monitor selection
- 📷 **Webcam PiP overlay** (position & size adjustable)
- 🎤 **Audio recording** with device selection
- 🎬 **Audio + Video muxing** into single file via FFmpeg (when available)
- ✏️ **Screen drawing tools** (pen, arrow, rectangle, circle, eraser)
- ⏸ Pause/Resume recording
- 📷 Screenshot capture
- ⌨️ Global hotkeys (F9/F10/F11/F12)
- 🎚 Configurable FPS (10-120), quality (CRF via FFmpeg), and format
- 📁 Multiple output formats (MP4, AVI, MKV) with proper codec selection
- 📋 **Recording history** with file details
- 🖱️ **Right-click to undo** drawings
- 🔔 System tray integration with minimize
- 🎨 Modern dark UI with gradient header

### Android (v2.0)
- 📱 Full screen recording with MediaProjection API
- ⏸ Pause/Resume via notification & floating overlay
- 🎤 **Audio recording** option (microphone)
- 🔊 **Internal audio recording** (Android 10+)
- 🤳 **Face cam overlay** toggle
- 👆 Show touch points option
- 🫧 **Floating bubble overlay** with draggable controls
- ⏳ **3-2-1 countdown** before recording starts
- 📂 **Recording gallery** — play, share, delete
- 📊 Resolution presets (SD, HD, Full HD, 2K, Auto)
- 🎚 Configurable FPS (15/24/30/60) and quality
- 📳 **Shake to stop** recording
- 🔔 Persistent notification with pause/resume/stop
- 🎨 Material Design dark theme with gradient header

## 📥 Download

### Windows
1. Go to [Releases](https://github.com/AnishtayiN/ScreenRecorder/releases)
2. Download `ScreenRecorder-Windows-vX.Y.Z.exe`
3. Run directly — no installation needed

### Android
1. Go to [Releases](https://github.com/AnishtayiN/ScreenRecorder/releases)
2. Download `ScreenRecorder-Android-vX.Y.Z-release.apk`
3. Enable "Install from Unknown Sources" in device settings
4. Install and open

## ⚙️ Requirements

### Windows
- Windows 7 / 8 / 8.1 / 10 / 11
- Python 3.8+ (for building from source)
- Optional: [FFmpeg](https://ffmpeg.org/) — enables audio+video muxing into a single MP4 file. Without FFmpeg, audio is saved as a separate WAV file.
- Optional: Webcam for PiP, Microphone for audio

### Android
- Android 7.0 (API 24) or later
- Screen recording permission
- Overlay permission (for floating controls)
- Camera permission (for face cam, optional)

## ⌨️ Hotkeys (Windows)

| Key | Action |
|-----|--------|
| F9 | Start / Stop recording |
| F10 | Pause / Resume |
| F11 | Take screenshot |
| F12 | Export to GIF |

## 🖱️ Drawing Tools (Windows)

| Tool | Action |
|------|--------|
| ✏ Pen | Freehand drawing |
| ➤ Arrow | Draw arrow |
| ▭ Rectangle | Draw rectangle |
| ○ Circle | Draw circle |
| ⌫ Eraser | Erase strokes |
| Right-click | Undo last stroke |
| Esc | Close overlay |

## 🛠 Build from Source

### Windows (Python)
```bash
cd windows
pip install -r requirements.txt

# Optional: Install FFmpeg for audio+video muxing
# Download from https://ffmpeg.org/download.html

# Build EXE
pip install pyinstaller
pyinstaller --onefile --noconsole --name ScreenRecorder screen_recorder.py
```

### Android (Gradle)
```bash
cd android
./gradlew assembleRelease
```

## 🧪 Running Tests

```bash
python -m unittest tests.test_windows -v
```

## 🎬 Audio + Video (Windows)

When **FFmpeg** is installed and on PATH:
- Audio and video are recorded simultaneously
- FFmpeg muxes them into a single synchronized MP4/MKV/AVI file
- Quality slider maps to CRF values (lower CRF = higher quality)
- Temporary files are automatically cleaned up

When FFmpeg is **not** installed:
- Video is recorded via OpenCV VideoWriter
- Audio is saved as a separate WAV file
- A warning is shown in the UI

## 🏗 Tech Stack

| Component | Technology |
|-----------|-----------|
| Windows UI | Python + PyQt5 |
| Windows Capture | mss + OpenCV |
| Windows Encoding | FFmpeg (preferred) / OpenCV (fallback) |
| Windows Audio | PyAudio |
| Android UI | Kotlin + Material Design |
| Android Capture | MediaProjection + MediaRecorder |
| Android Audio | AudioRecord (internal) + MediaRecorder (mic) |
| CI/CD | GitHub Actions |

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 👤 Developer

- **Telegram**: [@AnishtayiN](https://t.me/AnishtayiN)
- **GitHub**: [github.com/AnishtayiN](https://github.com/AnishtayiN)
- ⭐ [Star this project](https://github.com/AnishtayiN/ScreenRecorder)
