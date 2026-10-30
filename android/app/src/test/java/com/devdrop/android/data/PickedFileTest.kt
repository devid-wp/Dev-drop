package com.devdrop.android.data

import org.junit.Assert.assertEquals
import org.junit.Test

class PickedFileTest {
    @Test
    fun formatsKnownAndUnknownSizes() {
        assertEquals("0 B", formatFileSize(0))
        assertEquals("1.0 KB", formatFileSize(1024))
        assertEquals("1.0 MB", formatFileSize(1024L * 1024))
        assertEquals("Size unavailable", formatFileSize(null))
        assertEquals("Size unavailable", formatFileSize(-1))
    }
}
