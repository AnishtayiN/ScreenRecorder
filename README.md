# 🎬 Screen Recorder

A cross-platform screen recording application for **Windows** and **Android**.

![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Android-blue)
![Windows](https://img.shields.io/badge/Windows-7%20to%2011-brightgreen)
![Android](https://img.shields.io/badge/Android-7.0%2B-brightgreen)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ Features

### Windows
- 🖥️ Full screen & custom region recording
- ⏸ Pause/Resume recording
- 📷 Built-in screenshot capture
- ⌨ Global hotkeys (F9/F10/F11)
- 🎚 Configurable FPS (10-120), quality, and format
- 📁 Multiple output formats (MP4, AVI, MKV)
- 🔔 System tray integration with minimize support
- 🎨 Modern dark UI

### Android
- 📱 Full screen recording with MediaProjection API
- ⏸ Pause/Resume via notification
- 🎤 Audio recording option (microphone)
- 👆 Show touch points option
- 📊 Multiple resolution presets (SD, HD, Full HD, Auto)
- 🎚 Configurable frame rate (15/24/30/60 FPS)
- 🔔 Persistent notification with stop control
- 🎨 Material Design dark theme

## 📥 Download

### Windows
1. Go to [Releases](https://github.com/AnishtayiN/ScreenRecorder/releases)
2. Download `ScreenRecorder.exe`
3. Run directly — no installation needed

### Android
1. Go to [Releases](https://github.com/AnishtayiN/ScreenRecorder/releases)
2. Download `app-debug.apk`
3. Enable "Install from Unknown Sources" in your device settings
4. Install and open

## ⌨ Hotkeys (Windows)

| Key | Action |
|-----|--------|
| F9 | Start / Stop recording |
| F10 | Pause / Resume |
| F11 | Take screenshot |

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

### Android
- Android 7.0 (API 24) or later
- Screen recording permission

## 🏗 Tech Stack

| Component | Technology |
|-----------|-----------|
| Windows UI | Python + PyQt5 |
| Windows Capture | mss + OpenCV |
| Android UI | Kotlin + Material Design |
| Android Capture | MediaProjection + MediaRecorder |
| CI/CD | GitHub Actions |

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.
