"use strict";

const pairingForm = document.querySelector(".pairing-form");
const pairingInput = document.querySelector("#pair-code");
const pairingButton = pairingForm.querySelector("button");
const pairingScreen = document.querySelector(".card");
const transferScreen = document.querySelector("#transfer-screen");
const modeButtons = document.querySelectorAll(".mode");
const textPanel = document.querySelector("#text-panel");
const filePanel = document.querySelector("#file-panel");
const textContent = document.querySelector("#text-content");
const uploadButton = document.querySelector("#upload-button");
const cameraButton = document.querySelector("#camera-button");
const fileInput = document.querySelector("#file-input");
const cameraInput = document.querySelector("#camera-input");
const dropZone = document.querySelector("#drop-zone");
const emptyFileState = document.querySelector("#empty-file-state");
const filePreview = document.querySelector("#file-preview");
const fileName = document.querySelector("#file-name");
const fileSize = document.querySelector("#file-size");
const imagePreview = document.querySelector("#image-preview");
const removeFileButton = document.querySelector("#remove-file");
const sendButton = document.querySelector("#send-button");
const transferStatus = document.querySelector("#transfer-status");
const discoveredServers = document.querySelector("#discovered-servers");
const serverList = document.querySelector("#server-list");

let currentMode = "text";
let selectedFiles = [];
let previewUrl = null;
let sendResetTimer = null;
let isCameraMode = false;

discoverServers();

async function discoverServers() {
    try {
        const response = await fetch("/api/discover", { cache: "no-store" });
        if (!response.ok) return;

        const data = await response.json();
        const servers = Array.isArray(data.servers) ? data.servers : [];
        serverList.replaceChildren();

        servers.forEach((server) => {
            const button = document.createElement("button");
            button.className = "discovered-server";
            button.type = "button";
            button.innerHTML = `<strong>${escapeHtml(server.name || "DevDrop")}</strong>`
                + `<span>${escapeHtml(server.ip || "Unknown IP")}</span>`
                + `<em>${escapeHtml(server.status || "Available")}</em>`;
            button.addEventListener("click", () => {
                const url = new URL(server.url, window.location.href);
                window.location.href = url.href;
            });
            serverList.appendChild(button);
        });

        discoveredServers.hidden = servers.length === 0;
    } catch (_error) {
        discoveredServers.hidden = true;
    }
}

function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (character) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "'": "&#39;",
        '"': "&quot;",
    }[character]));
}

pairingForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const code = pairingInput.value.replace(/\D/g, "");

    if (code.length !== 9) {
        showPairingStatus("Enter a 9-digit code", true);
        return;
    }

    pairingButton.disabled = true;
    pairingButton.textContent = "Connecting...";

    try {
        const response = await fetch("/api/pair", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code }),
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Pairing failed");
        }

        showPairingStatus("Connected ✓", false);
        pairingButton.textContent = "Connected";
        pairingInput.disabled = true;
        window.setTimeout(openTransferScreen, 250);
    } catch (error) {
        showPairingStatus(error.message || "Pairing failed", true);
        pairingButton.disabled = false;
        pairingButton.textContent = "Connect";
    }
});

pairingInput.addEventListener("input", () => {
    const digits = pairingInput.value.replace(/\D/g, "").slice(0, 9);
    pairingInput.value = (digits.match(/.{1,3}/g) || []).join(" ");
});

modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
        currentMode = button.dataset.mode;
        modeButtons.forEach((item) => item.classList.toggle("active", item === button));
        textPanel.classList.toggle("hidden", currentMode !== "text");
        filePanel.classList.toggle("hidden", currentMode !== "file");
        resetSendFeedback();
    });
});

uploadButton.addEventListener("click", () => fileInput.click());
cameraButton.addEventListener("click", () => cameraInput.click());
fileInput.addEventListener("change", () => {
    isCameraMode = false;
    selectFiles(fileInput.files);
});
cameraInput.addEventListener("change", () => {
    isCameraMode = true;
    selectFiles(cameraInput.files);
});

dropZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
});

dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));

dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
    isCameraMode = false;
    selectFiles(event.dataTransfer.files);
});

removeFileButton.addEventListener("click", clearSelectedFile);

sendButton.addEventListener("click", async () => {
    if (currentMode === "text") {
        await sendText();
    } else {
        await sendFile();
    }
});

