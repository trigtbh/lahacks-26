package com.flow.app.network

import com.flow.app.audio.AudioCaptureManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit

data class TranscriptResponse(
    val transcript: String,
    val partial: Boolean,
)

data class WorkflowRequest(
    val triggerPhrase: String,
    val userId: String,
    val context: Map<String, Any> = emptyMap(),
)

data class WorkflowResponse(
    val actionTaken: String,
    val stepsCompleted: List<String>,
    val needsInput: Boolean,
    val question: String,
)

class FlowApiClient(baseUrl: String) {

    private val base = baseUrl.trimEnd('/')

    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    /** Generates a new unique ID for an audio session. */
    fun newChunkId(): String = UUID.randomUUID().toString()

    /**
     * POST /audio/start
     * Signals the backend that a new audio chunk session is beginning.
     * Must be called before streaming chunks for this chunkId.
     */
    suspend fun startAudio(chunkId: String, userId: String): Result<Unit> =
        withContext(Dispatchers.IO) {
            runCatching {
                val body = JSONObject().apply {
                    put("chunk_id", chunkId)
                    put("user_id", userId)
                }
                val request = Request.Builder()
                    .url("$base/audio/start")
                    .addHeader("X-Audio-Encoding", "pcm_s16le")
                    .addHeader("X-Audio-Sample-Rate", AudioCaptureManager.SAMPLE_RATE.toString())
                    .post(body.toString().toRequestBody("application/json".toMediaType()))
                    .build()
                val response = http.newCall(request).execute()
                check(response.isSuccessful) {
                    "Audio start error ${response.code}: ${response.body?.string()}"
                }
            }
        }

    /**
     * POST /audio/end
     * Signals the backend that the audio chunk session is complete.
     * Must be called after the last chunk for this chunkId.
     */
    suspend fun endAudio(chunkId: String, userId: String): Result<Unit> =
        withContext(Dispatchers.IO) {
            runCatching {
                val body = JSONObject().apply {
                    put("chunk_id", chunkId)
                    put("user_id", userId)
                }
                val request = Request.Builder()
                    .url("$base/audio/end")
                    .post(body.toString().toRequestBody("application/json".toMediaType()))
                    .build()
                val response = http.newCall(request).execute()
                check(response.isSuccessful) {
                    "Audio end error ${response.code}: ${response.body?.string()}"
                }
            }
        }

    /**
     * POST /audio/stream
     * Sends a raw PCM chunk. Include the chunkId so the backend can group chunks.
     */
    suspend fun streamAudioChunk(
        chunk: ByteArray,
        userId: String,
        chunkId: String,
    ): Result<TranscriptResponse> = withContext(Dispatchers.IO) {
        runCatching {
            val request = Request.Builder()
                .url("$base/audio/stream")
                .addHeader("X-User-Id", userId)
                .addHeader("X-Chunk-Id", chunkId)
                .addHeader("X-Audio-Sample-Rate", "16000")
                .addHeader("X-Audio-Encoding", "pcm_s16le")
                .addHeader("X-Audio-Channels", "1")
                .post(chunk.toRequestBody("application/octet-stream".toMediaType()))
                .build()

            val response = http.newCall(request).execute()
            check(response.isSuccessful) {
                "Audio stream error ${response.code}: ${response.body?.string()}"
            }
            val body = JSONObject(response.body!!.string())
            TranscriptResponse(
                transcript = body.getString("transcript"),
                partial = body.getBoolean("partial"),
            )
        }
    }

    /**
     * POST /workflow/execute
     * Sends a finalized trigger phrase and context to kick off a workflow.
     */
    suspend fun executeWorkflow(req: WorkflowRequest): Result<WorkflowResponse> =
        withContext(Dispatchers.IO) {
            runCatching {
                val body = JSONObject().apply {
                    put("trigger_phrase", req.triggerPhrase)
                    put("user_id", req.userId)
                    put("context", JSONObject(req.context))
                }
                val request = Request.Builder()
                    .url("$base/workflow/execute")
                    .post(body.toString().toRequestBody("application/json".toMediaType()))
                    .build()
                val response = http.newCall(request).execute()
                check(response.isSuccessful) {
                    "Workflow error ${response.code}: ${response.body?.string()}"
                }
                val res = JSONObject(response.body!!.string())
                val steps = res.getJSONArray("steps_completed").let { arr ->
                    List(arr.length()) { arr.getString(it) }
                }
                WorkflowResponse(
                    actionTaken = res.getString("action_taken"),
                    stepsCompleted = steps,
                    needsInput = res.getBoolean("needs_input"),
                    question = res.optString("question", ""),
                )
            }
        }
}
