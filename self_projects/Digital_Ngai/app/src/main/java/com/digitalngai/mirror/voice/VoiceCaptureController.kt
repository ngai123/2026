package com.digitalngai.mirror.voice

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer

enum class VoiceCaptureState { IDLE, LISTENING, PROCESSING }

/**
 * Thin wrapper around Android's on-device SpeechRecognizer so the mic button
 * can be "press, talk, done" -- no separate voice UI screen, no API key.
 * Must be driven from the main thread (SpeechRecognizer requirement).
 */
class VoiceCaptureController(
    private val context: Context,
    private val onState: (VoiceCaptureState) -> Unit,
    private val onResult: (String) -> Unit,
    private val onError: (String) -> Unit
) {
    private var recognizer: SpeechRecognizer? = null

    fun isAvailable(): Boolean = SpeechRecognizer.isRecognitionAvailable(context)

    fun start() {
        if (!isAvailable()) {
            onError("Speech recognition isn't available on this device.")
            return
        }
        release()
        val sr = SpeechRecognizer.createSpeechRecognizer(context)
        recognizer = sr
        sr.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) = onState(VoiceCaptureState.LISTENING)
            override fun onBeginningOfSpeech() = onState(VoiceCaptureState.LISTENING)
            override fun onRmsChanged(rmsdB: Float) = Unit
            override fun onBufferReceived(buffer: ByteArray?) = Unit
            override fun onEndOfSpeech() = onState(VoiceCaptureState.PROCESSING)

            override fun onError(error: Int) {
                onState(VoiceCaptureState.IDLE)
                onError(errorMessage(error))
                release()
            }

            override fun onResults(results: Bundle?) {
                val text = results
                    ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    ?.firstOrNull()
                onState(VoiceCaptureState.IDLE)
                if (!text.isNullOrBlank()) onResult(text) else onError("Didn't catch that -- try again.")
                release()
            }

            override fun onPartialResults(partialResults: Bundle?) = Unit
            override fun onEvent(eventType: Int, params: Bundle?) = Unit
        })

        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
        }
        sr.startListening(intent)
    }

    fun cancel() {
        recognizer?.cancel()
        release()
        onState(VoiceCaptureState.IDLE)
    }

    private fun release() {
        recognizer?.destroy()
        recognizer = null
    }

    private fun errorMessage(code: Int): String = when (code) {
        SpeechRecognizer.ERROR_NO_MATCH -> "Didn't catch that -- try again."
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "No speech detected."
        SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Network issue during recognition."
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission is required."
        else -> "Voice capture failed (code $code)."
    }
}
