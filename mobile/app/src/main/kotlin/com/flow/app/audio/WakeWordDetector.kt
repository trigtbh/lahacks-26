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
    private val audioRouteManager = AudioRouteManager(context)

    fun start() {
        if (isListening) return
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            Log.w("WakeWord", "Speech recognition not available")
            FluxEvents.emitError("Wake word recognition is not available on this device")
            return
        }
        isListening = true
        triggered = false
        FluxEvents.emitDebugStatus(audioRouteManager.routeToPreferredInput().message)
        FluxEvents.emitDebugStatus("Wake word detector listening for Flux")
        listen()
    }

    fun stop() {
        if (!isListening && recognizer == null) return
        isListening = false
        recognizer?.stopListening()
        recognizer?.destroy()
        recognizer = null
        audioRouteManager.clearRoute()
        FluxEvents.emitDebugStatus("Wake word detector stopped")
    }

    private fun onFluxDetected(text: String) {
        if (triggered) return
        triggered = true
        Log.d("WakeWord", "Flux detected: $text")
        // Stop mic immediately so AudioRecord can take over
        isListening = false
        recognizer?.stopListening()
        FluxEvents.emitWakeWordDetected(text)
    }

    private fun listen() {
        if (!isListening) return
        triggered = false

        recognizer?.destroy()
        recognizer = SpeechRecognizer.createSpeechRecognizer(context).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onPartialResults(partial: Bundle) = Unit

                override fun onResults(results: Bundle) {
                    val matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    val fluxMatch = matches?.firstOrNull { it.contains("flux", ignoreCase = true) }
                    if (fluxMatch != null) {
                        onFluxDetected(fluxMatch)
                    } else {
                        restart()
                    }
                }

                override fun onError(error: Int) {
                    Log.d("WakeWord", "Error: $error")
                    FluxEvents.emitDebugStatus("Wake word recognizer error=$error; retrying")
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
