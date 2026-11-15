package com.digitalngai.mirror.voice

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import java.io.File

class VoiceRecorder(private val context: Context) {
    private var recorder: MediaRecorder? = null
    private var outputFile: File? = null

    fun start(): File {
        val dir = File(context.getExternalFilesDir(null), "audio").apply { mkdirs() }
        val file = File(dir, "journal_${System.currentTimeMillis()}.m4a")
        outputFile = file

        val mr = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(context)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }
        mr.apply {
            setAudioSource(MediaRecorder.AudioSource.MIC)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            setOutputFile(file.absolutePath)
            prepare()
            start()
        }
        recorder = mr
        return file
    }

    /** Returns the recorded file, or null if nothing was recording. */
    fun stop(): File? {
        val file = outputFile
        try {
            recorder?.apply {
                stop()
                release()
            }
        } catch (_: RuntimeException) {
            // stop() called too soon after start(); recording is likely empty/invalid.
        }
        recorder = null
        outputFile = null
        return file
    }

    fun isRecording(): Boolean = recorder != null
}
