package com.flow.app.ui

import android.app.Application
import android.content.Intent
import android.media.AudioAttributes
import android.speech.tts.TextToSpeech
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.flow.app.BuildConfig
import com.flow.app.FluxEvents
import com.flow.app.TtsQueue
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
    val lastTranscript: String = "",
    val debugMessage: String = "",
    val errorMessage: String = "",
    val isAudioActive: Boolean = false,
)

class FlowViewModel(app: Application) : AndroidViewModel(app) {

    private val userId = BuildConfig.FLOW_USER_ID.ifBlank { "akshai" }

    private val _uiState = MutableStateFlow(FlowUiState())
    val uiState: StateFlow<FlowUiState> = _uiState.asStateFlow()

    private var tts: TextToSpeech? = null

    init {
        viewModelScope.launch {
            FluxEvents.triggerDetected.collect { transcript ->
                _uiState.value = _uiState.value.copy(
                    statusMessage = "Go ahead...",
                    triggerMessage = "Chad heard: \"$transcript\""
                )
            }
        }
        viewModelScope.launch {
            FluxEvents.speechCaptured.collect { transcript ->
                _uiState.value = _uiState.value.copy(
                    lastTranscript = transcript,
                    errorMessage = "",
                )
            }
        }
        viewModelScope.launch {
            FluxEvents.debugStatus.collect { message ->
                _uiState.value = _uiState.value.copy(debugMessage = message)
            }
        }
        viewModelScope.launch {
            FluxEvents.errorMessage.collect { message ->
                _uiState.value = _uiState.value.copy(
                    errorMessage = message,
                    statusMessage = "Capture error",
                )
            }
        }
        viewModelScope.launch {
            FluxEvents.sessionEnded.collect {
                _uiState.value = _uiState.value.copy(
                    statusMessage = "Listening on glasses...",
                    workflowCommand = "",
                )
            }
        }
        viewModelScope.launch {
            FluxEvents.workflowTriggered.collect { command ->
                _uiState.value = _uiState.value.copy(
                    statusMessage = "Workflow ready...",
                    workflowCommand = command,
                )
            }
        }
        viewModelScope.launch {
            FluxEvents.caltrainTriggered.collect {
                _uiState.value = _uiState.value.copy(
                    statusMessage = "Talking to Caltrain...",
                    workflowCommand = "Connecting to Caltrain agent",
                )
            }
        }
        viewModelScope.launch {
            FluxEvents.agentSearchTriggered.collect { agentName ->
                _uiState.value = _uiState.value.copy(
                    statusMessage = "Finding agent...",
                    workflowCommand = "Searching for $agentName on Agentverse",
                )
            }
        }
        viewModelScope.launch {
            FluxEvents.audioActive.collect { active ->
                _uiState.value = _uiState.value.copy(isAudioActive = active)
            }
        }
    }

    fun onPermissionsGranted() {
        _uiState.value = _uiState.value.copy(
            isReady = true,
            statusMessage = "Listening on glasses...",
            debugMessage = "Starting glasses-only capture",
        )

        val audioAttrs = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()

        tts = TextToSpeech(getApplication()) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.setAudioAttributes(audioAttrs)
                TtsQueue.init(tts!!, viewModelScope)
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
