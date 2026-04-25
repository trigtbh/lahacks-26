package com.flow.app

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow

object FluxEvents {
    private val _triggerDetected = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val triggerDetected = _triggerDetected.asSharedFlow()

    private val _sessionEnded = MutableSharedFlow<Unit>(extraBufferCapacity = 8)
    val sessionEnded = _sessionEnded.asSharedFlow()

    private val _workflowTriggered = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val workflowTriggered = _workflowTriggered.asSharedFlow()

    fun emitTrigger(transcript: String) {
        _triggerDetected.tryEmit(transcript)
    }

    fun emitSessionEnded() {
        _sessionEnded.tryEmit(Unit)
    }

    fun emitWorkflowTriggered(command: String) {
        _workflowTriggered.tryEmit(command)
    }
}
