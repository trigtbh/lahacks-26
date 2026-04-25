package com.flow.app.audio

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.flow.app.BuildConfig
import com.flow.app.FluxEvents
import com.flow.app.network.FlowApiClient
import com.flow.app.network.WorkflowRequest
import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import kotlin.math.sqrt

class AudioCaptureService : Service() {

    companion object {
        const val EXTRA_USER_ID = "user_id"
        private const val CHANNEL_ID = "flow_listening"
        private const val NOTIF_ID = 1
        private const val VAD_RMS_THRESHOLD = 25.0
        private const val SILENCE_RMS_THRESHOLD = 25.0
        private const val SILENCE_TIMEOUT_MS = 2500L
        private val RING_BUFFER_BYTES = AudioCaptureManager.SAMPLE_RATE * 2 * 2 // 2s pre-roll
    }

    private enum class State { IDLE, RECORDING }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val audioCaptureManager = AudioCaptureManager()
    private lateinit var apiClient: FlowApiClient

    override fun onCreate() {
        super.onCreate()
        apiClient = FlowApiClient(BuildConfig.FLOW_API_BASE_URL)
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val userId = intent?.getStringExtra(EXTRA_USER_ID) ?: "akshai"
        startForeground(NOTIF_ID, buildNotification("Listening..."))
        scope.launch { runLoop(userId) }
        return START_STICKY
    }

    private suspend fun runLoop(userId: String) {
        val ringBuffer = RingBuffer(RING_BUFFER_BYTES)
        var state = State.IDLE

        var chunkId = ""
        var lastActiveTime = 0L
        var fluxDetected = false

        audioCaptureManager.audioChunks().collect { chunk ->
            val rms = calculateRms(chunk)

            Log.d("Flux/VAD", "rms=${"%.1f".format(rms)} state=$state")

            when (state) {
                State.IDLE -> {
                    ringBuffer.write(chunk)
                    if (rms >= VAD_RMS_THRESHOLD) {
                        state = State.RECORDING
                        chunkId = apiClient.newChunkId()
                        lastActiveTime = System.currentTimeMillis()
                        fluxDetected = false

                        val preRoll = ringBuffer.drain()
                        apiClient.startAudio(chunkId, userId)
                        if (preRoll.isNotEmpty()) {
                            apiClient.streamAudioChunk(preRoll, userId, chunkId)
                                .onSuccess { onTranscript(it.transcript, it.partial, chunkId, userId, fluxDetected) { fluxDetected = true } }
                        }
                        apiClient.streamAudioChunk(chunk, userId, chunkId)
                            .onSuccess { onTranscript(it.transcript, it.partial, chunkId, userId, fluxDetected) { fluxDetected = true } }
                    }
                }

                State.RECORDING -> {
                    if (rms >= SILENCE_RMS_THRESHOLD) {
                        lastActiveTime = System.currentTimeMillis()
                    } else if (System.currentTimeMillis() - lastActiveTime > SILENCE_TIMEOUT_MS) {
                        state = State.IDLE
                        withContext(NonCancellable) {
                            apiClient.endAudio(chunkId, userId).onSuccess { resp ->
                                if (containsFlux(resp.transcript) && containsWorkflow(resp.transcript)) {
                                    FluxEvents.emitWorkflowTriggered(resp.command)
                                }
                            }
                            FluxEvents.emitSessionEnded()
                        }
                        return@collect
                    }

                    apiClient.streamAudioChunk(chunk, userId, chunkId)
                        .onSuccess { onTranscript(it.transcript, it.partial, chunkId, userId, fluxDetected) { fluxDetected = true } }
                }
            }
        }
    }

    private suspend fun onTranscript(
        transcript: String,
        partial: Boolean,
        chunkId: String,
        userId: String,
        fluxAlreadyDetected: Boolean,
        onFluxDetected: () -> Unit,
    ) {
        if (!fluxAlreadyDetected && transcript.contains("flux", ignoreCase = true)) {
            onFluxDetected()
            FluxEvents.emitTrigger(transcript)
        }
        if (!partial && transcript.isNotBlank()) {
            apiClient.executeWorkflow(
                WorkflowRequest(
                    triggerPhrase = transcript,
                    userId = userId,
                    context = mapOf("source" to "glasses_mic", "chunk_id" to chunkId),
                )
            )
        }
    }

    private fun containsFlux(text: String) =
        listOf("flux", "flock", "flex", "flocks", "flax", "fluke").any { text.contains(it, ignoreCase = true) }

    private fun containsWorkflow(text: String) =
        listOf("workflow", "work flow", "workload", "work-flow", "work").any { text.contains(it, ignoreCase = true) }

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
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {
        val channel = NotificationChannel(CHANNEL_ID, "Flux Listening", NotificationManager.IMPORTANCE_LOW)
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(text: String): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Flux")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .build()
}
