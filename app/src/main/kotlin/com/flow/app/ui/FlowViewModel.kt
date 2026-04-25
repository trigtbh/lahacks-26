package com.flow.app.ui

import android.app.Application
import android.content.Intent
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
)

class FlowViewModel(app: Application) : AndroidViewModel(app) {

    private val userId = "akshai"

    private val _uiState = MutableStateFlow(FlowUiState())
    val uiState: StateFlow<FlowUiState> = _uiState.asStateFlow()

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
                    statusMessage = "Message sent! Listening for Flux..."
                )
            }
        }
    }

    fun onPermissionsGranted() {
        _uiState.value = _uiState.value.copy(
            isReady = true,
            statusMessage = "Listening for Flux..."
        )
        // Start the service once — it loops forever internally
        val intent = Intent(getApplication(), AudioCaptureService::class.java).apply {
            putExtra(AudioCaptureService.EXTRA_USER_ID, userId)
        }
        ContextCompat.startForegroundService(getApplication(), intent)
    }
}
