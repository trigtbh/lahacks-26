package com.flow.app.audio

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.IBinder
import android.util.Base64
import android.util.Log
import androidx.core.app.NotificationCompat
import com.flow.app.BuildConfig
import com.flow.app.FluxEvents
import com.flow.app.TtsQueue
import com.flow.app.network.FlowApiClient
import com.flow.app.network.WorkflowRequest
import kotlinx.coroutines.*
import kotlin.math.sqrt

class AudioCaptureService : Service() {

    companion object {
        const val EXTRA_USER_ID = "user_id"
        private const val CHANNEL_ID = "flow_listening"
        private const val NOTIF_ID = 1
        private const val SPEECH_RMS_THRESHOLD = 15.0
        private const val SILENCE_RMS_THRESHOLD = 8.0
        private const val SILENCE_TIMEOUT_MS = 2500L
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val audioCaptureManager = AudioCaptureManager()
    private lateinit var apiClient: FlowApiClient
    private var loopJob: Job? = null
    private var inAgentSession = false

    override fun onCreate() {
        super.onCreate()
        apiClient = FlowApiClient(BuildConfig.FLOW_API_BASE_URL)
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val userId = intent?.getStringExtra(EXTRA_USER_ID) ?: "akshai"
        startForeground(NOTIF_ID, buildNotification("Listening..."))
        if (loopJob?.isActive != true) {
            loopJob = scope.launch { runLoop(userId) }
        }
        return START_STICKY
    }

    private suspend fun runLoop(userId: String) {
        while (currentCoroutineContext().isActive) {
            runSession(userId)
        }
    }

    private suspend fun runSession(userId: String) {
        val chunkId = apiClient.newChunkId()
        var lastActiveTime = System.currentTimeMillis()
        var hadSpeech = false

        apiClient.startAudio(chunkId, userId)

        try {
            coroutineScope {
                val sessionScope = this
                launch {
                    audioCaptureManager.audioChunks().collect { chunk ->
                        val rms = calculateRms(chunk)
                        Log.d("Flux/VAD", "rms=${"%.1f".format(rms)} hadSpeech=$hadSpeech")

                        if (rms >= SPEECH_RMS_THRESHOLD) {
                            lastActiveTime = System.currentTimeMillis()
                            hadSpeech = true
                        }

                        // Only stream once speech has started in this session
                        if (hadSpeech) {
                            apiClient.streamAudioChunk(chunk, userId, chunkId)
                        }

                        if (hadSpeech && System.currentTimeMillis() - lastActiveTime > SILENCE_TIMEOUT_MS) {
                            sessionScope.cancel()
                        }
                    }
                }
            }
        } catch (_: CancellationException) { /* normal session end */ }

        if (hadSpeech) {
            withContext(NonCancellable) {
                apiClient.endAudio(chunkId, userId).onSuccess { resp ->
                    Log.d("Flux/End", "transcript=${resp.transcript} action=${resp.action} inSession=$inAgentSession")

                    if (inAgentSession) {
                        // Forward directly to active agent — no command classification needed
                        apiClient.executeWorkflow(
                            WorkflowRequest(
                                triggerPhrase = resp.transcript,
                                userId = userId,
                                context = mapOf("source" to "glasses_mic", "chunk_id" to chunkId),
                            )
                        ).onSuccess { wf ->
                            Log.d("Flux/Agent", "actionTaken=${wf.actionTaken} reply=${wf.reply}")
                            if (wf.actionTaken == "disconnect") {
                                inAgentSession = false
                                FluxEvents.emitSessionEnded()
                            }
                            val pcm = wf.audioB64?.let { Base64.decode(it, Base64.DEFAULT) }
                            if (pcm != null) TtsQueue.playPcm(pcm)
                        }
                        return@onSuccess
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
                            ).onSuccess { wf ->
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
                            ).onSuccess { wf ->
                                if (wf.actionTaken == "connect") inAgentSession = true
                                val pcm = wf.audioB64?.let { Base64.decode(it, Base64.DEFAULT) }
                                if (pcm != null) TtsQueue.playPcm(pcm)
                            }
                        }
                    }
                }
                FluxEvents.emitSessionEnded()
            }
        } else {
            Log.d("Flux/VAD", "session $chunkId had no speech, skipping end")
        }
    }

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
