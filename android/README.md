# Dev-Drop Android

Native Android client scaffold built with Kotlin, Jetpack Compose, Material 3,
Navigation Compose, ViewModel and StateFlow. It currently provides the four
navigation destinations and Android system file pickers. Discovery, server
connection, transfer history and sending are intentionally not wired yet, so the
app does not show devices or successful transfers that it has not observed.

## Build

Requirements: JDK 17 and Android SDK Platform 35. From this directory run:

```sh
./gradlew :app:assembleDebug :app:testDebugUnitTest
```

The app supports Android API 26 and later. File selection uses the Android Photo
Picker for photos/videos and the Storage Access Framework for other files; no
broad storage permission is requested. Network access and TLS trust provisioning
are not implemented yet. See [API integration notes](docs/API_INTEGRATION.md)
before connecting this client to a Dev-Drop server.
