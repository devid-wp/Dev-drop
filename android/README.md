# Dev-Drop Android

Native Android client scaffold built with Kotlin, Jetpack Compose, Material 3,
Navigation Compose, ViewModel and StateFlow. It currently provides the four
navigation destinations and Android system file pickers. It implements real
server discovery, pinned-CA HTTPS pairing, session restore, phone-to-PC uploads
with owner approval, and PC-to-phone incoming offers with one-use download
authorization and streamed SAF saving.

## Build

Requirements: JDK 17 and Android SDK Platform 35. From this directory run:

```sh
./gradlew :app:assembleDebug :app:testDebugUnitTest
```

The app supports Android API 26 and later. It uses the Android Photo Picker and
Storage Access Framework; no broad storage permission is requested. The debug
APK requires a server provisioned with the Dev-Drop HTTPS certificate and CA.
Disconnect revokes the current Bearer session when online. Incoming files are
confirmed by the backend only after the SAF output is closed and Android posts
the verified size and SHA-256. If that receipt request is interrupted, retry
the confirmation without downloading the file again. See
[API integration notes](docs/API_INTEGRATION.md) for routes and limitations.
