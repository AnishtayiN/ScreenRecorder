package com.screenrecorder

import android.annotation.SuppressLint
import android.app.Service
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import android.view.*
import android.widget.TextView
import android.view.animation.DecelerateInterpolator

class FloatingOverlayService : Service() {

    companion object {
        private const val TAG = "FloatingOverlay"
        const val ACTION_START = "com.screenrecorder.FLOAT_START"
        const val ACTION_STOP = "com.screenrecorder.FLOAT_STOP"
        const val ACTION_UPDATE_TIMER = "com.screenrecorder.FLOAT_UPDATE_TIMER"
    }

    private var windowManager: WindowManager? = null
    private var overlayView: View? = null
    private var tvTimer: TextView? = null
    private var isExpanded = false
    private var elapsedSeconds = 0
    private val handler = Handler(Looper.getMainLooper())

    private val timerRunnable = object : Runnable {
        override fun run() {
            elapsedSeconds++
            val h = elapsedSeconds / 3600
            val m = (elapsedSeconds % 3600) / 60
            val s = elapsedSeconds % 60
            tvTimer?.text = if (h > 0) String.format("%d:%02d:%02d", h, m, s) else String.format("%02d:%02d", m, s)
            handler.postDelayed(this, 1000)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    @SuppressLint("ClickableViewAccessibility")
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> showOverlay()
            ACTION_STOP -> removeOverlay()
            ACTION_UPDATE_TIMER -> {
                elapsedSeconds = intent.getIntExtra("seconds", 0)
                val h = elapsedSeconds / 3600
                val m = (elapsedSeconds % 3600) / 60
                val s = elapsedSeconds % 60
                tvTimer?.text = if (h > 0) String.format("%d:%02d:%02d", h, m, s) else String.format("%02d:%02d", m, s)
            }
        }
        return START_NOT_STICKY
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun showOverlay() {
        if (overlayView != null) return

        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager

        val inflater = LayoutInflater.from(this)
        overlayView = inflater.inflate(R.layout.overlay_floating, null)
        tvTimer = overlayView!!.findViewById(R.id.tvFloatingTimer)

        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        else
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = 50
            y = 200
        }

        // Make draggable
        var initialX = 0
        var initialY = 0
        var initialTouchX = 0f
        var initialTouchY = 0f

        overlayView!!.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    initialX = params.x
                    initialY = params.y
                    initialTouchX = event.rawX
                    initialTouchY = event.rawY
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    params.x = initialX + (event.rawX - initialTouchX).toInt()
                    params.y = initialY + (event.rawY - initialTouchY).toInt()
                    windowManager?.updateViewLayout(overlayView, params)
                    true
                }
                else -> false
            }
        }

        // Pause button
        overlayView!!.findViewById<TextView>(R.id.btnFloatingPause).setOnClickListener {
            val intent = Intent(this, RecordingService::class.java)
            intent.action = RecordingService.ACTION_PAUSE
            startService(intent)
        }

        // Stop button
        overlayView!!.findViewById<TextView>(R.id.btnFloatingStop).setOnClickListener {
            val intent = Intent(this, RecordingService::class.java)
            intent.action = RecordingService.ACTION_STOP
            startService(intent)
            removeOverlay()
        }

        windowManager?.addView(overlayView, params)

        // Start timer
        handler.postDelayed(timerRunnable, 1000)

        // Entrance animation
        overlayView?.let {
            it.alpha = 0f
            it.translationX = -100f
            it.animate()
                .alpha(1f)
                .translationX(0f)
                .setDuration(300)
                .setInterpolator(DecelerateInterpolator())
                .start()
        }
    }

    private fun removeOverlay() {
        handler.removeCallbacks(timerRunnable)
        overlayView?.let {
            it.animate()
                .alpha(0f)
                .translationX(-100f)
                .setDuration(200)
                .withEndAction {
                    try {
                        windowManager?.removeView(overlayView)
                    } catch (e: IllegalArgumentException) {
                        Log.w(TAG, "Overlay already removed: ${e.message}")
                    }
                    overlayView = null
                }
                .start()
        } ?: run {
            try {
                windowManager?.removeView(overlayView)
            } catch (e: IllegalArgumentException) {
                Log.w(TAG, "Overlay already removed: ${e.message}")
            }
            overlayView = null
        }
    }

    override fun onDestroy() {
        removeOverlay()
        super.onDestroy()
    }
}
