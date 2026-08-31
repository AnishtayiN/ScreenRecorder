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
- ✏️ **Screen drawing tools** (pen, arrow, rectangle, circle, eraser)
- ⏸ Pause/Resume recording
- 📷 Screenshot capture
- ⌨ Global hotkeys (F9/F10/F11)
- 🎚 Configurable FPS (10-120), quality, and format
- 📁 Multiple output formats (MP4, AVI, MKV)
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
2. Download `ScreenRecorder.exe`
3. Run directly — no installation needed

### Android
1. Go to [Releases](https://github.com/AnishtayiN/ScreenRecorder/releases)
2. Download `app-debug.apk`
3. Enable "Install from Unknown Sources" in device settings
4. Install and open

## ⌨ Hotkeys (Windows)

| Key | Action |
|-----|--------|
| F9 | Start / Stop recording |
| F10 | Pause / Resume |
| F11 | Take screenshot |

## 🖱 Drawing Tools (Windows)

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
pip install pyinstaller
pyinstaller --onefile --noconsole --name ScreenRecorder screen_recorder.py
```

### Android (Gradle)
```bash
cd android
./gradlew assembleDebug
```

## 📋 Requirements

### Windows
- Windows 7 / 8 / 8.1 / 10 / 11
- Python 3.8+ (for building from source)
- Optional: Webcam for PiP, Microphone for audio

### Android
- Android 7.0 (API 24) or later
- Screen recording permission
- Overlay permission (for floating controls)
- Camera permission (for face cam)

## 🏗 Tech Stack

| Component | Technology |
|-----------|-----------|
| Windows UI | Python + PyQt5 |
| Windows Capture | mss + OpenCV |
| Windows Audio | PyAudio |
| Android UI | Kotlin + Material Design |
| Android Capture | MediaProjection + MediaRecorder |
| Android Audio | AudioRecord (internal) + MediaRecorder (mic) |
| CI/CD | GitHub Actions |

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.
