package com.devdrop.android.data.model

data class IncomingFileOffer(
    val id: String,
    val filename: String,
    val size: Long,
    val sha256: String,
    val sender: String,
    val status: String,
    val createdAt: Double,
    val expiresAt: Double,
)
