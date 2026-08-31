package com.screenrecorder

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.provider.Settings
import android.os.Vibrator
import android.view.View
import android.view.animation.AccelerateInterpolator
import android.view.animation.DecelerateInterpolator
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.google.android.material.card.MaterialCardView
import java.io.File
import java.text.SimpleDateFormat
import java.util.*

class MainActivity : AppCompatActivity(), SensorEventListener {

    private lateinit var btnRecord: Button
    private lateinit var btnStop: Button
    private lateinit var btnPause: Button
    private lateinit var tvStatus: TextView
    private lateinit var tvTimer: TextView
    private lateinit var tvPath: TextView
    private lateinit var tvRecordingInfo: TextView
    private lateinit var tvFileCount: TextView
    private lateinit var tvCountdown: TextView
    private lateinit var statusDot: View
    private lateinit var countdownOverlay: FrameLayout
    private lateinit var spinnerResolution: Spinner
    private lateinit var spinnerFps: Spinner
    private lateinit var spinnerQuality: Spinner
    private lateinit var switchAudio: Switch
    private lateinit var switchTouch: Switch
    private lateinit var cardInternalAudio: MaterialCardView
    private lateinit var cardFaceCam: MaterialCardView

    private var isRecording = false
    private var isPaused = false
    private var outputDir: String = ""
    private var timerHandler = Handler(Looper.getMainLooper())
    private var elapsedSeconds = 0

    // Shake detection
    private lateinit var sensorManager: SensorManager
    private var accelerometer: Sensor? = null
    private var shakeThreshold = 12.0f
    private var lastShakeTime = 0L

    // Internal audio (Android 10+)
    private var internalAudioEnabled = false

    // Face cam
    private var faceCamEnabled = false

    private val timerRunnable = object : Runnable {
        override fun run() {
            if (isRecording && !isPaused) {
                elapsedSeconds++
                tvTimer.text = formatTime(elapsedSeconds)
                timerHandler.postDelayed(this, 1000)
            }
        }
    }

    companion object {
        const val REQUEST_MEDIA_PROJECTION = 1001
        const val REQUEST_PERMISSIONS = 1002
        const val REQUEST_OVERLAY = 1003
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        initViews()
        setupSpinners()
        setupOutputDir()
        checkPermissions()
        setupShakeDetection()
        updateFileCount()
    }

    private fun initViews() {
        btnRecord = findViewById(R.id.btnRecord)
        btnStop = findViewById(R.id.btnStop)
        btnPause = findViewById(R.id.btnPause)
        tvStatus = findViewById(R.id.tvStatus)
        tvTimer = findViewById(R.id.tvTimer)
        tvPath = findViewById(R.id.tvPath)
        tvRecordingInfo = findViewById(R.id.tvRecordingInfo)
        tvFileCount = findViewById(R.id.tvFileCount)
        tvCountdown = findViewById(R.id.tvCountdown)
        statusDot = findViewById(R.id.statusDot)
        countdownOverlay = findViewById(R.id.countdownOverlay)
        spinnerResolution = findViewById(R.id.spinnerResolution)
        spinnerFps = findViewById(R.id.spinnerFps)
        spinnerQuality = findViewById(R.id.spinnerQuality)
        switchAudio = findViewById(R.id.switchAudio)
        switchTouch = findViewById(R.id.switchTouch)
        cardInternalAudio = findViewById(R.id.cardInternalAudio)
        cardFaceCam = findViewById(R.id.cardFaceCam)

        btnRecord.setOnClickListener { startRecordingFlow() }
        btnStop.setOnClickListener { stopRecording() }
        btnPause.setOnClickListener { togglePause() }

        cardInternalAudio.setOnClickListener { toggleInternalAudio() }
        cardFaceCam.setOnClickListener { toggleFaceCam() }

        // Gallery button
        findViewById<MaterialCardView>(R.id.cardGallery).setOnClickListener {
            startActivity(Intent(this, RecordingGalleryActivity::class.java))
        }

        // Set initial states
        btnPause.isEnabled = false
        btnStop.isEnabled = false
    }

    private fun setupSpinners() {
        val resolutions = arrayOf(
            "2K (2560×1440)",
            "Full HD (1920×1080)",
            "HD (1280×720)",
            "SD (854×480)",
            "Auto (Screen Size)"
        )
        spinnerResolution.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, resolutions)
        spinnerResolution.setSelection(1)

