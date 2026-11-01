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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Modifier
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
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
import com.devdrop.android.ui.screens.connection.ConnectionSetupScreen
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode

@Composable
fun DevDropApp(viewModel: DevDropViewModel) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val snackbarHostState = remember { SnackbarHostState() }
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val codeScanner = remember(context) {
        GmsBarcodeScanning.getClient(context, GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
    }
    val photoPicker = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia()) {
        viewModel.addPickedFiles(it)
    }
    val documentPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) {
        viewModel.addPickedFiles(it)
    }
    val certificatePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) {
        it?.let(viewModel::selectCaCertificate)
    }
    val receiveDestinationPicker = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("*/*")) {
        viewModel.incomingDestinationResult(it)
    }

    LaunchedEffect(currentRoute, state.connection.phase, lifecycleOwner) {
        if (state.connection.phase == com.devdrop.android.data.model.ConnectionPhase.Connected &&
            currentRoute in setOf(AppDestination.Transfers.route, "incoming-transfer")) {
            lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
                while (isActive) {
                    viewModel.refreshIncomingOffersNow()
                    delay(3_000)
                }
            }
        }
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
                    connection = state.connection,
                    onSearch = viewModel::searchServers,
                    onScanQr = {
                        codeScanner.startScan()
                            .addOnSuccessListener { barcode ->
                                barcode.rawValue?.let { payload ->
                                    if (viewModel.useQrPayload(payload)) {
                                        navController.navigate("connect")
                                        viewModel.pair()
                                    }
                                } ?: viewModel.showNotice("This QR code does not contain a valid Dev-Drop pairing request.")
                            }
                            .addOnFailureListener { viewModel.showNotice("QR scanner unavailable. Enter the HTTPS address manually.") }
                    },
                    onAddressChanged = viewModel::setAddressDraft,
                    onConnectAddress = { if (viewModel.continueToConnectionSetup()) navController.navigate("connect") },
                    onSelectServer = { viewModel.selectDiscoveredServer(it); navController.navigate("connect") },
                    onOpenDetails = { navController.navigate("device-details") },
                )
            }
            composable("connect") {
                ConnectionSetupScreen(
                    state = state.connection,
                    onAddressChanged = viewModel::setAddressDraft,
                    onPickCertificate = { certificatePicker.launch(arrayOf("*/*")) },
                    onFingerprintChanged = viewModel::setFingerprintConfirmation,
                    onPairingCodeChanged = viewModel::setPairingCode,
                    onPair = viewModel::pair,
                    onCancelPairing = { viewModel.cancelPairing(); navController.popBackStack() },
                    onCheck = viewModel::checkConnection,
                    onDisconnect = viewModel::disconnect,
                    onBack = { navController.popBackStack() },
                )
            }
            composable(AppDestination.Send.route) {
                SendScreen(
                    files = state.selectedFiles,
                    transfer = state.transfer,
                    connected = state.connection.phase == com.devdrop.android.data.model.ConnectionPhase.Connected,
                    onPickPhotos = { photoPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo)) },
                    onPickDocuments = { documentPicker.launch(arrayOf("*/*")) },
                    onRemove = viewModel::removeFile,
                    onSend = viewModel::sendSelectedFiles,
                    onCancel = viewModel::cancelTransfer,
                )
            }
            composable(AppDestination.Transfers.route) {
                TransfersScreen(
                    transfer = state.transfer,
                    incomingDownload = state.incomingDownload,
                    pendingOffers = state.incomingOffers.count { it.status == "pending" },
                    onCancelSend = viewModel::cancelTransfer,
                    onCancelReceive = viewModel::cancelIncomingDownload,
                    onOpenIncoming = { navController.navigate("incoming-transfer") },
                )
            }
            composable(AppDestination.Settings.route) {
                SettingsScreen(state.connection) {
                    if (state.connection.phase == com.devdrop.android.data.model.ConnectionPhase.Connected) {
                        navController.navigate("device-details")
                    } else navController.navigate("connect")
                }
            }
            composable("device-details") {
                DeviceDetailsScreen(state.connection, viewModel::checkConnection, viewModel::disconnect)
            }
            composable("incoming-transfer") {
                IncomingTransferScreen(
                    connected = state.connection.phase == com.devdrop.android.data.model.ConnectionPhase.Connected,
                    offers = state.incomingOffers,
                    offersError = state.incomingOffersError,
                    download = state.incomingDownload,
                    destinationPickerOpen = state.incomingDownload?.phase == com.devdrop.android.data.IncomingPhase.ChoosingDestination,
                    onRefresh = viewModel::refreshIncomingOffers,
                    onBack = { navController.popBackStack() },
                    onAccept = { offer ->
                        if (viewModel.beginIncomingAcceptance(offer)) receiveDestinationPicker.launch(offer.filename)
                    },
                    onReject = viewModel::rejectIncomingOffer,
                    onCancelDownload = viewModel::cancelIncomingDownload,
                    onRetryReceipt = viewModel::retryIncomingReceipt,
                )
            }
        }
    }
}
