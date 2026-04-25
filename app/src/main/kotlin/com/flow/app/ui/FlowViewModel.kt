package com.flow.app.ui

import android.app.Application
import android.content.Intent
import android.media.AudioAttributes
import android.speech.tts.TextToSpeech
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.flow.app.FluxEvents
import com.flow.app.audio.AudioCaptureService
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class FlowUiState(
    val isReady: Boolean = false,
    val statusMessage: String = "Waiting for permissions...",
    val triggerMessage: String = "",
    val workflowCommand: String = "",
)

class FlowViewModel(app: Application) : AndroidViewModel(app) {

    private val userId = "akshai"

    private val _uiState = MutableStateFlow(FlowUiState())
    val uiState: StateFlow<FlowUiState> = _uiState.asStateFlow()

    private var tts: TextToSpeech? = null

    init {
        viewModelScope.launch {
            FluxEvents.triggerDetected.collect { transcript ->
                _uiState.value = _uiState.value.copy(
                    statusMessage = "Go ahead...",
                    triggerMessage = "Flux heard: \"$transcript\""
                )
            }
        }
        viewModelScope.launch {
            FluxEvents.sessionEnded.collect {
                _uiState.value = _uiState.value.copy(
                    statusMessage = "Listening...",
                    workflowCommand = "",
                )
            }
        }
        viewModelScope.launch {
            FluxEvents.workflowTriggered.collect { command ->
                _uiState.value = _uiState.value.copy(
                    statusMessage = "Building workflow...",
                    workflowCommand = command,
                )
                tts?.speak("Workflow will be created", TextToSpeech.QUEUE_FLUSH, null, null)
            }
        }
    }

    fun onPermissionsGranted() {
        _uiState.value = _uiState.value.copy(
            isReady = true,
            statusMessage = "Listening..."
        )

        val audioAttrs = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()

        tts = TextToSpeech(getApplication()) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.setAudioAttributes(audioAttrs)
            }
        }

        val intent = Intent(getApplication(), AudioCaptureService::class.java).apply {
            putExtra(AudioCaptureService.EXTRA_USER_ID, userId)
        }
        ContextCompat.startForegroundService(getApplication(), intent)
    }

    override fun onCleared() {
        tts?.stop()
        tts?.shutdown()
        super.onCleared()
    }
}