        val fpsOptions = arrayOf("30 FPS", "60 FPS", "24 FPS", "15 FPS")
        spinnerFps.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, fpsOptions)

        val qualityOptions = arrayOf("High (8 Mbps)", "Medium (5 Mbps)", "Low (2 Mbps)", "Ultra (16 Mbps)")
        spinnerQuality.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, qualityOptions)
    }

    private fun setupOutputDir() {
        val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES), "ScreenRecorder")
        if (!dir.exists()) dir.mkdirs()
        outputDir = dir.absolutePath
        tvPath.text = outputDir
    }

    private fun checkPermissions() {
        val perms = mutableListOf<String>()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            perms.add(Manifest.permission.RECORD_AUDIO)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                perms.add(Manifest.permission.POST_NOTIFICATIONS)
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_VIDEO) != PackageManager.PERMISSION_GRANTED) {
                perms.add(Manifest.permission.READ_MEDIA_VIDEO)
            }
        }
        if (perms.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, perms.toTypedArray(), REQUEST_PERMISSIONS)
        }
    }

    private fun setupShakeDetection() {
        sensorManager = getSystemService(SENSOR_SERVICE) as SensorManager
        accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    }

    override fun onResume() {
        super.onResume()
        accelerometer?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_UI)
        }
        updateFileCount()
    }

    override fun onPause() {
        super.onPause()
        sensorManager.unregisterListener(this)
    }

    override fun onSensorChanged(event: SensorEvent?) {
        if (event?.sensor?.type == Sensor.TYPE_ACCELEROMETER && isRecording) {
            val x = event.values[0]
            val y = event.values[1]
            val z = event.values[2]

            val acceleration = Math.sqrt((x * x + y * y + z * z).toDouble()).toFloat()
            val gravity = SensorManager.GRAVITY_EARTH
            val force = acceleration - gravity

            if (force > shakeThreshold) {
                val now = System.currentTimeMillis()
                if (now - lastShakeTime > 2000) {
                    lastShakeTime = now
                    vibrate()
                    stopRecording()
                }
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    private fun vibrate() {
        val vibrator = getSystemService(Vibrator::class.java)
        if (vibrator != null) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator.vibrate(VibrationEffect.createOneShot(200, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                @Suppress("DEPRECATION")
                vibrator.vibrate(200)
            }
        }
    }

    private fun toggleInternalAudio() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            internalAudioEnabled = !internalAudioEnabled
            if (internalAudioEnabled) {
                cardInternalAudio.strokeColor = ContextCompat.getColor(this, R.color.primary)
                Toast.makeText(this, "Internal audio ON (Android 10+)", Toast.LENGTH_SHORT).show()
            } else {
                cardInternalAudio.strokeColor = ContextCompat.getColor(this, R.color.divider)
                Toast.makeText(this, "Internal audio OFF", Toast.LENGTH_SHORT).show()
            }
        } else {
            Toast.makeText(this, "Internal audio requires Android 10+", Toast.LENGTH_SHORT).show()
        }
    }

    private fun toggleFaceCam() {
        faceCamEnabled = !faceCamEnabled
        if (faceCamEnabled) {
            cardFaceCam.strokeColor = ContextCompat.getColor(this, R.color.primary)
            Toast.makeText(this, "Face cam will appear during recording", Toast.LENGTH_SHORT).show()
        } else {
            cardFaceCam.strokeColor = ContextCompat.getColor(this, R.color.divider)
        }
    }

    private fun startRecordingFlow() {
        // Check overlay permission first
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
            val intent = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION)
            intent.data = android.net.Uri.parse("package:$packageName")
            startActivityForResult(intent, REQUEST_OVERLAY)
            return
        }

        // Start countdown animation
        startCountdown {
            // After countdown, request screen capture
            val projManager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            startActivityForResult(projManager.createScreenCaptureIntent(), REQUEST_MEDIA_PROJECTION)
        }
    }

    private fun startCountdown(onComplete: () -> Unit) {
        countdownOverlay.visibility = View.VISIBLE
        var count = 3
        tvCountdown.text = count.toString()
        tvCountdown.scaleX = 1.5f
        tvCountdown.scaleY = 1.5f
        tvCountdown.alpha = 0f

        val handler = Handler(Looper.getMainLooper())
        val countRunnable = object : Runnable {
            override fun run() {
                if (count > 0) {
                    // Animate in
                    tvCountdown.text = count.toString()
                    tvCountdown.animate()
                        .scaleX(1f).scaleY(1f)
                        .alpha(1f)
                        .setDuration(200)
                        .setInterpolator(DecelerateInterpolator())
                        .withEndAction {
                            // Animate out
                            tvCountdown.animate()
                                .scaleX(0.5f).scaleY(0.5f)
                                .alpha(0f)
                                .setDuration(500)
                                .setInterpolator(AccelerateInterpolator())
                                .start()
                        }
                        .start()

                    // Vibrate on each count
                    vibrate()

                    count--
                    handler.postDelayed(this, 900)
                } else {
                    countdownOverlay.visibility = View.GONE
                    onComplete()
                }
            }
        }
        handler.post(countRunnable)
    }

    private fun stopRecording() {
        isRecording = false
        isPaused = false
        timerHandler.removeCallbacks(timerRunnable)

        val intent = Intent(this, RecordingService::class.java)
        intent.action = RecordingService.ACTION_STOP
        startService(intent)

        // Stop floating overlay
        val floatIntent = Intent(this, FloatingOverlayService::class.java)
        floatIntent.action = FloatingOverlayService.ACTION_STOP
        startService(floatIntent)

        btnRecord.isEnabled = true
        btnRecord.text = "⏺  Start"
        btnStop.isEnabled = false
        btnPause.isEnabled = false
        btnPause.text = "⏸  Pause"
        tvStatus.text = "Ready"
        statusDot.setBackgroundResource(R.drawable.bg_circle_green)
        tvTimer.text = "00:00"
        tvRecordingInfo.visibility = View.GONE

        updateFileCount()
    }

    private fun togglePause() {
        if (isPaused) {
            isPaused = false
            timerHandler.postDelayed(timerRunnable, 1000)
            btnPause.text = "⏸  Pause"
            tvStatus.text = "Recording"
            statusDot.setBackgroundResource(R.drawable.bg_circle_red)
            val intent = Intent(this, RecordingService::class.java)
            intent.action = RecordingService.ACTION_RESUME
            startService(intent)
        } else {
            isPaused = true
            timerHandler.removeCallbacks(timerRunnable)
            btnPause.text = "▶  Resume"
            tvStatus.text = "Paused"
            statusDot.setBackgroundResource(R.drawable.bg_pulse)
            val intent = Intent(this, RecordingService::class.java)
            intent.action = RecordingService.ACTION_PAUSE
            startService(intent)
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_MEDIA_PROJECTION && resultCode == Activity.RESULT_OK && data != null) {
            val serviceIntent = Intent(this, RecordingService::class.java).apply {
                action = RecordingService.ACTION_START
                putExtra("resultCode", resultCode)
                putExtra("data", data)
                putExtra("outputDir", outputDir)
                putExtra("resolution", spinnerResolution.selectedItemPosition)
                putExtra("fps", spinnerFps.selectedItemPosition)
                putExtra("quality", spinnerQuality.selectedItemPosition)
                putExtra("audio", switchAudio.isChecked)
                putExtra("touch", switchTouch.isChecked)
                putExtra("internalAudio", internalAudioEnabled)
                putExtra("faceCam", faceCamEnabled)
            }
            startForegroundService(serviceIntent)

            // Start floating overlay
            val floatIntent = Intent(this, FloatingOverlayService::class.java).apply {
                action = FloatingOverlayService.ACTION_START
            }
            startService(floatIntent)

            isRecording = true
            elapsedSeconds = 0
            timerHandler.postDelayed(timerRunnable, 1000)

            btnRecord.isEnabled = false
            btnRecord.text = "⏺  Recording"
            btnStop.isEnabled = true
            btnPause.isEnabled = true
            tvStatus.text = "Recording"
            statusDot.setBackgroundResource(R.drawable.bg_circle_red)
            statusDot.animate().alpha(0.3f).setDuration(500).withEndAction {
                statusDot.animate().alpha(1f).setDuration(500).start()
            }.start()

            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            tvPath.text = "$outputDir/recording_$timestamp.mp4"
            tvRecordingInfo.visibility = View.VISIBLE

            val resolution = when (spinnerResolution.selectedItemPosition) {
                0 -> "2560×1440"
                1 -> "1920×1080"
                2 -> "1280×720"
                3 -> "854×480"
                else -> "Auto"
            }
            val fps = spinnerFps.selectedItem.toString()
            tvRecordingInfo.text = "📹 $resolution  •  $fps  •  ${spinnerQuality.selectedItem}"
        } else if (requestCode == REQUEST_OVERLAY) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && Settings.canDrawOverlays(this)) {
                startRecordingFlow()
            } else {
                Toast.makeText(this, "Overlay permission required for floating controls", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun updateFileCount() {
        val dir = File(outputDir)
        if (dir.exists()) {
            val count = dir.listFiles { f -> f.name.endsWith(".mp4") }?.size ?: 0
            tvFileCount.text = if (count > 0) "$count recording${if (count != 1) "s" else ""} saved" else ""
        }
    }

    private fun formatTime(seconds: Int): String {
        val h = seconds / 3600
        val m = (seconds % 3600) / 60
        val s = seconds % 60
        return if (h > 0) String.format("%d:%02d:%02d", h, m, s) else String.format("%02d:%02d", m, s)
    }
}
