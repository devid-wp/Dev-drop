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

const incomingFiles = document.querySelector("#incoming-files");
const incomingStatus = document.querySelector("#incoming-status");
let incomingTimer = null;
let incomingBusy = false;
const relayRecipient = document.querySelector("#relay-recipient");
const relayOutgoing = document.querySelector("#relay-outgoing");
let activeRelay = null;
let fileSendBusy = false;
let sessionToken = null;
let currentMode = "text";
let selectedFiles = [];
let previewUrl = null;
let sendResetTimer = null;
let isCameraMode = false;

discoverServers();

async function discoverServers() {
    if (window.location.protocol !== "https:") return;
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
                // Discovery is unauthenticated. Do not navigate to another identity.
                if (url.protocol === "https:" && url.origin === window.location.origin) {
                    window.location.href = url.href;
                }
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
    if (window.location.protocol !== "https:") {
        showPairingStatus("Trusted HTTPS is required. Do not pair over HTTP.", true);
        return;
    }
    const code = pairingInput.value.replace(/\D/g, "");

    if (code.length !== 9) {
        showPairingStatus("Enter a 9-digit code", true);
        return;
    }

    pairingButton.disabled = true;
    pairingButton.textContent = "Connecting...";

    try {
        const response = await fetch("/api/pair", {
            redirect: "error",
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code }),
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Pairing failed");
        }

        if (!data.paired || typeof data.token !== "string" || !data.token) {
            throw new Error("Pairing failed");
        }
        sessionToken = data.token;
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

async function sha256(buffer) {
    if (window.location.protocol !== "https:" || !globalThis.crypto?.subtle) {
        throw new Error("Trusted HTTPS is required");
    }
    const digest = await globalThis.crypto.subtle.digest("SHA-256", buffer);
    return Array.from(new Uint8Array(digest), x => x.toString(16).padStart(2, "0")).join("");
}

async function requestApproval(description) {
    const relay = Boolean(description.recipient_id);
    const response = await authorizedFetch(relay ? "/api/relays" : "/api/transfer-requests", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({sender: "Browser (unverified)", ...description}),
    });
    if (!response.ok) throw new Error("Could not request approval");
    const transfer = await response.json();
    if (relay) activeRelay = {id: transfer.id, controller: new AbortController()};
    sendButton.textContent = "Waiting for approval...";
    const deadline = Date.now() + 125000;
    while (Date.now() < deadline) {
        const status = await authorizedFetch(`${relay ? "/api/relays" : "/api/transfer-requests"}/${transfer.id}`, {});
        if (!status.ok) throw new Error("Transfer request unavailable");
        const current = await status.json();
        if (current.status === "approved" && !current.used) return transfer.id;
        if (current.status !== "pending") throw new Error(`Transfer ${current.status}`);
        await new Promise(resolve => window.setTimeout(resolve, 1000));
    }
    throw new Error("Approval expired. Try again.");
}