async function sendText() {
    const content = textContent.value.trim();

    if (!content) {
        showTransferError("Paste some text first");
        textContent.focus();
        return;
    }

    setSending();

    try {
        const response = await fetch("/api/text", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content }),
        });

        if (!response.ok) {
            const text = await response.text();
            throw new Error(text || "Could not send text");
        }

        const data = await response.json();
        textContent.value = "";
        showSent();
    } catch (error) {
        showSendFailure(error.message || "Could not send text");
    }
}

async function sendFile() {
    if (!selectedFiles || selectedFiles.length === 0) {
        showTransferError("Choose a file first");
        return;
    }

    setSending();
    const formData = new FormData();
    
    for (let i = 0; i < selectedFiles.length; i++) {
        formData.append("files", selectedFiles[i], selectedFiles[i].name);
    }

    try {
        const response = await fetch("/api/upload", {
            method: "POST",
            body: formData,
        });

        if (!response.ok) {
            const text = await response.text();
            throw new Error(text || "Could not send file");
        }

        const data = await response.json();
        clearSelectedFile();
        showSent();
    } catch (error) {
        showSendFailure(error.message || "Could not send file");
    }
}

function selectFiles(fileList) {
    if (!fileList || fileList.length === 0) return;

    clearPreviewUrl();
    selectedFiles = Array.from(fileList);
    
    // For camera mode, treat as single file even if multiple files somehow selected
    if (isCameraMode && selectedFiles.length > 0) {
        selectedFiles = selectedFiles.slice(0, 1);
    }
    
    updateFilePreviewDisplay();
    resetSendFeedback();
}

function updateFilePreviewDisplay() {
    emptyFileState.classList.add("hidden");
    filePreview.classList.remove("hidden");
    
    if (selectedFiles.length === 1) {
        const file = selectedFiles[0];
        fileName.textContent = file.name;
        fileSize.textContent = formatFileSize(file.size);
        
        if (file.type.startsWith("image/")) {
            previewUrl = URL.createObjectURL(file);
            imagePreview.src = previewUrl;
            imagePreview.classList.remove("hidden");
        } else {
            imagePreview.removeAttribute("src");
            imagePreview.classList.add("hidden");
        }
    } else {
        const totalSize = selectedFiles.reduce((sum, file) => sum + file.size, 0);
        fileName.textContent = `${selectedFiles.length} files selected`;
        fileSize.textContent = formatFileSize(totalSize);
        imagePreview.removeAttribute("src");
        imagePreview.classList.add("hidden");
    }
}

function clearSelectedFile() {
    selectedFiles = [];
    isCameraMode = false;
    fileInput.value = "";
    cameraInput.value = "";
    clearPreviewUrl();
    imagePreview.removeAttribute("src");
    imagePreview.classList.add("hidden");
    filePreview.classList.add("hidden");
    emptyFileState.classList.remove("hidden");
}

function clearPreviewUrl() {
    if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
        previewUrl = null;
    }
}

function formatFileSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function showPairingStatus(message, isError) {
    let status = document.querySelector(".pair-status");

    if (!status) {
        status = document.createElement("p");
        status.className = "pair-status";
        status.setAttribute("aria-live", "polite");
        pairingForm.appendChild(status);
    }

    status.textContent = message;
    status.classList.toggle("error", isError);
}

function openTransferScreen() {
    pairingScreen.classList.add("hidden");
    transferScreen.classList.remove("hidden");
    textContent.focus();
}

function setSending() {
    window.clearTimeout(sendResetTimer);
    sendButton.disabled = true;
    sendButton.textContent = "Sending...";
    transferStatus.textContent = "";
    transferStatus.classList.remove("error");
}

function showSent() {
    sendButton.textContent = "Sent ✓";
    sendResetTimer = window.setTimeout(resetSendFeedback, 1200);
}

function showSendFailure(message) {
    sendButton.textContent = "Failed";
    showTransferError(message);
    sendResetTimer = window.setTimeout(() => {
        sendButton.textContent = "Send";
        sendButton.disabled = false;
    }, 1400);
}

function showTransferError(message) {
    transferStatus.textContent = message;
    transferStatus.classList.add("error");
}

function resetSendFeedback() {
    window.clearTimeout(sendResetTimer);
    sendButton.textContent = "Send";
    sendButton.disabled = false;
    transferStatus.textContent = "";
    transferStatus.classList.remove("error");
}
