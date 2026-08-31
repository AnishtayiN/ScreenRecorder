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
                startForeground(NOTIFICATION_ID, buildNotification("Recording..."))
                startRecording(intent)
            }
            ACTION_STOP -> {
                stopRecording()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
            ACTION_PAUSE -> {
                pauseRecording()
                updateNotification("Paused")
            }
            ACTION_RESUME -> {
                resumeRecording()
                updateNotification("Recording...")
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

            when (intent.getIntExtra("resolution", 0)) {
                0 -> { width = 1920; height = 1080 }
                1 -> { width = 1280; height = 720 }
                2 -> { width = 854; height = 480 }
                3 -> { width = metrics.widthPixels; height = metrics.heightPixels }
            }

            width = width and 0x7FFFFFFE.toInt()
            height = height and 0x7FFFFFFE.toInt()

            when (intent.getIntExtra("fps", 0)) {
                0 -> { fps = 30; bitrate = 8000000 }
                1 -> { fps = 24; bitrate = 6000000 }
                2 -> { fps = 60; bitrate = 16000000 }
                3 -> { fps = 15; bitrate = 4000000 }
            }

            val outputDir = intent.getStringExtra("outputDir") ?: "${getExternalFilesDir(null)}/ScreenRecorder"
            File(outputDir).mkdirs()
            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            outputFile = "$outputDir/recording_$timestamp.mp4"

            mediaRecorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                MediaRecorder()
            } else {
                @Suppress("DEPRECATION")
                MediaRecorder()
            }

            mediaRecorder!!.apply {
                setVideoSource(MediaRecorder.VideoSource.SURFACE)
                if (intent.getBooleanExtra("audio", false)) {
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

            val resultCode = intent.getIntExtra("resultCode", Activity.RESULT_CANCELED)
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
                description = "Shows recording status"
            }
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        val stopIntent = Intent(this, RecordingService::class.java).apply { action = ACTION_STOP }
        val stopPending = PendingIntent.getService(
            this, 0, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val openIntent = Intent(this, MainActivity::class.java)
        val openPending = PendingIntent.getActivity(
            this, 0, openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Screen Recorder")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_record)
            .setContentIntent(openPending)
            .addAction(R.drawable.ic_record, "Stop", stopPending)
            .setOngoing(true)
            .build()
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