async function sendText() {
    const content = textContent.value.trim();

    if (!content) {
        showTransferError("Paste some text first");
        textContent.focus();
        return;
    }

    setSending();

    try {
        const bytes = new TextEncoder().encode(content);
        const identity = await requestApproval({type: "text", description: content.slice(0, 200),
            size: bytes.length, sha256: await sha256(bytes.buffer)});
        const response = await authorizedFetch("/api/text", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Transfer-ID": identity },
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
    if (fileSendBusy) return;
    if (!selectedFiles || selectedFiles.length === 0) {
        showTransferError("Choose a file first");
        return;
    }

    const recipient = relayRecipient.value;
    if (recipient && selectedFiles.length !== 1) {
        showTransferError("Choose exactly one file for relay");
        return;
    }
    fileSendBusy = true;
    relayRecipient.disabled = true;
    setSending();
    const files = selectedFiles.slice();
    const formData = new FormData();
    
    for (let i = 0; i < files.length; i++) {
        formData.append("files", files[i], files[i].name);
    }

    try {
        const manifest = [];
        for (const file of files) {
            manifest.push({name: file.name, size: file.size, sha256: await sha256(await file.arrayBuffer())});
        }
        const identity = await requestApproval({type: "file", description: files.map(f => f.name).join(", ").slice(0, 500),
            size: files.reduce((total, file) => total + file.size, 0), files: manifest,
            ...(recipient ? {recipient_id: recipient} : {})});
        if (recipient) transferStatus.textContent = "Uploading through computer...";
        const response = await authorizedFetch(recipient ? `/api/relays/${identity}/upload` : "/api/upload", {
            method: "POST",
            signal: recipient ? activeRelay.controller.signal : undefined,
            headers: recipient ? {} : {"X-Transfer-ID": identity},
            body: formData,
        });

        if (!response.ok) {
            const text = await response.text();
            throw new Error(text || "Could not send file");
        }

        const data = await response.json();
        clearSelectedFile();
        showSent();
        if (recipient) {
            sendButton.textContent = "Offered";
            transferStatus.textContent = "Uploaded to computer. Waiting for recipient Accept.";
            refreshIncoming();
        }
    } catch (error) {
        showSendFailure(error.name === "AbortError" ? "Relay cancelled" : (error.message || "Could not send file"));
    } finally {
        fileSendBusy = false;
        relayRecipient.disabled = false;
        activeRelay = null;
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

function returnToPairing() {
    window.clearInterval(incomingTimer);
    incomingTimer = null;
    incomingFiles.replaceChildren();
    relayOutgoing.replaceChildren();
    relayRecipient.replaceChildren();
    document.querySelector("#incoming-session").textContent = "";
    sessionToken = null;
    transferScreen.classList.add("hidden");
    pairingScreen.classList.remove("hidden");
    pairingInput.disabled = false;
    pairingInput.value = "";
    pairingButton.disabled = false;
    pairingButton.textContent = "Connect";
    resetSendFeedback();
    showPairingStatus("Session expired. Connect again.", true);
}

async function authorizedFetch(url, options) {
    if (window.location.protocol !== "https:") {
        returnToPairing();
        throw new Error("Trusted HTTPS is required");
    }
    if (!sessionToken) {
        returnToPairing();
        throw new Error("Connect again");
    }
    const response = await fetch(url, {
        ...options,
        redirect: "error",
        headers: { ...options.headers, Authorization: `Bearer ${sessionToken}` },
    });
    if (response.status === 401) {
        returnToPairing();
        throw new Error("Session expired. Connect again.");
    }
    return response;
}

function openTransferScreen() {
    if (!sessionToken) return;
    pairingScreen.classList.add("hidden");
    transferScreen.classList.remove("hidden");
    textContent.focus();
    window.clearInterval(incomingTimer);
    incomingTimer = window.setInterval(refreshIncoming, 2000);
    refreshIncoming();
}

async function refreshIncoming() {
    if (incomingBusy || !sessionToken) return;
    incomingBusy = true;
    const token = sessionToken;
    try {
        const response = await authorizedFetch("/api/incoming-offers", {cache: "no-store"});
        if (!response.ok) throw new Error("Could not load incoming files");
        const data = await response.json();
        if (token !== sessionToken) return;
        incomingFiles.replaceChildren();
        document.querySelector("#incoming-session").textContent = data.session_id ? `This browser: ${data.session_id.slice(0, 8)}` : "";
        for (const offer of data.offers || []) {
            const row = document.createElement("div");
            const label = document.createElement("p");
            label.textContent = `${offer.filename} | ${formatFileSize(offer.size)} | ${offer.sender} | ${offer.status}`;
            row.appendChild(label);
            if (offer.status === "pending") {
                for (const decision of ["accept", "reject"]) {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.textContent = decision === "accept" ? "Accept" : "Reject";
                    button.addEventListener("click", () => decideIncoming(offer, decision, row));
                    row.appendChild(button);
                }
            } else if (offer.status === "accepted") {
                addDownloadLink(offer, row);
            }
            incomingFiles.appendChild(row);
        }
        await refreshRelayState(token);
    } catch (error) {
        incomingStatus.textContent = error.message || "Incoming files unavailable";
    } finally {
        incomingBusy = false;
    }
}

async function refreshRelayState(token) {
    const recipients = await authorizedFetch("/api/relay-recipients", {cache: "no-store"});
    const outgoing = await authorizedFetch("/api/relays", {cache: "no-store"});
    if (!recipients.ok || !outgoing.ok) throw new Error("Relay state unavailable");
    const peers = await recipients.json();
    const transfers = await outgoing.json();
    if (token !== sessionToken) return;
    const selected = relayRecipient.value;
    relayRecipient.replaceChildren();
    const local = document.createElement("option");
    local.value = "";
    local.textContent = "This computer";
    relayRecipient.appendChild(local);
    for (const peer of peers.sessions || []) {
        const option = document.createElement("option");
        option.value = peer.id;
        option.textContent = `Session ${peer.id.slice(0, 8)}`;
        relayRecipient.appendChild(option);
    }
    relayRecipient.value = (peers.sessions || []).some(peer => peer.id === selected) ? selected : "";
    relayOutgoing.replaceChildren();
    for (const relay of transfers.relays || []) {
        const row = document.createElement("div");
        const label = document.createElement("p");
        label.textContent = `${relay.filename} → session ${relay.recipient_id.slice(0, 8)}: ${relay.status}`;
        row.appendChild(label);
        if (["pending", "approved", "uploading", "offered", "accepted", "streaming"].includes(relay.status)) {
            const cancel = document.createElement("button");
            cancel.type = "button";
            cancel.textContent = "Cancel relay";
            cancel.addEventListener("click", async () => {
                try {
                    const response = await authorizedFetch(`/api/relays/${encodeURIComponent(relay.id)}/cancel`, {method: "POST"});
                    if (!response.ok) throw new Error("Relay can no longer be cancelled");
                    if (activeRelay?.id === relay.id) activeRelay.controller.abort();
                    transferStatus.textContent = "Relay cancelled";
                    refreshIncoming();
                } catch (error) { showTransferError(error.message); }
            });
            row.appendChild(cancel);
        }
        relayOutgoing.appendChild(row);
    }
}

function addDownloadLink(offer, row) {
    const link = document.createElement("a");
    link.href = `/api/incoming-offers/${encodeURIComponent(offer.id)}/download`;
    link.download = offer.filename;
    link.textContent = "Download";
    link.referrerPolicy = "no-referrer";
    row.appendChild(link);
}

async function decideIncoming(offer, decision, row) {
    const token = sessionToken;
    try {
        const response = await authorizedFetch(`/api/incoming-offers/${encodeURIComponent(offer.id)}/${decision}`, {method: "POST"});
        if (!response.ok) throw new Error("Offer expired or is no longer available");
        const current = await response.json();
        if (token !== sessionToken) return;
        row.replaceChildren();
        const label = document.createElement("p");
        label.textContent = `${offer.filename}: ${current.status}`;
        row.appendChild(label);
        if (decision === "accept") {
            addDownloadLink(offer, row);
            incomingStatus.textContent = "Accepted. Tap Download to save the file.";
        } else {
            incomingStatus.textContent = "File rejected";
        }
    } catch (error) {
        incomingStatus.textContent = error.message;
    }
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
