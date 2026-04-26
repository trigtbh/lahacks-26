package com.flow.app.audio

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.net.Uri
import android.os.IBinder
import android.util.Base64
import android.util.Log
import androidx.core.app.NotificationCompat
import com.flow.app.BuildConfig
import com.flow.app.FluxEvents
import com.flow.app.TtsQueue
import com.flow.app.network.EndAudioResponse
import com.flow.app.network.FlowApiClient
import com.flow.app.network.WorkflowRequest
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale
import kotlin.math.sqrt

class AudioCaptureService : Service() {

    companion object {
        const val EXTRA_USER_ID = "user_id"
        private const val CHANNEL_ID = "flow_listening"
        private const val NOTIF_ID = 1
        private val MIN_SPEECH_RMS = BuildConfig.VAD_MIN_SPEECH_RMS
        private const val MIN_SILENCE_RMS = 12.0
        private const val SPEECH_START_MULTIPLIER = 1.35
        private const val SPEECH_END_MULTIPLIER = 1.05
        private val MIN_SPEECH_DELTA = BuildConfig.VAD_MIN_SPEECH_DELTA
        private val START_TRIGGER_CHUNKS = BuildConfig.VAD_START_TRIGGER_CHUNKS
        private const val SILENCE_TIMEOUT_MS = 900L
        private const val MIN_UTTERANCE_MS = 700L
        private const val PRE_ROLL_MS = 500L
        private const val LEVEL_REPORT_INTERVAL_MS = 600L
        private const val POST_WORKFLOW_COOLDOWN_MS = 4000L
        private const val POST_CONFIRMATION_PROMPT_COOLDOWN_MS = 3500L
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val audioCaptureManager = AudioCaptureManager()
    private lateinit var audioRouteManager: AudioRouteManager
    private lateinit var apiClient: FlowApiClient
    private var loopJob: Job? = null
    private var inAgentSession = false
    private var cooldownUntilMs = 0L

    override fun onCreate() {
        super.onCreate()
        audioRouteManager = AudioRouteManager(this)
        apiClient = FlowApiClient(BuildConfig.FLOW_API_BASE_URL)
        createNotificationChannel()
        FluxEvents.emitDebugStatus("Audio service created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val userId = intent?.getStringExtra(EXTRA_USER_ID) ?: "akshai"
        startForeground(NOTIF_ID, buildNotification("Listening..."))
        val routeResult = audioRouteManager.routeToPreferredInput()
        FluxEvents.emitDebugStatus(routeResult.message)
        if (!routeResult.routedToPreferredDevice) {
            FluxEvents.emitError(routeResult.message)
            stopSelf()
            return START_NOT_STICKY
        }

        FluxEvents.emitDebugStatus("Audio service started for $userId")
        if (loopJob?.isActive != true) {
            loopJob = scope.launch {
                runLoop(userId)
            }
        }
        return START_STICKY
    }

    private suspend fun runLoop(userId: String) {
        while (currentCoroutineContext().isActive) {
            if (TtsQueue.isBusy()) {
                FluxEvents.emitDebugStatus("Waiting for response playback to finish...")
                delay(250L)
                continue
            }
            val cooldownRemainingMs = cooldownUntilMs - System.currentTimeMillis()
            if (cooldownRemainingMs > 0L) {
                FluxEvents.emitDebugStatus("Workflow finished. Pausing before next listen...")
                delay(cooldownRemainingMs)
                continue
            }
            runSession(userId)
        }
    }

    private suspend fun runSession(userId: String) {
        FluxEvents.emitDebugStatus("Listening on glasses mic for speech")
        val preRollBytes =
            (AudioCaptureManager.SAMPLE_RATE * AudioCaptureManager.BYTES_PER_SAMPLE * PRE_ROLL_MS / 1000L).toInt()
        val preRollBuffer = RingBuffer(preRollBytes)

        var speaking = false
        var shouldFinalize = false
        var speechStartTime = 0L
        var lastSpeechTime = 0L
        var consecutiveSpeechChunks = 0
        var noiseFloor = 0.0
        var lastLevelReportAt = 0L
        var chunkId: String? = null
        var uploadChannel: Channel<ByteArray>? = null
        var uploaderJob: Job? = null

        try {
            audioCaptureManager.audioChunks().collect { chunk ->
                val now = System.currentTimeMillis()
                val rms = calculateRms(chunk)

                if (!speaking) {
                    preRollBuffer.write(chunk)
                    noiseFloor = updateNoiseFloorWhileIdle(noiseFloor, rms)
                    val speechThreshold = maxOf(
                        MIN_SPEECH_RMS,
                        noiseFloor * SPEECH_START_MULTIPLIER,
                        noiseFloor + MIN_SPEECH_DELTA,
                    )

                    if (now - lastLevelReportAt >= LEVEL_REPORT_INTERVAL_MS) {
                        FluxEvents.emitDebugStatus(
                            "Listening on glasses mic for speech\nrms=${fmt(rms)} floor=${fmt(noiseFloor)} trigger=${fmt(speechThreshold)}"
                        )
                        lastLevelReportAt = now
                    }

                    if (rms >= speechThreshold) {
                        consecutiveSpeechChunks += 1
                    } else {
                        consecutiveSpeechChunks = 0
                    }

                    Log.d(
                        "Flux/VAD",
                        "idle rms=${fmt(rms)} floor=${fmt(noiseFloor)} start=${fmt(speechThreshold)} hits=$consecutiveSpeechChunks"
                    )

                    if (consecutiveSpeechChunks >= START_TRIGGER_CHUNKS) {
                        val newChunkId = apiClient.newChunkId()
                        val startResult = apiClient.startAudio(newChunkId, userId)

                        startResult
                            .onFailure { err ->
                                Log.e("Flux/Start", "chunkId=$newChunkId failed", err)
                                FluxEvents.emitError("Failed to open audio session: ${err.message ?: "unknown error"}")
                                consecutiveSpeechChunks = 0
                            }
                            .onSuccess {
                                FluxEvents.emitDebugStatus("Speech detected locally. Opening session $newChunkId")
                                val channel = Channel<ByteArray>(capacity = Channel.UNLIMITED)
                                uploadChannel = channel
                                uploaderJob = scope.launch {
                                    for (payload in channel) {
                                        apiClient.streamAudioChunk(payload, userId, newChunkId)
                                            .onFailure { err ->
                                                Log.w(
                                                    "Flux/Stream",
                                                    "chunkId=$newChunkId bytes=${payload.size} failed (non-fatal): ${err.message}"
                                                )
                                            }
                                    }
                                }

                                speaking = true
                                shouldFinalize = true
                                chunkId = newChunkId
                                speechStartTime = now
                                lastSpeechTime = now
                                consecutiveSpeechChunks = 0

                                val bufferedAudio = preRollBuffer.drain()
                                enqueueBufferedAudio(channel, bufferedAudio)
                                Log.d(
                                    "Flux/Start",
                                    "chunkId=$newChunkId buffered=${bufferedAudio.size}B floor=${fmt(noiseFloor)}"
                                )
                            }
                    }
                    return@collect
                }

                val speechThreshold = maxOf(
                    MIN_SPEECH_RMS,
                    noiseFloor * SPEECH_START_MULTIPLIER,
                    noiseFloor + MIN_SPEECH_DELTA,
                )
                val silenceThreshold = maxOf(MIN_SILENCE_RMS, noiseFloor * SPEECH_END_MULTIPLIER)

                if (rms >= speechThreshold) {
                    lastSpeechTime = now
                } else if (rms <= silenceThreshold) {
                    noiseFloor = updateNoiseFloor(noiseFloor, rms, 0.02)
                }

                val sendResult = uploadChannel?.trySend(chunk)
                if (sendResult != null && sendResult.isFailure) {
                    Log.w(
                        "Flux/Stream",
                        "chunkId=$chunkId dropped ${chunk.size}B because uploader channel is closed"
                    )
                }

                val utteranceMs = now - speechStartTime
                val silenceMs = now - lastSpeechTime
                Log.d(
                    "Flux/VAD",
                    "speech rms=${fmt(rms)} floor=${fmt(noiseFloor)} stop=${fmt(silenceThreshold)} silenceMs=$silenceMs"
                )

                if (utteranceMs >= MIN_UTTERANCE_MS && silenceMs >= SILENCE_TIMEOUT_MS) {
                    throw CancellationException("Speech ended")
                }
            }
        } catch (_: CancellationException) {
            // normal speech-end path
        }

        val finalizedChunkId = chunkId
        if (shouldFinalize && finalizedChunkId != null) {
            withContext(NonCancellable) {
                uploadChannel?.close()
                uploaderJob?.join()
                FluxEvents.emitDebugStatus("Sending utterance $finalizedChunkId to backend for transcription")

                apiClient.endAudio(finalizedChunkId, userId)
                    .onFailure { err ->
                        Log.e("Flux/End", "chunkId=$finalizedChunkId failed", err)
                        FluxEvents.emitError(
                            "Transcription failed for $finalizedChunkId: ${err.message ?: "unknown error"}"
                        )
                    }
                    .onSuccess { resp ->
                        handleEndAudioResponse(userId, finalizedChunkId, resp)
                    }

                FluxEvents.emitSessionEnded()
            }
        } else {
            Log.d("Flux/VAD", "No speech detected in this capture window")
        }
    }

    private suspend fun handleEndAudioResponse(userId: String, chunkId: String, resp: EndAudioResponse) {
        Log.d(
            "Flux/End",
            "chunkId=$chunkId transcript=${resp.transcript} action=${resp.action} workflowStatus=${resp.workflowStatus} inSession=$inAgentSession"
        )

        if (resp.transcript.isBlank() || resp.action == "ignored" || resp.workflowStatus == "ignored") {
            FluxEvents.emitDebugStatus("Ignoring empty transcript for $chunkId")
            return
        }

        if (resp.reauthRequired && resp.reauthUrl.isNotBlank()) {
            Log.w("Flux/Auth", "Google token expired — opening re-auth URL")
            FluxEvents.emitDebugStatus("Google token expired. Opening browser to reconnect...")
            TtsQueue.speak("Your Google account needs to be reconnected. Opening browser now.")
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(resp.reauthUrl)).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            startActivity(intent)
            return
        }

        FluxEvents.emitSpeechCaptured(resp.transcript)
        FluxEvents.emitDebugStatus("Backend responded for $chunkId with action=${resp.action}")

        if (resp.workflowStatus == "awaiting_confirmation") {
            cooldownUntilMs = System.currentTimeMillis() + POST_CONFIRMATION_PROMPT_COOLDOWN_MS
            FluxEvents.emitDebugStatus(resp.workflowMessage.ifBlank { "Confirmation required" })
            TtsQueue.speak(resp.workflowMessage.ifBlank { "Please confirm the workflow" })
        } else if (
            resp.workflowStatus == "created" ||
            resp.workflowStatus == "executed" ||
            resp.workflowStatus == "partial" ||
            resp.workflowStatus == "failed" ||
            resp.workflowStatus == "cancelled"
        ) {
            cooldownUntilMs = System.currentTimeMillis() + POST_WORKFLOW_COOLDOWN_MS
            FluxEvents.emitDebugStatus(resp.workflowMessage.ifBlank { "Workflow finished. Cooling down..." })
            TtsQueue.speak(resp.workflowMessage.ifBlank { "workflow ${resp.workflowStatus}" })
        }

        if (inAgentSession) {
            apiClient.executeWorkflow(
                WorkflowRequest(
                    triggerPhrase = resp.transcript,
                    userId = userId,
                    context = mapOf("source" to "glasses_mic", "chunk_id" to chunkId),
                )
            )
                .onFailure { err ->
                    Log.e("Flux/Agent", "chunkId=$chunkId workflow execution failed", err)
                    FluxEvents.emitError(
                        "Workflow execution failed for $chunkId: ${err.message ?: "unknown error"}"
                    )
                }
                .onSuccess { wf ->
                    Log.d("Flux/Agent", "actionTaken=${wf.actionTaken} reply=${wf.reply}")
                    if (wf.actionTaken == "disconnect") {
                        inAgentSession = false
                        FluxEvents.emitSessionEnded()
                    }
                    val pcm = wf.audioB64?.let { Base64.decode(it, Base64.DEFAULT) }
                    if (pcm != null) TtsQueue.playPcm(pcm)
                }
            return
        }

        when (resp.action) {
            "workflow" -> {
                FluxEvents.emitTrigger(resp.transcript)
                FluxEvents.emitWorkflowTriggered(resp.command)
            }

            "caltrain" -> {
                FluxEvents.emitTrigger(resp.transcript)
                FluxEvents.emitCaltrainTriggered()
                apiClient.executeWorkflow(
                    WorkflowRequest(
                        triggerPhrase = "talk to caltrain",
                        userId = userId,
                        context = mapOf("source" to "glasses_mic", "chunk_id" to chunkId),
                    )
                )
                    .onFailure { err ->
                        Log.e("Flux/Agent", "chunkId=$chunkId caltrain execution failed", err)
                        FluxEvents.emitError(
                            "Caltrain execution failed for $chunkId: ${err.message ?: "unknown error"}"
                        )
                    }
                    .onSuccess { wf ->
                        if (wf.actionTaken == "connect") inAgentSession = true
                        val pcm = wf.audioB64?.let { Base64.decode(it, Base64.DEFAULT) }
                        if (pcm != null) TtsQueue.playPcm(pcm)
                    }
            }

            "agentverse_search" -> {
                val name = resp.agentName.lowercase()
                FluxEvents.emitTrigger(resp.transcript)
                FluxEvents.emitAgentSearchTriggered(name)
                apiClient.executeWorkflow(
                    WorkflowRequest(
                        triggerPhrase = "talk to $name",
                        userId = userId,
                        context = mapOf("source" to "glasses_mic", "chunk_id" to chunkId),
                    )
                )
                    .onFailure { err ->
                        Log.e("Flux/Agent", "chunkId=$chunkId agentverse execution failed", err)
                        FluxEvents.emitError(
                            "Agent search execution failed for $chunkId: ${err.message ?: "unknown error"}"
                        )
                    }
                    .onSuccess { wf ->
                        if (wf.actionTaken == "connect") inAgentSession = true
                        val pcm = wf.audioB64?.let { Base64.decode(it, Base64.DEFAULT) }
                        if (pcm != null) TtsQueue.playPcm(pcm)
                    }
            }
        }
    }

    private fun enqueueBufferedAudio(channel: Channel<ByteArray>, payload: ByteArray) {
        if (payload.isEmpty()) return
        for (offset in payload.indices step AudioCaptureManager.BYTES_PER_CHUNK) {
            val end = minOf(offset + AudioCaptureManager.BYTES_PER_CHUNK, payload.size)
            val sendResult = channel.trySend(payload.copyOfRange(offset, end))
            if (sendResult.isFailure) {
                Log.w("Flux/Stream", "Failed to queue buffered audio slice ${end - offset}B")
            }
        }
    }

    private fun updateNoiseFloor(current: Double, rms: Double, smoothing: Double): Double {
        if (current == 0.0) return rms
        return current * (1.0 - smoothing) + rms * smoothing
    }

    private fun updateNoiseFloorWhileIdle(current: Double, rms: Double): Double {
        if (current == 0.0) return rms

        // Let the floor rise slowly for genuine ambient changes, but don't let
        // brief speech bursts redefine "silence" before we trigger.
        return if (rms <= current + MIN_SPEECH_DELTA) {
            updateNoiseFloor(current, rms, 0.12)
        } else {
            updateNoiseFloor(current, current, 0.12)
        }
    }

    private fun fmt(value: Double): String = String.format(Locale.US, "%.1f", value)

    private fun calculateRms(pcm: ByteArray): Double {
        var sum = 0.0
        var i = 0
        while (i < pcm.size - 1) {
            val sample = ((pcm[i + 1].toInt() shl 8) or (pcm[i].toInt() and 0xFF)).toShort()
            sum += sample * sample
            i += 2
        }
        return sqrt(sum / (pcm.size / 2))
    }

    override fun onDestroy() {
        audioRouteManager.clearRoute()
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {
        val channel = NotificationChannel(CHANNEL_ID, "Chad Listening", NotificationManager.IMPORTANCE_LOW)
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(text: String): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Chad")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .build()
}
