package com.flow.app

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import com.flow.app.audio.AudioCaptureManager
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import java.util.concurrent.atomic.AtomicInteger
import java.util.UUID

object TtsQueue {

    private val channel = Channel<suspend () -> Unit>(Channel.UNLIMITED)
    private var tts: TextToSpeech? = null
    private val queuedPlaybackCount = AtomicInteger(0)

    fun isBusy(): Boolean = queuedPlaybackCount.get() > 0

    fun init(tts: TextToSpeech, scope: CoroutineScope) {
        TtsQueue.tts = tts
        scope.launch {
            for (action in channel) {
                try { action() } catch (e: Exception) {
                    Log.e("TtsQueue", "playback error", e)
                } finally {
                    queuedPlaybackCount.updateAndGet { current -> if (current > 0) current - 1 else 0 }
                }
            }
        }
    }

    fun speak(text: String) {
        queuedPlaybackCount.incrementAndGet()
        channel.trySend {
            val t = tts ?: return@trySend
            suspendCancellableCoroutine { cont ->
                val id = UUID.randomUUID().toString()
                t.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) {}
                    override fun onDone(utteranceId: String?) {
                        if (utteranceId == id && !cont.isCompleted) cont.resumeWith(Result.success(Unit))
                    }
                    override fun onError(utteranceId: String?) {
                        if (utteranceId == id && !cont.isCompleted) cont.resumeWith(Result.success(Unit))
                    }
                })
                if (t.speak(text, TextToSpeech.QUEUE_FLUSH, null, id) == TextToSpeech.ERROR) {
                    if (!cont.isCompleted) cont.resumeWith(Result.success(Unit))
                }
            }
        }
    }

    fun playPcm(pcm: ByteArray) {
        if (pcm.isEmpty()) return
        queuedPlaybackCount.incrementAndGet()
        channel.trySend { playPcmSync(pcm) }
    }

    private suspend fun playPcmSync(pcm: ByteArray) = withContext(Dispatchers.IO) {
        val sampleRate = AudioCaptureManager.SAMPLE_RATE
        val bufferSize = AudioTrack.getMinBufferSize(
            sampleRate,
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
                    .setSampleRate(sampleRate)
                    .setEncoding(AudioCaptureManager.AUDIO_FORMAT)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
            )
            .setBufferSizeInBytes(bufferSize)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        track.play()
        track.write(pcm, 0, pcm.size)
        // write() returns when data is queued into the internal buffer, not when
        // playback finishes. Wait for the remaining buffer to drain before stopping.
        val bufferDrainMs = (bufferSize.toLong() * 1000L) / (sampleRate.toLong() * 2L)
        delay(bufferDrainMs + 300L)
        track.stop()
        track.release()
    }
}
