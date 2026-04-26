package com.flow.app

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow

object FluxEvents {
    private val _wakeWordDetected = MutableSharedFlow<String>(replay = 1, extraBufferCapacity = 8)
    val wakeWordDetected = _wakeWordDetected.asSharedFlow()

    private val _triggerDetected = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val triggerDetected = _triggerDetected.asSharedFlow()

    private val _speechCaptured = MutableSharedFlow<String>(replay = 1, extraBufferCapacity = 8)
    val speechCaptured = _speechCaptured.asSharedFlow()

    private val _debugStatus = MutableSharedFlow<String>(replay = 1, extraBufferCapacity = 8)
    val debugStatus = _debugStatus.asSharedFlow()

    private val _errorMessage = MutableSharedFlow<String>(replay = 1, extraBufferCapacity = 8)
    val errorMessage = _errorMessage.asSharedFlow()

    private val _sessionEnded = MutableSharedFlow<Unit>(extraBufferCapacity = 8)
    val sessionEnded = _sessionEnded.asSharedFlow()

    private val _workflowTriggered = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val workflowTriggered = _workflowTriggered.asSharedFlow()

    private val _caltrainTriggered = MutableSharedFlow<Unit>(extraBufferCapacity = 8)
    val caltrainTriggered = _caltrainTriggered.asSharedFlow()

    private val _agentSearchTriggered = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val agentSearchTriggered = _agentSearchTriggered.asSharedFlow()

    private val _audioActive = MutableSharedFlow<Boolean>(replay = 1, extraBufferCapacity = 8)
    val audioActive = _audioActive.asSharedFlow()

    fun emitAudioActive(active: Boolean) {
        _audioActive.tryEmit(active)
    }

    fun emitWakeWordDetected(transcript: String) {
        _wakeWordDetected.tryEmit(transcript)
    }

    fun emitTrigger(transcript: String) {
        _triggerDetected.tryEmit(transcript)
    }

    fun emitSpeechCaptured(transcript: String) {
        _speechCaptured.tryEmit(transcript)
    }

    fun emitDebugStatus(message: String) {
        _debugStatus.tryEmit(message)
    }

    fun emitError(message: String) {
        _errorMessage.tryEmit(message)
    }

    fun emitSessionEnded() {
        _sessionEnded.tryEmit(Unit)
    }

    fun emitWorkflowTriggered(command: String) {
        _workflowTriggered.tryEmit(command)
    }

    fun emitCaltrainTriggered() {
        _caltrainTriggered.tryEmit(Unit)
    }

    fun emitAgentSearchTriggered(agentName: String) {
        _agentSearchTriggered.tryEmit(agentName)
    }
}
