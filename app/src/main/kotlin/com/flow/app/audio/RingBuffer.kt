package com.flow.app.audio

/**
 * Fixed-size circular buffer for raw PCM bytes.
 * Keeps the most recent [capacityBytes] of audio at all times.
 * Thread-safe for single-writer/single-reader use.
 */
class RingBuffer(private val capacityBytes: Int) {

    private val buf = ByteArray(capacityBytes)
    private var writePos = 0
    private var size = 0

    fun write(data: ByteArray) {
        for (byte in data) {
            buf[writePos] = byte
            writePos = (writePos + 1) % capacityBytes
            if (size < capacityBytes) size++
        }
    }

    /** Returns all buffered bytes in chronological order and resets the buffer. */
    fun drain(): ByteArray {
        if (size == 0) return ByteArray(0)
        val out = ByteArray(size)
        val start = if (size < capacityBytes) 0 else writePos
        for (i in 0 until size) {
            out[i] = buf[(start + i) % capacityBytes]
        }
        writePos = 0
        size = 0
        return out
    }
}
