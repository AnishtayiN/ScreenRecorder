package com.screenrecorder

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.io.File
import java.text.SimpleDateFormat
import java.util.*

class MainActivity : AppCompatActivity() {

    private lateinit var btnRecord: Button
    private lateinit var btnStop: Button
    private lateinit var btnPause: Button
    private lateinit var btnFolder: Button
    private lateinit var tvStatus: TextView
    private lateinit var tvTimer: TextView
    private lateinit var tvPath: TextView
    private lateinit var spinnerResolution: Spinner
    private lateinit var spinnerFps: Spinner
    private lateinit var switchAudio: Switch
    private lateinit var switchTouch: Switch

    private var isRecording = false
    private var isPaused = false
    private var recordingService: Intent? = null
    private var outputDir: String = ""

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
    }

    private fun initViews() {
        btnRecord = findViewById(R.id.btnRecord)
        btnStop = findViewById(R.id.btnStop)
        btnPause = findViewById(R.id.btnPause)
        btnFolder = findViewById(R.id.btnFolder)
        tvStatus = findViewById(R.id.tvStatus)
        tvTimer = findViewById(R.id.tvTimer)
        tvPath = findViewById(R.id.tvPath)
        spinnerResolution = findViewById(R.id.spinnerResolution)
        spinnerFps = findViewById(R.id.spinnerFps)
        switchAudio = findViewById(R.id.switchAudio)
        switchTouch = findViewById(R.id.switchTouch)

        btnRecord.setOnClickListener { startRecording() }
        btnStop.setOnClickListener { stopRecording() }
        btnPause.setOnClickListener { togglePause() }
        btnFolder.setOnClickListener { selectFolder() }

        btnStop.isEnabled = false
        btnPause.isEnabled = false
    }

    private fun setupSpinners() {
        val resolutions = arrayOf("1920x1080 (Full HD)", "1280x720 (HD)", "854x480 (SD)", "Auto (Screen Size)")
        spinnerResolution.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, resolutions)

        val fpsOptions = arrayOf("30 FPS", "24 FPS", "60 FPS", "15 FPS")
        spinnerFps.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, fpsOptions)
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

    private fun startRecording() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
            val intent = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION)
            intent.data = android.net.Uri.parse("package:$packageName")
            startActivityForResult(intent, REQUEST_OVERLAY)
            return
        }

        val projManager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        startActivityForResult(projManager.createScreenCaptureIntent(), REQUEST_MEDIA_PROJECTION)
    }

    private fun stopRecording() {
        isRecording = false
        isPaused = false
        val intent = Intent(this, RecordingService::class.java)
        intent.action = RecordingService.ACTION_STOP
        startService(intent)

        btnRecord.isEnabled = true
        btnRecord.text = "⏺ Start Recording"
        btnStop.isEnabled = false
        btnPause.isEnabled = false
        btnPause.text = "⏸ Pause"
        tvStatus.text = "● Ready"
        tvStatus.setTextColor(ContextCompat.getColor(this, R.color.status_ready))
        tvTimer.text = "00:00:00"
    }

    private fun togglePause() {
        if (isPaused) {
            isPaused = false
            btnPause.text = "⏸ Pause"
            tvStatus.text = "● Recording..."
            tvStatus.setTextColor(ContextCompat.getColor(this, R.color.status_recording))
            val intent = Intent(this, RecordingService::class.java)
            intent.action = RecordingService.ACTION_RESUME
            startService(intent)
        } else {
            isPaused = true
            btnPause.text = "▶ Resume"
            tvStatus.text = "● Paused"
            tvStatus.setTextColor(ContextCompat.getColor(this, R.color.status_paused))
            val intent = Intent(this, RecordingService::class.java)
            intent.action = RecordingService.ACTION_PAUSE
            startService(intent)
        }
    }

    private fun selectFolder() {
        Toast.makeText(this, "Default: $outputDir", Toast.LENGTH_SHORT).show()
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
                putExtra("audio", switchAudio.isChecked)
                putExtra("touch", switchTouch.isChecked)
            }
            startForegroundService(serviceIntent)

            isRecording = true
            btnRecord.isEnabled = false
            btnStop.isEnabled = true
            btnPause.isEnabled = true
            tvStatus.text = "● Recording..."
            tvStatus.setTextColor(ContextCompat.getColor(this, R.color.status_recording))

            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            tvPath.text = "$outputDir/recording_$timestamp.mp4"
        }
    }
}
