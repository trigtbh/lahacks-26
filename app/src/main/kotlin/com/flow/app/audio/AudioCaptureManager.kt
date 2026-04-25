package com.flow.app.audio

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.isActive
import kotlin.coroutines.coroutineContext

/**
 * Captures audio from the active Bluetooth HFP device (Ray-Ban glasses mic).
 *
 * When the glasses are connected and a session is running, Android selects the
 * HFP mic as the audio source for VOICE_COMMUNICATION automatically. No extra
 * routing logic needed — the OS handles it.
 *
 * Emits raw PCM chunks as ByteArrays via a cold Flow. Collect in a coroutine;
 * cancelling the collector stops recording and releases the AudioRecord.
 */
class AudioCaptureManager {

    companion object {
        const val SAMPLE_RATE = 16000
        const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
        const val CHUNK_DURATION_MS = 100   // emit a chunk every 100ms
    }

    private val bufferSize: Int = maxOf(
        AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT),
        (SAMPLE_RATE * 2 * CHUNK_DURATION_MS) / 1000  // bytes for CHUNK_DURATION_MS at 16-bit
    )

    /**
     * Returns a Flow that emits raw PCM ByteArray chunks continuously.
     * Requires RECORD_AUDIO permission to be granted before collecting.
     */
    fun audioChunks(): Flow<ByteArray> = flow {
        val recorder = AudioRecord(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION,
            SAMPLE_RATE,
            CHANNEL_CONFIG,
            AUDIO_FORMAT,
            bufferSize
        )

        Log.d("Flux/Audio", "recorder.state=${recorder.state} bufferSize=$bufferSize")
        try {
            recorder.startRecording()
            Log.d("Flux/Audio", "recordingState=${recorder.recordingState}")
            val buffer = ByteArray(bufferSize)
            while (coroutineContext.isActive) {
                val bytesRead = recorder.read(buffer, 0, buffer.size)
                Log.d("Flux/Audio", "bytesRead=$bytesRead")
                if (bytesRead > 0) {
                    emit(buffer.copyOf(bytesRead))
                }
            }
        } finally {
            recorder.stop()
            recorder.release()
        }
    }.flowOn(Dispatchers.IO)
}
