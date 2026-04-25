package com.flow.app.audio

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.flow.app.BuildConfig
import com.flow.app.FluxEvents
import com.flow.app.network.FlowApiClient
import com.flow.app.network.WorkflowRequest
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import java.io.ByteArrayOutputStream
import kotlin.math.sqrt

class AudioCaptureService : Service() {

    companion object {
        const val EXTRA_USER_ID = "user_id"
        private const val CHANNEL_ID = "flow_listening"
        private const val NOTIF_ID = 1
        private const val SILENCE_RMS_THRESHOLD = 600.0
        private const val SILENCE_TIMEOUT_MS = 3000L
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val audioCaptureManager = AudioCaptureManager()
    private lateinit var apiClient: FlowApiClient
    private lateinit var wakeWordDetector: WakeWordDetector

    override fun onCreate() {
        super.onCreate()
        apiClient = FlowApiClient(BuildConfig.FLOW_API_BASE_URL)
        wakeWordDetector = WakeWordDetector(this)
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val userId = intent?.getStringExtra(EXTRA_USER_ID) ?: "akshai"
        startForeground(NOTIF_ID, buildNotification("Say 'Hey Flux' to start"))
        scope.launch { runLoop(userId) }
        return START_STICKY
    }

    private suspend fun runLoop(userId: String) {
        while (currentCoroutineContext().isActive) {
            withContext(Dispatchers.Main) { wakeWordDetector.start() }
            FluxEvents.triggerDetected.first()               // suspend until "hey flux" heard
            withContext(Dispatchers.Main) { wakeWordDetector.stop() }   // release mic for AudioRecord
            recordSession(userId)
        }
    }

    private suspend fun recordSession(userId: String) {
        val chunkId = apiClient.newChunkId()
        val sessionBuffer = ByteArrayOutputStream()
        var lastActiveTime = System.currentTimeMillis()

        apiClient.startAudio(chunkId, userId)
        delay(300) // mic handoff: give SpeechRecognizer time to fully release

        // Two sibling coroutines: one streams audio, one watches for silence.
        // When silence times out, the watcher cancels the stream job;
        // supervisorScope doesn't propagate that cancellation to siblings.
        supervisorScope {
            val streamJob = launch {
                audioCaptureManager.audioChunks().collect { chunk ->
                    val rms = calculateRms(chunk)
                    if (rms >= SILENCE_RMS_THRESHOLD) lastActiveTime = System.currentTimeMillis()
                    sessionBuffer.write(chunk)
                    apiClient.streamAudioChunk(chunk, userId, chunkId)
                        .onSuccess { resp ->
                            if (!resp.partial && resp.transcript.isNotBlank()) {
                                executeWorkflow(resp.transcript, chunkId, userId)
                            }
                        }
                }
            }

            launch {
                while (isActive) {
                    delay(100)
                    if (System.currentTimeMillis() - lastActiveTime > SILENCE_TIMEOUT_MS) {
                        streamJob.cancel()
                        return@launch
                    }
                }
            }

            streamJob.join()
            coroutineContext.cancelChildren()
        }

        withContext(NonCancellable) {
            apiClient.endAudio(chunkId, userId)
            FluxEvents.emitSessionEnded()
            playback(sessionBuffer.toByteArray())
        }
    }

    private suspend fun executeWorkflow(transcript: String, chunkId: String, userId: String) {
        apiClient.executeWorkflow(
            WorkflowRequest(
                triggerPhrase = transcript,
                userId = userId,
                context = mapOf("source" to "glasses_mic", "chunk_id" to chunkId),
            )
        )
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

    private fun playback(pcm: ByteArray) {
        if (pcm.isEmpty()) return
        Thread {
            val bufferSize = AudioTrack.getMinBufferSize(
                AudioCaptureManager.SAMPLE_RATE,
                AudioFormat.CHANNEL_OUT_MONO,
                AudioCaptureManager.AUDIO_FORMAT,
            )
            val track = AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setSampleRate(AudioCaptureManager.SAMPLE_RATE)
                        .setEncoding(AudioCaptureManager.AUDIO_FORMAT)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .build()
                )
                .setBufferSizeInBytes(bufferSize)
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build()
            track.play()
            track.write(pcm, 0, pcm.size)
            track.stop()
            track.release()
        }.start()
    }

    override fun onDestroy() {
        wakeWordDetector.stop()
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
