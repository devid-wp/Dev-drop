"use strict";

const pages = ["dashboard", "devices", "transfers", "history", "security", "settings", "pairing-requests"];
const labels = {dashboard:"Overview",devices:"Devices",transfers:"Transfers",history:"History",security:"Security",settings:"Settings","pairing-requests":"Connection requests"};
const data = {status:null, sessions:[], discovered:[], requests:[], offers:[], history:[], pairingRequests:[], pairingQr:null, failures:{}};
let selectedRequest = null;
let selectedPairing = null;
let toastTimer = 0;
let refreshBusy = false;

const byId = id => document.getElementById(id);
const safe = (value, fallback="—") => value === null || value === undefined || value === "" ? fallback : String(value);
const escapeText = value => String(value ?? "");

async function api(path, options={}) {
  const response = await fetch(path, {cache:"no-store", credentials:"same-origin", redirect:"error", ...options,
    headers:{...(options.body ? {"Content-Type":"application/json"} : {}), ...(options.headers || {})}});
  let body = {};
  try { body = await response.json(); } catch (_) {}
  if (!response.ok) {
    const messages = {401:"The server refused this request. Reopen the panel from this computer.",403:"This action is available only to the local owner.",404:"This operation is not supported by this server version.",409:"The transfer changed state or is no longer available.",503:"The server could not read transfer history."};
    throw new Error((response.status === 403 && body.detail) || messages[response.status] || `Server returned HTTP ${response.status}.`);
  }
  return body;
}

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = escapeText(text);
  return el;
}
function empty(message, error=false) { return node("div", error ? "error-state" : "empty-state", message); }
function formatSize(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "Size unavailable";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB","MB","GB","TB","PB"];
  let size = bytes, index = -1;
  do { size /= 1024; index++; } while (size >= 1024 && index < units.length - 1);
  return `${size.toFixed(size >= 100 ? 0 : size >= 10 ? 1 : 2)} ${units[index]}`;
}
function formatTime(value) {
  if (!value) return "Time unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}
function onlyNumber(value) { const number=Number(value); return Number.isFinite(number) ? number : 0; }
function currentPage() {
  const page = location.hash.slice(1);
  return pages.includes(page) ? page : "dashboard";
}

function showPage() {
  const page = currentPage();
  byId("page-title").textContent = labels[page];
  document.querySelectorAll(".page").forEach(section => section.classList.toggle("active", section.id === `page-${page}`));
  document.querySelectorAll(".nav-link").forEach(link => {
    const active = link.dataset.page === page;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  if (page === "security") loadSecurity();
}

async function loadGroup(name, path, select) {
  try { data[name] = select(await api(path)); delete data.failures[name]; }
  catch (error) { data[name] = null; data.failures[name] = error.message || "Could not reach the server."; }
}
async function refresh() {
  if (refreshBusy) return;
  refreshBusy = true;
  byId("refresh").classList.add("spinning");
  await Promise.all([
    loadGroup("status", "/api/status", result => { if (result && typeof result === "object") delete result.pairing_code; return result; }),
    loadGroup("sessions", "/api/recipient-sessions", result => Array.isArray(result.sessions) ? result.sessions : []),
    loadGroup("discovered", "/api/discover", result => Array.isArray(result.servers) ? result.servers : []),
    loadGroup("requests", "/api/transfer-requests", result => Array.isArray(result.requests) ? result.requests : []),
    loadGroup("offers", "/api/outgoing-offers", result => Array.isArray(result.offers) ? result.offers : []),
    loadGroup("history", "/api/history", result => Array.isArray(result.transfers) ? result.transfers : []),
    loadGroup("pairingRequests", "/api/pairing/requests", result => Array.isArray(result.requests) ? result.requests : []),
    loadGroup("pairingQr", "/api/pairing/qr", result => result),
  ]);
  renderAll();
  byId("last-updated").textContent = `Updated ${new Date().toLocaleTimeString()}`;
  refreshBusy = false;
  byId("refresh").classList.remove("spinning");
}

function renderAll() {
  const ok = data.status !== null;
  const pill = byId("server-pill");
  pill.classList.toggle("offline", !ok);
  pill.querySelector("span").textContent = ok ? "Server online" : "Some data unavailable";
  byId("server-state").textContent = ok ? "Online" : "Unavailable";
  byId("server-address").textContent = `${location.protocol}//${location.host}`;
  byId("https-state").textContent = location.protocol === "https:" ? "HTTPS active" : "HTTPS required";
  byId("device-total").textContent = data.status === null ? "—" : String(onlyNumber(data.status.connected_devices));
  byId("setting-port").textContent = location.port || (location.protocol === "https:" ? "443" : "80");
  byId("setting-path").textContent = data.status === null ? "Unavailable" : safe(data.status.session_path,"Not configured");
  const pending = (data.requests || []).filter(item => item.status === "pending");
  byId("pending-count").hidden = pending.length === 0;
  byId("pending-count").textContent = String(pending.length);
  byId("request-count").textContent = `${pending.length} pending`;
  const activeStates = new Set(["pending", "accepted", "streaming", "preparing", "uploading"]);
  const active = (data.offers || []).filter(item => activeStates.has(item.status));
  byId("active-total").textContent = data.offers === null || data.requests === null ? "—" : String(active.length + pending.length);
  byId("active-caption").textContent = data.offers === null || data.requests === null ? "Transfer state unavailable" : "Pending approvals and outgoing offers";
  renderDevices(); renderRequests(); renderOffers(); renderHistory(); renderDashboard(); renderPairing();
}

function renderDevices() {
  const discovered = byId("discovered-devices"); discovered.replaceChildren();
  if (data.discovered === null) discovered.append(empty(data.failures.discovered || "Discovery is unavailable.", true));
  else {
    const others = data.discovered.filter(item => {
      try { return new URL(item.url).host !== location.host; } catch (_) { return true; }
    });
    if (!others.length) discovered.append(empty("No other Dev-Drop servers found."));
    for (const device of others) {
      const row=node("div","device-row"), avatar=node("span","device-avatar","D"), copy=node("div","device-copy");
      copy.append(node("strong","",safe(device.name,"Dev-Drop server")),node("small","device-address",safe(device.url,"Address unavailable")));
      row.append(avatar,copy,node("span","status-tag",safe(device.status,"Available"))); discovered.append(row);
    }
  }
  const paired=byId("paired-devices"); paired.replaceChildren();
  if(data.sessions===null) paired.append(empty(data.failures.sessions || "Paired sessions are unavailable.",true));
  else if(!data.sessions.length) paired.append(empty("No devices are paired right now."));
  else for(const session of data.sessions){
    const row=node("div","device-row"),avatar=node("span","device-avatar","◉"),copy=node("div","device-copy"),meta=node("small","device-meta");
    copy.append(node("strong","",safe(session.agent,"Paired device")));
    const peer=safe(session.peer,"Address unavailable"), id=safe(session.id,"");
    meta.textContent=`${peer}${id ? ` · ID ${id.slice(0,8)}` : ""}`;copy.append(meta);row.append(avatar,copy,node("span","status-dot"));paired.append(row);
  }
}

function requestFiles(request) {
  const files = Array.isArray(request.files) ? request.files : [];
  if (files.length) return files.map(file => `${safe(file.name,"Unnamed file")} (${formatSize(file.size)})`).join(" · ");
  return safe(request.description || request.type, "Transfer details unavailable");
}
function renderRequests() {
  const target=byId("pending-transfers");target.replaceChildren();
  if(data.requests===null){target.append(empty(data.failures.requests || "Requests are unavailable.",true));return;}
  const requests=data.requests.filter(item=>item.status==="pending");
  if(!requests.length){target.append(empty("No transfer requests need your decision."));return;}
  for(const item of requests){
    const row=node("div","transfer-row"),icon=node("span","file-icon",item.type==="text"?"T":"↧"),copy=node("div","transfer-copy"),actions=node("div","transfer-actions");
    copy.append(node("strong","",requestFiles(item)),node("small","",`${safe(item.sender,"Unknown sender")} · ${formatSize(item.size)} · ${formatTime(item.created_at)}`));
    const reject=node("button","reject-button","Reject"),approve=node("button","approve-button","Review & approve");
    reject.type=approve.type="button";reject.addEventListener("click",()=>openDecision(item,"reject"));approve.addEventListener("click",()=>openDecision(item,"approve"));
    actions.append(reject,approve);row.append(icon,copy,actions);target.append(row);
  }
}
function openDecision(item, decision) {
  selectedRequest=item;
  byId("dialog-title").textContent=decision==="approve"?"Approve this transfer?":"Reject this transfer?";
  const detail=byId("dialog-details");detail.replaceChildren();
  const lines=[["Files",requestFiles(item)],["Size",formatSize(item.size)],["Sender",safe(item.sender,"Unknown sender")],["Request type",safe(item.type,"Unknown")],["Created",formatTime(item.created_at)]];
  for(const [label,value] of lines){const row=node("div","detail-line"),k=node("span","",label),v=node("strong","",value);row.append(k,v);detail.append(row);}
  const approve=byId("dialog-approve"),reject=byId("dialog-reject");approve.hidden=decision!=="approve";reject.hidden=decision!=="reject";
  byId("decision-dialog").showModal();
}
async function decide(decision) {
  if(!selectedRequest)return;
  const id=String(selectedRequest.id || "");
  if(!/^[A-Za-z0-9_-]{1,128}$/.test(id)){showToast("The server returned an invalid request ID.",true);return;}
  const button=byId(decision==="approve"?"dialog-approve":"dialog-reject");button.disabled=true;
  try { await api(`/api/transfer-requests/${encodeURIComponent(id)}/${decision}`,{method:"POST",body:"{}"});byId("decision-dialog").close();showToast(decision==="approve"?"Transfer approved.":"Transfer rejected.");await refresh(); }
  catch(error){byId("decision-dialog").close();showToast(error.message || "The decision could not be saved.",true);await refresh();}
  finally {button.disabled=false;selectedRequest=null;}
}

function renderOffers() {
  const target=byId("outgoing-transfers");target.replaceChildren();
  if(data.offers===null){target.append(empty(data.failures.offers || "Outgoing transfers are unavailable.",true));return;}
  if(!data.offers.length){target.append(empty("No outgoing transfers."));return;}
  const table=node("table"),thead=node("thead"),header=node("tr");
  for(const label of ["File","Recipient","Progress","Status"]){header.append(node("th","",label));}thead.append(header);table.append(thead);
  const body=node("tbody");
  for(const item of data.offers){
    const row=node("tr"),file=node("td","",safe(item.filename,"Unnamed file")),recipient=node("td","",safe(item.recipient_id,"Paired device")),progress=node("td","progress-cell"),status=node("td");
    const size=Number(item.size),sent=onlyNumber(item.sent_bytes);
    if(Number.isFinite(size)&&size>=0){const pct=size===0?(item.status==="sent"?100:0):Math.min(100,Math.floor(sent/size*100));const bar=node("progress","progress-bar");bar.max=Math.max(1,size);bar.value=Math.min(sent,size);bar.setAttribute("aria-label",`${formatSize(sent)} of ${formatSize(size)} sent`);progress.append(bar,node("small","progress-label",`${formatSize(sent)} / ${formatSize(size)} · ${pct}%`));}
    else progress.textContent="Progress unavailable";
    const badge=node("span",`status-tag ${safe(item.status,"")}`,safe(item.status,"Unknown"));status.append(badge);row.append(file,recipient,progress,status);body.append(row);
  }
  table.append(body);target.append(table);
}
function renderHistory() {
  const target=byId("history-list");target.replaceChildren();
  if(data.history===null){target.append(empty(data.failures.history || "History is unavailable.",true));return;}
  if(!data.history.length){target.append(empty("No completed transfers have been recorded."));return;}
  const table=node("table"),thead=node("thead"),head=node("tr");
  for(const label of ["File","Direction","Size","Received from","Time","Status"]){head.append(node("th","",label));}thead.append(head);table.append(thead);
  const body=node("tbody");
  for(const item of [...data.history].reverse()){
    const row=node("tr");row.append(node("td","",safe(item.filename,"Unnamed file")),node("td","","Received"),node("td","",formatSize(item.size)),node("td","",safe(item.sender_ip,"Unknown")),node("td","",formatTime(item.timestamp)));
    const state=node("td"),badge=node("span","status-tag saved","Saved");state.append(badge);row.append(state);body.append(row);
  }
  table.append(body);target.append(table);
}
function renderDashboard() {
  const activity=byId("recent-activity");activity.replaceChildren();
  if(data.history===null)activity.append(empty(data.failures.history || "Activity is unavailable.",true));
  else if(!data.history.length)activity.append(empty("No recent activity yet."));
  else for(const item of [...data.history].reverse().slice(0,5)){
    const row=node("div","activity-row"),dot=node("span","activity-dot","↓"),copy=node("div","activity-copy");
    copy.append(node("strong","",safe(item.filename,"Unnamed file")),node("small","",`${formatTime(item.timestamp)} · ${safe(item.sender_ip,"Unknown sender")}`));row.append(dot,copy,node("span","activity-size",formatSize(item.size)));activity.append(row);
  }
  const devices=byId("dashboard-devices");devices.replaceChildren();
  if(data.sessions===null)devices.append(empty(data.failures.sessions || "Device list is unavailable.",true));
  else if(!data.sessions.length)devices.append(empty("No paired devices."));
  else for(const session of data.sessions.slice(0,4)){
    const row=node("div","compact-device"),avatar=node("span","device-avatar","◉"),copy=node("div","device-copy");copy.append(node("strong","",safe(session.agent,"Paired device")),node("small","",safe(session.peer,"Address unavailable")));row.append(avatar,copy,node("span","status-dot"));devices.append(row);
  }
}
async function loadSecurity() {
  byId("https-state").textContent=location.protocol==="https:"?"HTTPS active":"HTTPS required";
  if(location.protocol!=="https:"){byId("pairing-state").textContent="Pairing requires HTTPS.";return;}
}
function renderPairing(){
  const result=data.pairingQr, image=byId("pairing-qr"), emptyState=byId("pairing-qr-empty");
  if(!result){byId("pairing-state").textContent=data.failures.pairingQr||"Secure pairing unavailable.";image.classList.remove("visible");emptyState.classList.remove("hidden");emptyState.textContent="QR unavailable";}
  else if(result.state==="waiting_for_owner"){
    byId("pairing-state").textContent="A phone is waiting for owner approval.";byId("pairing-expiry").textContent=`Request expires in ${result.expires_in} seconds.`;image.classList.remove("visible");emptyState.classList.remove("hidden");emptyState.textContent="Approve the phone below";
  } else {
    byId("pairing-state").textContent="Ready to scan";byId("pairing-expiry").textContent=`One use · expires in ${result.expires_in} seconds`;
    if(result.qr_svg){image.src=`data:image/svg+xml;charset=utf-8,${encodeURIComponent(result.qr_svg)}`;image.classList.add("visible");emptyState.classList.add("hidden");}
  }
  const target=byId("pairing-requests");target.replaceChildren();
  if(data.pairingRequests===null){target.append(empty(data.failures.pairingRequests||"Connection requests are unavailable.",true));return;}
  if(!data.pairingRequests.length){target.append(empty("No phone is waiting to connect."));return;}
  for(const item of data.pairingRequests){
    const row=node("div","transfer-row"),icon=node("span","file-icon","◉"),copy=node("div","transfer-copy"),actions=node("div","pair-request-actions");
    copy.append(node("strong","",safe(item.device,"Android phone")),node("small","",`${safe(item.peer,"Address unavailable")} · expires in ${item.expires_in}s`));
    const reject=node("button","reject-button","Reject"),approve=node("button","approve-button","Check code & approve");reject.type=approve.type="button";reject.onclick=()=>rejectPairing(item);approve.onclick=()=>openPairingDialog(item);actions.append(reject,approve);row.append(icon,copy,actions);target.append(row);
  }
}
function openPairingDialog(item){selectedPairing=item;byId("pairing-dialog-title").textContent=`Connect ${safe(item.device,"this phone")}?`;byId("pairing-dialog-copy").textContent=`Request from ${safe(item.peer,"unknown address")}. Compare the code shown on the phone before approving.`;byId("pairing-confirmation-code").value="";byId("pairing-dialog").showModal();byId("pairing-confirmation-code").focus();}
async function decidePairing(approve){
  if(!selectedPairing)return;
  const id=encodeURIComponent(selectedPairing.attempt_id), code=byId("pairing-confirmation-code").value;
  if(approve&&!/^\d{6}$/.test(code)){showToast("Enter the six digit code shown on the phone.",true);return;}
  try{await api(`/api/pairing/requests/${id}/${approve?"approve":"reject"}`,{method:"POST",body:approve?JSON.stringify({code}):"{}"});byId("pairing-dialog").close();selectedPairing=null;showToast(approve?"Phone approved and paired.":"Connection request rejected.");await refresh();}
  catch(error){showToast(error.message||"Could not update pairing request.",true);await refresh();}
}
async function rejectPairing(item){selectedPairing=item;await decidePairing(false);}
function showToast(message,error=false){const toast=byId("toast");toast.textContent=message;toast.classList.toggle("error",error);toast.classList.add("show");window.clearTimeout(toastTimer);toastTimer=window.setTimeout(()=>toast.classList.remove("show"),3500);}

document.querySelectorAll(".nav-link").forEach(link=>link.addEventListener("click",()=>{if(link.dataset.page)showPage();}));
document.querySelectorAll(".refresh-page").forEach(button=>button.addEventListener("click",refresh));
byId("refresh").addEventListener("click",refresh);
byId("dialog-approve").addEventListener("click",event=>{event.preventDefault();decide("approve");});
byId("dialog-reject").addEventListener("click",event=>{event.preventDefault();decide("reject");});
byId("pairing-approve").addEventListener("click",event=>{event.preventDefault();decidePairing(true);});
window.addEventListener("hashchange",showPage);
window.setInterval(refresh,15000);
showPage();refresh();
