package com.flow.app

import android.Manifest
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts.RequestMultiplePermissions
import androidx.activity.viewModels
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.flow.app.ui.FlowViewModel

private val BrandOrange = Color(0xFFf73a00)
private val BgColor = Color(0xFFf7f4f0)
private val CardColor = Color(0xFFffffff)
private val BorderColor = Color(0xFFd6d0c8)
private val BorderDark = Color(0xFF0d0d0d)
private val TextPrimary = Color(0xFF0d0d0d)
private val TextMuted = Color(0xFF888888)

class MainActivity : ComponentActivity() {

    private val viewModel: FlowViewModel by viewModels()

    private val permissionsLauncher = registerForActivityResult(RequestMultiplePermissions()) { results ->
        if (results.values.all { it }) {
            viewModel.onPermissionsGranted()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                FlowScreen(viewModel)
            }
        }
        permissionsLauncher.launch(
            arrayOf(
                Manifest.permission.BLUETOOTH_CONNECT,
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.RECORD_AUDIO,
            )
        )
    }
}

@Composable
fun FlowScreen(viewModel: FlowViewModel) {
    val state by viewModel.uiState.collectAsState()
    val active = state.isAudioActive

    val infiniteTransition = rememberInfiniteTransition(label = "mic-pulse")
    val ringScale by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = 1.55f,
        animationSpec = infiniteRepeatable(
            animation = tween(900, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "ringScale"
    )
    val ringAlpha by infiniteTransition.animateFloat(
        initialValue = 0.45f,
        targetValue = 0f,
        animationSpec = infiniteRepeatable(
            animation = tween(900, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "ringAlpha"
    )

    val micIconTint by animateColorAsState(
        targetValue = if (active) BrandOrange else TextMuted,
        animationSpec = tween(300),
        label = "micTint"
    )
    val micBg by animateColorAsState(
        targetValue = if (active) BrandOrange.copy(alpha = 0.12f) else CardColor,
        animationSpec = tween(300),
        label = "micBg"
    )
    val micBorder by animateColorAsState(
        targetValue = if (active) BorderDark else BorderColor,
        animationSpec = tween(300),
        label = "micBorder"
    )

    Surface(
        modifier = Modifier.fillMaxSize(),
        color = BgColor
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(32.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = "barelyatwork",
                fontSize = 30.sp,
                fontWeight = FontWeight.Bold,
                color = BrandOrange,
                letterSpacing = (-0.5).sp,
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = "voice automations for meta ray-bans",
                fontSize = 13.sp,
                color = TextMuted,
                letterSpacing = 0.sp,
            )

            Spacer(modifier = Modifier.height(72.dp))

            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier.size(140.dp)
            ) {
                if (active) {
                    Box(
                        modifier = Modifier
                            .size(100.dp)
                            .scale(ringScale)
                            .background(
                                color = BrandOrange.copy(alpha = ringAlpha),
                                shape = CircleShape
                            )
                    )
                }
                Box(
                    contentAlignment = Alignment.Center,
                    modifier = Modifier
                        .size(100.dp)
                        .background(color = micBg, shape = CircleShape)
                        .border(width = 1.5.dp, color = micBorder, shape = CircleShape)
                ) {
                    Icon(
                        imageVector = Icons.Filled.Mic,
                        contentDescription = "Microphone",
                        tint = micIconTint,
                        modifier = Modifier.size(44.dp)
                    )
                }
            }

            Spacer(modifier = Modifier.height(28.dp))

            Text(
                text = state.statusMessage,
                fontSize = 14.sp,
                color = if (state.errorMessage.isNotEmpty()) BrandOrange else TextMuted,
                textAlign = TextAlign.Center,
            )

            if (state.errorMessage.isNotEmpty()) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = state.errorMessage,
                    fontSize = 12.sp,
                    color = TextMuted,
                    textAlign = TextAlign.Center,
                )
            }

            if (state.workflowCommand.isNotEmpty()) {
                Spacer(modifier = Modifier.height(48.dp))
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(color = CardColor, shape = RoundedCornerShape(14.dp))
                        .border(width = 1.5.dp, color = BorderDark, shape = RoundedCornerShape(14.dp))
                        .padding(horizontal = 20.dp, vertical = 16.dp)
                ) {
                    Column {
                        Text(
                            text = "RUNNING WORKFLOW",
                            fontSize = 10.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = BrandOrange,
                            letterSpacing = 1.2.sp,
                        )
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(
                            text = state.workflowCommand,
                            fontSize = 15.sp,
                            color = TextPrimary,
                        )
                    }
                }
            }
        }
    }
}
