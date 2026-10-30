package com.devdrop.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import com.devdrop.android.data.DevDropViewModel
import com.devdrop.android.ui.navigation.DevDropApp
import com.devdrop.android.ui.theme.DevDropTheme

class MainActivity : ComponentActivity() {
    private val viewModel by viewModels<DevDropViewModel> {
        DevDropViewModel.Factory(application)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            DevDropTheme {
                DevDropApp(viewModel = viewModel)
            }
        }
    }
}
