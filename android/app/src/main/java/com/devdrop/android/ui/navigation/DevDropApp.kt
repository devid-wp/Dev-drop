package com.devdrop.android.ui.navigation

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.devdrop.android.data.DevDropViewModel
import com.devdrop.android.ui.screens.nearby.NearbyScreen
import com.devdrop.android.ui.screens.send.SendScreen
import com.devdrop.android.ui.screens.settings.SettingsScreen
import com.devdrop.android.ui.screens.transfers.TransfersScreen
import com.devdrop.android.ui.screens.device.DeviceDetailsScreen
import com.devdrop.android.ui.screens.incoming.IncomingTransferScreen

@Composable
fun DevDropApp(viewModel: DevDropViewModel) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val snackbarHostState = remember { SnackbarHostState() }
    val photoPicker = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia()) {
        viewModel.addPickedFiles(it)
    }
    val documentPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) {
        viewModel.addPickedFiles(it)
    }

    LaunchedEffect(state.notice) {
        state.notice?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = androidx.compose.material3.MaterialTheme.colorScheme.background,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        bottomBar = {
            if (currentRoute in AppDestination.entries.map { it.route }) {
                AppNavigationBar(currentRoute) { destination ->
                    navController.navigate(destination.route) {
                        popUpTo(navController.graph.startDestinationId) { saveState = true }
                        launchSingleTop = true
                        restoreState = true
                    }
                }
            }
        },
    ) { innerPadding: PaddingValues ->
        NavHost(
            navController = navController,
            startDestination = AppDestination.Nearby.route,
            modifier = Modifier.padding(innerPadding),
        ) {
            composable(AppDestination.Nearby.route) {
                NearbyScreen(
                    onSearch = { viewModel.showNotice("Discovery is not connected in this build yet.") },
                    onOpenSettings = { navController.navigate(AppDestination.Settings.route) },
                )
            }
            composable(AppDestination.Send.route) {
                SendScreen(
                    files = state.selectedFiles,
                    onPickPhotos = { photoPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo)) },
                    onPickDocuments = { documentPicker.launch(arrayOf("*/*")) },
                    onRemove = viewModel::removeFile,
                )
            }
            composable(AppDestination.Transfers.route) { TransfersScreen() }
            composable(AppDestination.Settings.route) { SettingsScreen() }
            composable("device-details") { DeviceDetailsScreen() }
            composable("incoming-transfer") { IncomingTransferScreen() }
        }
    }
}
