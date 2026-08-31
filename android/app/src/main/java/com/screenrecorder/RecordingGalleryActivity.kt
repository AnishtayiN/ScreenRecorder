package com.screenrecorder

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import java.io.File
import java.text.SimpleDateFormat
import java.util.*

class RecordingGalleryActivity : AppCompatActivity() {

    private lateinit var recyclerView: RecyclerView
    private lateinit var emptyState: LinearLayout
    private lateinit var tvRecordingsCount: TextView
    private var recordings = mutableListOf<File>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_gallery)

        recyclerView = findViewById(R.id.recyclerView)
        emptyState = findViewById(R.id.emptyState)
        tvRecordingsCount = findViewById(R.id.tvRecordingsCount)

        recyclerView.layoutManager = GridLayoutManager(this, 2)

        findViewById<TextView>(R.id.btnBack).setOnClickListener { finish() }

        loadRecordings()
    }

    private fun loadRecordings() {
        val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES), "ScreenRecorder")
        if (dir.exists()) {
            recordings = dir.listFiles { f -> f.name.endsWith(".mp4") }
                ?.sortedByDescending { it.lastModified() }
                ?.toMutableList() ?: mutableListOf()
        }

        if (recordings.isEmpty()) {
            emptyState.visibility = View.VISIBLE
            recyclerView.visibility = View.GONE
            tvRecordingsCount.text = "0 recordings"
        } else {
            emptyState.visibility = View.GONE
            recyclerView.visibility = View.VISIBLE
            tvRecordingsCount.text = "${recordings.size} recording${if (recordings.size != 1) "s" else ""}"
            recyclerView.adapter = RecordingAdapter(recordings)
        }
    }

    inner class RecordingAdapter(private val files: List<File>) :
        RecyclerView.Adapter<RecordingAdapter.ViewHolder>() {

        inner class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
            val tvFileName: TextView = view.findViewById(R.id.tvFileName)
            val tvDate: TextView = view.findViewById(R.id.tvDate)
            val tvFileSize: TextView = view.findViewById(R.id.tvFileSize)
            val tvDuration: TextView = view.findViewById(R.id.tvDuration)
            val btnPlay: TextView = view.findViewById(R.id.btnPlay)
            val btnShare: TextView = view.findViewById(R.id.btnShare)
            val btnDelete: TextView = view.findViewById(R.id.btnDelete)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
            val view = LayoutInflater.from(parent.context).inflate(R.layout.item_recording, parent, false)
            return ViewHolder(view)
        }

        override fun onBindViewHolder(holder: ViewHolder, position: Int) {
            val file = files[position]

            holder.tvFileName.text = file.name
            val date = SimpleDateFormat("MMM d, yyyy • HH:mm", Locale.US).format(Date(file.lastModified()))
            holder.tvDate.text = date
            holder.tvFileSize.text = formatFileSize(file.length())

            // Estimate duration from file size (rough estimate for MP4)
            val estimatedSeconds = (file.length() / 500000).toInt().coerceAtLeast(1)
            val durationMin = estimatedSeconds / 60
            val durationSec = estimatedSeconds % 60
            holder.tvDuration.text = String.format("%d:%02d", durationMin, durationSec)

            // Play
            holder.btnPlay.setOnClickListener {
                try {
                    val uri = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                        FileProvider.getUriForFile(
                            this@RecordingGalleryActivity,
                            "${packageName}.fileprovider",
                            file
                        )
                    } else {
                        Uri.fromFile(file)
                    }
                    val intent = Intent(Intent.ACTION_VIEW).apply {
                        setDataAndType(uri, "video/mp4")
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    startActivity(intent)
                } catch (e: Exception) {
                    Toast.makeText(this@RecordingGalleryActivity, "No video player found", Toast.LENGTH_SHORT).show()
                }
            }

            // Share
            holder.btnShare.setOnClickListener {
                try {
                    val uri = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                        FileProvider.getUriForFile(
                            this@RecordingGalleryActivity,
                            "${packageName}.fileprovider",
                            file
                        )
                    } else {
                        Uri.fromFile(file)
                    }
                    val intent = Intent(Intent.ACTION_SEND).apply {
                        type = "video/mp4"
                        putExtra(Intent.EXTRA_STREAM, uri)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    startActivity(Intent.createChooser(intent, "Share recording"))
                } catch (e: Exception) {
                    Toast.makeText(this@RecordingGalleryActivity, "Share failed", Toast.LENGTH_SHORT).show()
                }
            }

            // Delete
            holder.btnDelete.setOnClickListener {
                AlertDialog.Builder(this@RecordingGalleryActivity)
                    .setTitle("Delete Recording")
                    .setMessage("Delete ${file.name}?")
                    .setPositiveButton("Delete") { _, _ ->
                        if (file.delete()) {
                            recordings = recordings.toMutableList().also { it.removeAt(position) }
                            notifyItemRemoved(position)
                            notifyItemRangeChanged(position, recordings.size)
                            tvRecordingsCount.text = "${recordings.size} recording${if (recordings.size != 1) "s" else ""}"
                            if (recordings.isEmpty()) {
                                emptyState.visibility = View.VISIBLE
                                recyclerView.visibility = View.GONE
                            }
                        }
                    }
                    .setNegativeButton("Cancel", null)
                    .show()
            }
        }

        override fun getItemCount() = files.size
    }

    private fun formatFileSize(bytes: Long): String {
        return when {
            bytes >= 1073741824 -> String.format("%.1f GB", bytes / 1073741824.0)
            bytes >= 1048576 -> String.format("%.1f MB", bytes / 1048576.0)
            bytes >= 1024 -> String.format("%.1f KB", bytes / 1024.0)
            else -> "$bytes B"
        }
    }
}
