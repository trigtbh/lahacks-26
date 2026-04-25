package com.flow.app.wearables

import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.selectors.AutoDeviceSelector
import com.meta.wearable.dat.core.session.Session
import com.meta.wearable.dat.core.types.DeviceIdentifier
import kotlinx.coroutines.flow.Flow

/**
 * Manages the lifecycle of the Ray-Ban glasses connection via the DAT SDK.
 * Once a session is started, Android routes audio through HFP so AudioCaptureManager
 * can pull from the glasses mic using standard AudioRecord APIs.
 */
class WearablesManager {

    private val deviceSelector = AutoDeviceSelector()
    private var session: Session? = null

    /** Emits the currently active device (null if none connected). */
    fun activeDeviceFlow(): Flow<DeviceIdentifier?> = deviceSelector.activeDeviceFlow()

    /**
     * Creates and starts a session for the given device.
     * Call this once a device appears in [activeDeviceFlow].
     */
    fun startSession(deviceIdentifier: DeviceIdentifier) {
        session?.stop()
        val result = Wearables.createSession(deviceSelector)
        result.onSuccess { s ->
            session = s
            s.start()
        }
    }

    fun stopSession() {
        session?.stop()
        session = null
    }
}
