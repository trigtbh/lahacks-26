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
import java.util.UUID

object TtsQueue {

    private val channel = Channel<suspend () -> Unit>(Channel.UNLIMITED)
    private var tts: TextToSpeech? = null

    fun init(tts: TextToSpeech, scope: CoroutineScope) {
        TtsQueue.tts = tts
        scope.launch {
            for (action in channel) {
                try { action() } catch (e: Exception) {
                    Log.e("TtsQueue", "playback error", e)
                }
            }
        }
    }

    fun speak(text: String) {
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
        channel.trySend { playPcmSync(pcm) }
    }

    private suspend fun playPcmSync(pcm: ByteArray) = withContext(Dispatchers.IO) {
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
    }
}
