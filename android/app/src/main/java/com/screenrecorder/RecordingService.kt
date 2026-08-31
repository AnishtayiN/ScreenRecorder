package com.screenrecorder

import android.app.*
import android.content.Context
import android.content.Intent
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.MediaRecorder
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import java.io.File
import java.text.SimpleDateFormat
import java.util.*

class RecordingService : Service() {

    companion object {
        const val ACTION_START = "com.screenrecorder.START"
        const val ACTION_STOP = "com.screenrecorder.STOP"
        const val ACTION_PAUSE = "com.screenrecorder.PAUSE"
        const val ACTION_RESUME = "com.screenrecorder.RESUME"
        const val CHANNEL_ID = "screen_recorder_channel"
        const val NOTIFICATION_ID = 1
    }

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var mediaRecorder: MediaRecorder? = null
    private var outputFile: String = ""
    private var isRecording = false

    private var width = 1920
    private var height = 1080
    private var fps = 30
    private var bitrate = 8000000

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                startForeground(NOTIFICATION_ID, buildNotification("Starting..."))
                startRecording(intent)
            }
            ACTION_STOP -> {
                stopRecording()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
            ACTION_PAUSE -> {
                pauseRecording()
                updateNotification("Paused ⏸")
            }
            ACTION_RESUME -> {
                resumeRecording()
                updateNotification("Recording ●")
            }
        }
        return START_NOT_STICKY
    }

    private fun startRecording(intent: Intent) {
        try {
            val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
            val metrics = DisplayMetrics()
            @Suppress("DEPRECATION")
            wm.defaultDisplay.getRealMetrics(metrics)

            // Resolution
            when (intent.getIntExtra("resolution", 1)) {
                0 -> { width = 2560; height = 1440 }
                1 -> { width = 1920; height = 1080 }
                2 -> { width = 1280; height = 720 }
                3 -> { width = 854; height = 480 }
                4 -> { width = metrics.widthPixels; height = metrics.heightPixels }
            }

            // Ensure even dimensions
            width = width and 0x7FFFFFFE.toInt()
            height = height and 0x7FFFFFFE.toInt()

            // FPS and quality
            when (intent.getIntExtra("fps", 0)) {
                0 -> fps = 30
                1 -> fps = 60
                2 -> fps = 24
                3 -> fps = 15
            }

            when (intent.getIntExtra("quality", 0)) {
                0 -> bitrate = 8000000   // High
                1 -> bitrate = 5000000   // Medium
                2 -> bitrate = 2000000   // Low
                3 -> bitrate = 16000000  // Ultra
            }

            // Output
            val outputDir = intent.getStringExtra("outputDir") ?: "${getExternalFilesDir(null)}/ScreenRecorder"
            File(outputDir).mkdirs()
            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            outputFile = "$outputDir/recording_$timestamp.mp4"

            // MediaRecorder setup
            mediaRecorder = MediaRecorder()

            mediaRecorder!!.apply {
                setVideoSource(MediaRecorder.VideoSource.SURFACE)

                val hasAudio = intent.getBooleanExtra("audio", false)
                val hasInternalAudio = intent.getBooleanExtra("internalAudio", false) && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q

                if (hasAudio || hasInternalAudio) {
                    setAudioSource(MediaRecorder.AudioSource.MIC)
                    setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                    setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                    setAudioSamplingRate(44100)
                    setAudioEncodingBitRate(128000)
                } else {
                    setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                }

                setVideoEncoder(MediaRecorder.VideoEncoder.H264)
                setVideoSize(width, height)
                setVideoFrameRate(fps)
                setVideoEncodingBitRate(bitrate)
                setOutputFile(outputFile)
                prepare()
            }

            // MediaProjection
            val resultCode = intent.getIntExtra("resultCode", Activity.RESULT_CANCELED)
            @Suppress("DEPRECATION")
            val data = intent.getParcelableExtra<Intent>("data")

            val projManager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            mediaProjection = projManager.getMediaProjection(resultCode, data!!)

            mediaProjection?.registerCallback(object : MediaProjection.Callback() {
                override fun onStop() {
                    if (isRecording) stopRecording()
                }
            }, null)

            virtualDisplay = mediaProjection?.createVirtualDisplay(
                "ScreenRecorder",
                width, height, metrics.densityDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                mediaRecorder!!.surface,
                null, null
            )

            mediaRecorder!!.start()
            isRecording = true

            updateNotification("Recording ●")

        } catch (e: Exception) {
            Log.e("ScreenRecorder", "Start recording failed", e)
            stopSelf()
        }
    }

    private fun stopRecording() {
        try {
            isRecording = false
            mediaRecorder?.apply {
                stop()
                release()
            }
            mediaRecorder = null
            virtualDisplay?.release()
            virtualDisplay = null
            mediaProjection?.stop()
            mediaProjection = null
        } catch (e: Exception) {
            Log.e("ScreenRecorder", "Stop recording failed", e)
        }
    }

    private fun pauseRecording() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            mediaRecorder?.pause()
        }
    }

    private fun resumeRecording() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            mediaRecorder?.resume()
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Screen Recording",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Shows recording status and controls"
                setShowBadge(false)
            }
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        // Stop action
        val stopIntent = Intent(this, RecordingService::class.java).apply { action = ACTION_STOP }
        val stopPending = PendingIntent.getService(
            this, 0, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // Pause action
        val pauseIntent = Intent(this, RecordingService::class.java).apply { action = ACTION_PAUSE }
        val pausePending = PendingIntent.getService(
            this, 1, pauseIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // Resume action
        val resumeIntent = Intent(this, RecordingService::class.java).apply { action = ACTION_RESUME }
        val resumePending = PendingIntent.getService(
            this, 2, resumeIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // Open app
        val openIntent = Intent(this, MainActivity::class.java)
        val openPending = PendingIntent.getActivity(
            this, 0, openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Screen Recorder")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_record)
            .setContentIntent(openPending)
            .setOngoing(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .addAction(R.drawable.ic_record, "Stop", stopPending)

        if (isRecording) {
            builder.addAction(R.drawable.ic_pause, "Pause", pausePending)
        } else if (text.contains("Paused")) {
            builder.addAction(R.drawable.ic_record, "Resume", resumePending)
        }

        return builder.build()
    }

    private fun updateNotification(text: String) {
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(NOTIFICATION_ID, buildNotification(text))
    }

    override fun onDestroy() {
        if (isRecording) stopRecording()
        super.onDestroy()
    }
}
