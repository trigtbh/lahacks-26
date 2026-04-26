import java.util.Properties

val localProps = Properties().also { props ->
    val f = rootProject.file("local.properties")
    if (f.exists()) props.load(f.inputStream())
}

fun localProp(key: String) = localProps.getProperty(key)
    ?: System.getenv(key.uppercase().replace(".", "_"))
    ?: ""

fun localPropOrDefault(key: String, default: String) = localProps.getProperty(key)
    ?: System.getenv(key.uppercase().replace(".", "_"))
    ?: default

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.flow.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.flow.app"
        minSdk = 31
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"

        // Inject credentials into AndroidManifest.xml placeholders
        manifestPlaceholders["MWDAT_APPLICATION_ID"] = localProp("mwdat_application_id")
        manifestPlaceholders["MWDAT_CLIENT_TOKEN"] = localProp("mwdat_client_token")

        // Inject credentials into BuildConfig for runtime access
        buildConfigField("String", "MWDAT_APPLICATION_ID", "\"${localProp("mwdat_application_id")}\"")
        buildConfigField("String", "MWDAT_CLIENT_TOKEN", "\"${localProp("mwdat_client_token")}\"")
        buildConfigField("String", "FLOW_API_BASE_URL", "\"${localProp("flow_api_base_url")}\"")
        buildConfigField("String", "FLOW_USER_ID", "\"${localProp("flow_user_id")}\"")
        buildConfigField("double", "VAD_MIN_SPEECH_RMS", localPropOrDefault("vad_min_speech_rms", "28.0"))
        buildConfigField("double", "VAD_MIN_SPEECH_DELTA", localPropOrDefault("vad_min_speech_delta", "10.0"))
        buildConfigField("int", "VAD_START_TRIGGER_CHUNKS", localPropOrDefault("vad_start_trigger_chunks", "2"))
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = "11"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.material.icons.extended)
    debugImplementation(libs.androidx.ui.tooling)

    // Meta Wearables DAT SDK
    implementation(libs.mwdat.core)
    implementation(libs.mwdat.camera)
    debugImplementation(libs.mwdat.mockdevice)

    // Async & networking
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.okhttp)
}
