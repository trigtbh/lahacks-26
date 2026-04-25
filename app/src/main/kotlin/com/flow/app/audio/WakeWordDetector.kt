package com.flow.app.audio

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import com.flow.app.FluxEvents
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class WakeWordDetector(private val context: Context) {

    private var recognizer: SpeechRecognizer? = null
    private var isListening = false
    private var triggered = false  // prevent double-firing per utterance
    private val scope = CoroutineScope(Dispatchers.Main)

    fun start() {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            Log.w("WakeWord", "Speech recognition not available")
            return
        }
        isListening = true
        triggered = false
        listen()
    }

    fun stop() {
        isListening = false
        recognizer?.stopListening()
        recognizer?.destroy()
        recognizer = null
    }

    private fun onFluxDetected(text: String) {
        if (triggered) return
        triggered = true
        Log.d("WakeWord", "Flux detected: $text")
        // Stop mic immediately so AudioRecord can take over
        recognizer?.stopListening()
        FluxEvents.emitTrigger(text)
    }

    private fun listen() {
        if (!isListening) return
        triggered = false

        recognizer?.destroy()
        recognizer = SpeechRecognizer.createSpeechRecognizer(context).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onPartialResults(partial: Bundle) {
                    val matches = partial.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    matches?.firstOrNull { it.contains("flux", ignoreCase = true) }
                        ?.let { onFluxDetected(it) }
                }

                override fun onResults(results: Bundle) {
                    val matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    matches?.firstOrNull { it.contains("flux", ignoreCase = true) }
                        ?.let { onFluxDetected(it) }
                    restart()
                }

                override fun onError(error: Int) {
                    Log.d("WakeWord", "Error: $error")
                    restart(delayMs = 300)
                }

                override fun onEndOfSpeech() = Unit
                override fun onBeginningOfSpeech() = Unit
                override fun onBufferReceived(buffer: ByteArray?) = Unit
                override fun onEvent(eventType: Int, params: Bundle?) = Unit
                override fun onReadyForSpeech(params: Bundle?) = Unit
                override fun onRmsChanged(rmsdB: Float) = Unit
            })
        }

        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 5)
        }
        recognizer?.startListening(intent)
    }

    private fun restart(delayMs: Long = 100) {
        if (!isListening) return
        scope.launch {
            delay(delayMs)
            listen()
        }
    }
}
