const state = {
  ws: null,
  roomId: null,
  name: null,
  clientId: null,
  peers: new Map(),
  localStream: null,
  muted: false,
  analyser: null,
  vadInterval: null,
  pitchInterval: null,
};

const el = (id) => document.getElementById(id);
const peersList = el('peers');
const videos = el('videos');
const messages = el('messages');
const alertModal = () => document.getElementById('alertModal');
const toastsEl = () => document.getElementById('toasts');

function toast(text){
  const c = toastsEl();
  if (!c) return;
  const t = document.createElement('div');
  t.className = 'toast';
  t.innerHTML = `<span class="title">Notification</span>${text}`;
  c.appendChild(t);
  setTimeout(()=>{ if (t.parentNode) t.parentNode.removeChild(t); }, 3500);
}

function showAlert(html){
  const modal = alertModal();
  if (!modal) return;
  document.getElementById('alertBody').innerHTML = html;
  modal.classList.remove('hidden');
}
function hideAlert(){ const modal = alertModal(); if (!modal) return; modal.classList.add('hidden'); }

function appendMessage(text, me = false) {
  const div = document.createElement('div');
  div.className = `msg ${me ? 'me' : 'other'}`;
  div.textContent = text;
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

function updateAuthState(){
  const token = localStorage.getItem('whop_token');
  const a = document.getElementById('authState');
  if (!a) return;
  a.textContent = token ? 'Signed in with Whop' : 'Not signed in';
}

function ensureTileElements(clientId, name, isLocal=false) {
  let wrap = document.getElementById(`tile-${clientId}`);
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.className = 'video-wrap';
    wrap.id = `tile-${clientId}`;
    const ring = document.createElement('div'); ring.className = 'vad-ring'; ring.id = `ring-${clientId}`;
    const title = document.createElement('h4'); title.textContent = name + (isLocal ? ' (you)' : ''); title.id = `name-${clientId}`;
    const badge = document.createElement('div'); badge.className = 'badge'; badge.id = `badge-${clientId}`;
    const pitch = document.createElement('div'); pitch.className = 'pitch'; pitch.id = `pitch-${clientId}`; pitch.textContent = '';
    const video = document.createElement('video'); video.autoplay = true; video.playsInline = true; video.muted = isLocal; video.id = `video-${clientId}`;
    wrap.appendChild(ring); wrap.appendChild(title); wrap.appendChild(badge); wrap.appendChild(video); wrap.appendChild(pitch);
    videos.appendChild(wrap);
  }
  return wrap;
}

function addPeerTile(clientId, name, stream, isLocal=false) {
  ensureTileElements(clientId, name, isLocal);
  const video = document.getElementById(`video-${clientId}`);
  if (video) {
    video.srcObject = stream;
    video.muted = isLocal; // Ensure local video is muted to prevent feedback
    // Force audio context to be active for better audio handling
    if (!isLocal) {
      video.addEventListener('loadedmetadata', async () => {
        try {
          await video.play();
          console.log(`Audio/video playing for ${clientId}`);
        } catch (e) {
          console.warn(`Autoplay failed for ${clientId}:`, e);
          // Try user gesture fallback
          document.addEventListener('click', async () => {
            try { await video.play(); } catch(_) {}
          }, { once: true });
        }
      });
    }
  }
}

function setPitchUI(clientId, hz){
  const elp = document.getElementById(`pitch-${clientId}`);
  const ring = document.getElementById(`ring-${clientId}`);
  if (!elp) return;
  
  // Clear previous pitch classes
  elp.classList.remove('low', 'mid', 'high', 'very-high');
  if (ring) ring.classList.remove('low', 'mid', 'high', 'very-high');
  
  if (!hz || hz <= 0) { 
    elp.textContent = ''; 
    return; 
  }
  
  const display = `${Math.round(hz)} Hz`;
  elp.textContent = display;
  
  // Apply pitch-based color classes
  let pitchClass = '';
  if (hz < 150) {
    pitchClass = 'low'; // Deep voice - Blue
  } else if (hz < 250) {
    pitchClass = 'mid'; // Normal voice - Green  
  } else if (hz < 350) {
    pitchClass = 'high'; // High voice - Orange
  } else {
    pitchClass = 'very-high'; // Very high voice - Red
  }
  
  elp.classList.add(pitchClass);
  if (ring) ring.classList.add(pitchClass);
}

function removePeerTile(clientId) {
  const wrap = document.getElementById(`tile-${clientId}`);
  if (wrap && wrap.parentNode) wrap.parentNode.removeChild(wrap);
}

function renderPeersList(peers) {
  peersList.innerHTML = '';
  peers.forEach((p) => {
    const li = document.createElement('li');
    li.textContent = `${p.name} (${p.clientId})`;
    peersList.appendChild(li);
  });
}

function mediaConstraints(videoPreferred=true){
  const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
  const video = videoPreferred ? { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 24 } } : false;
  return { audio, video };
}

async function getMediaWithFallback() {
  try { return await navigator.mediaDevices.getUserMedia(mediaConstraints(true)); }
  catch (err) {
    console.warn('Falling back to audio-only', err);
    try { return await navigator.mediaDevices.getUserMedia(mediaConstraints(false)); }
    catch (audioErr) { console.error('Media denied by system', audioErr); showAlert('Microphone (and/or camera) access is blocked. Please allow access for this site, then try again.'); throw audioErr; }
  }
}

async function ensureMedia() {
  if (state.localStream) return state.localStream;
  state.localStream = await getMediaWithFallback();
  addPeerTile('local', state.name || 'Me', state.localStream, true);
  setupLocalVAD(state.localStream);
  setupLocalPitch(state.localStream);
  send({ type: 'media-state', hasAudio: hasAudioTrack(state.localStream), hasVideo: hasVideoTrack(state.localStream) });
  return state.localStream;
}

function hasAudioTrack(stream){ return !!(stream && stream.getAudioTracks().find(t=>t.enabled !== false)); }
function hasVideoTrack(stream){ return !!(stream && stream.getVideoTracks().length); }

function createPeerConnection(targetId) {
  const pc = new RTCPeerConnection({ iceServers: [ { urls: 'stun:stun.l.google.com:19302' } ] });
  pc.onicecandidate = (ev) => { if (ev.candidate) send({ type: 'ice', to: targetId, candidate: ev.candidate }); };
  pc.ontrack = (ev) => {
    const [stream] = ev.streams;
    const peer = state.peers.get(targetId) || { name: 'Peer' };
    peer.stream = stream;
    state.peers.set(targetId, peer);
    addPeerTile(targetId, peer.name || 'Peer', stream, false);
    setupRemotePitch(targetId, stream);
  };
  return pc;
}

function addLocalTracksTo(pc){ if (!state.localStream) return; state.localStream.getTracks().forEach((t) => pc.addTrack(t, state.localStream)); }
function replaceOrAddTrackOnPeers(){ if (!state.localStream) return; for (const [id, peer] of state.peers.entries()){ if (!peer.pc) continue; const senders = peer.pc.getSenders(); for (const track of state.localStream.getTracks()){ const sender = senders.find(s => s.track && s.track.kind === track.kind); if (sender) sender.replaceTrack(track); else peer.pc.addTrack(track, state.localStream); } } }

function send(obj) { if (state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(obj)); }

function setMutedUI(clientId, muted) { const badge = document.getElementById(`badge-${clientId}`); if (!badge) return; if (muted) { badge.textContent = 'Muted'; badge.classList.add('muted'); badge.classList.remove('speaking'); } else { badge.textContent = ''; badge.classList.remove('muted'); } }
function setSpeakingUI(clientId, speaking) { const ring = document.getElementById(`ring-${clientId}`); const badge = document.getElementById(`badge-${clientId}`); if (ring) ring.classList.toggle('active', speaking); if (badge && !badge.classList.contains('muted')) badge.classList.toggle('speaking', speaking); }

function setupLocalVAD(stream){ 
  try{ 
    const ctx = new (window.AudioContext || window.webkitAudioContext)(); 
    const src = ctx.createMediaStreamSource(stream); 
    const analyser = ctx.createAnalyser(); 
    analyser.fftSize = 512; 
    src.connect(analyser); 
    const data = new Uint8Array(analyser.frequencyBinCount); 
    state.analyser = analyser; 
    if (state.vadInterval) clearInterval(state.vadInterval); 
    state.vadInterval = setInterval(()=>{ 
      analyser.getByteFrequencyData(data); 
      let sum = 0; for (let i=0;i<data.length;i++) sum += data[i]; 
      const avg = sum / data.length; 
      setSpeakingUI('local', avg > 25 && !state.muted); 
    }, 120); 
    // Ensure audio context is running
    if (ctx.state === 'suspended') {
      ctx.resume().catch(e => console.warn('Failed to resume audio context:', e));
    }
  }catch(e){ console.warn('VAD unavailable', e); } 
}

function estimatePitchFromStream(stream, callback){
  try{
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);
    const buffer = new Float32Array(analyser.fftSize);
    const sampleRate = audioCtx.sampleRate;
    function autoCorrelate(buf, sr){
      let SIZE = buf.length;
      let rms = 0; for (let i=0;i<SIZE;i++){ let v = buf[i]; rms += v*v; }
      rms = Math.sqrt(rms / SIZE);
      if (rms < 0.01) return -1;
      let r1=0, r2=SIZE-1, thres=0.2;
      for (let i=0;i<SIZE/2;i++){ if (Math.abs(buf[i])<thres){ r1=i; break; } }
      for (let i=1;i<SIZE/2;i++){ if (Math.abs(buf[SIZE-i])<thres){ r2=SIZE-i; break; } }
      buf = buf.slice(r1, r2); SIZE = buf.length;
      const c = new Array(SIZE).fill(0);
      for (let tau=0; tau<SIZE; tau++){
        for (let i=0;i<SIZE-tau;i++) c[tau] += buf[i]*buf[i+tau];
      }
      let d=0; while (c[d]>c[d+1]) d++;
      let maxval=-1, maxpos=-1; for (let i=d; i<SIZE; i++){ if (c[i] > maxval){ maxval=c[i]; maxpos=i; } }
      let T = maxpos; if (T===0) return -1; return sr/T;
    }
    function tick(){ analyser.getFloatTimeDomainData(buffer); const hz = autoCorrelate(buffer, sampleRate); callback(hz>80 && hz<500 ? hz : -1); }
    // Ensure audio context is running
    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(e => console.warn('Failed to resume pitch audio context:', e));
    }
    return setInterval(tick, 300);
  }catch(e){ console.warn('Pitch detection unavailable', e); return null; }
}

function setupLocalPitch(stream){ if (state.pitchInterval) clearInterval(state.pitchInterval); state.pitchInterval = estimatePitchFromStream(stream, (hz)=>{ setPitchUI('local', hz); if (hz && hz>0) send({ type: 'pitch', hz }); }); }
function setupRemotePitch(clientId, stream){ estimatePitchFromStream(stream, (hz)=> setPitchUI(clientId, hz)); }

async function handleJoined(payload) {
  state.clientId = payload.clientId;
  try {
    if (state.localStream) {
      const stream = state.localStream; renderPeersList(payload.peers);
      for (const p of payload.peers) { const pc = createPeerConnection(p.clientId); addLocalTracksTo(pc); state.peers.set(p.clientId, { pc, name: p.name }); const offer = await pc.createOffer(); await pc.setLocalDescription(offer); send({ type: 'offer', to: p.clientId, sdp: offer.sdp }); }
    } else {
      renderPeersList(payload.peers);
      for (const p of payload.peers) { const pc = createPeerConnection(p.clientId); state.peers.set(p.clientId, { pc, name: p.name }); const offer = await pc.createOffer(); await pc.setLocalDescription(offer); send({ type: 'offer', to: p.clientId, sdp: offer.sdp }); }
      el('enableMicBtn').disabled = false; showAlert('You joined without microphone/camera. Click <b>Enable Mic</b> to grant access when ready.');
    }
  } catch (e) { appendMessage('Permission denied. You joined without mic. Click Enable Mic to retry.'); el('enableMicBtn').disabled = false; showAlert('Microphone/camera access failed. Please allow access for this site in the browser and Windows settings.'); }
}

async function handleOffer(payload) { const from = payload.from; const pc = createPeerConnection(from); if (state.localStream) addLocalTracksTo(pc); state.peers.set(from, { pc, name: (state.peers.get(from)?.name) || 'Peer' }); await pc.setRemoteDescription({ type: 'offer', sdp: payload.sdp }); const answer = await pc.createAnswer(); await pc.setLocalDescription(answer); send({ type: 'answer', to: from, sdp: answer.sdp }); }
async function handleAnswer(payload) { const from = payload.from; const peer = state.peers.get(from); if (!peer?.pc) return; await peer.pc.setRemoteDescription({ type: 'answer', sdp: payload.sdp }); }
async function handleIce(payload) { const from = payload.from; const peer = state.peers.get(from); if (!peer?.pc) return; try { await peer.pc.addIceCandidate(payload.candidate); } catch (e) { console.error('Failed to add ICE', e); } }

function connect(roomId, name) { state.ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`); state.ws.onopen = () => { send({ type: 'join', roomId, name, token: localStorage.getItem('whop_token') || '' }); }; state.ws.onmessage = (ev) => { const msg = JSON.parse(ev.data); switch (msg.type) { case 'joined': handleJoined(msg); el('muteBtn').disabled = false; el('leaveBtn').disabled = false; break; case 'peer-joined': toast(`${msg.name} joined the room`); break; case 'peer-left': toast(`${msg.name || msg.clientId} left the room`); removePeerTile(msg.clientId); state.peers.delete(msg.clientId); break; case 'chat': { const isMe = msg.fromClientId && msg.fromClientId === state.clientId; appendMessage(`${isMe ? 'You' : msg.fromName}: ${msg.message}`, !!isMe); break; } case 'offer': handleOffer(msg); break; case 'answer': handleAnswer(msg); break; case 'ice': handleIce(msg); break; case 'mute': setMutedUI(msg.clientId, !!msg.muted); break; case 'media-state': { const target = state.peers.get(msg.clientId); if (target && target.stream) addPeerTile(msg.clientId, target.name || 'Peer', target.stream, false); break; } case 'pitch': setPitchUI(msg.clientId, msg.hz); break; case 'error': appendMessage(`Error: ${msg.error}`); break; } }; state.ws.onclose = () => { el('muteBtn').disabled = true; el('leaveBtn').disabled = true; el('enableMicBtn').disabled = true; if (state.pitchInterval) clearInterval(state.pitchInterval); if (state.vadInterval) clearInterval(state.vadInterval); }; }

function setupUI() {
  const modal = alertModal(); if (modal) document.getElementById('alertClose').onclick = hideAlert;
  const loginBtn = document.getElementById('loginBtn');
  if (loginBtn) loginBtn.onclick = () => { window.location.href = '/auth/login'; };
  updateAuthState();

  el('joinBtn').onclick = async () => { const room = el('room').value.trim(); const name = el('name').value.trim() || 'Guest'; if (!room) return; state.roomId = room; state.name = name; try { if (!state.localStream) { state.localStream = await getMediaWithFallback(); addPeerTile('local', name || 'Me', state.localStream, true); setupLocalVAD(state.localStream); setupLocalPitch(state.localStream); } } catch (e) { showAlert('Microphone/camera access is blocked. You can still join to listen. Click <b>Enable Mic</b> later to grant access.'); } connect(room, name); };
  el('enableMicBtn').onclick = async () => { try { state.localStream = await getMediaWithFallback(); addPeerTile('local', state.name || 'Me', state.localStream, true); setupLocalVAD(state.localStream); setupLocalPitch(state.localStream); replaceOrAddTrackOnPeers(); send({ type: 'media-state', hasAudio: hasAudioTrack(state.localStream), hasVideo: hasVideoTrack(state.localStream) }); el('enableMicBtn').disabled = true; hideAlert(); } catch (e) { showAlert('Still no access to mic/camera. Check Windows privacy settings and browser site permissions.'); } };
  const sendCurrentMessage = () => { const val = el('msgInput').value.trim(); if (!val) return; send({ type: 'chat', message: val }); el('msgInput').value = ''; };
  el('sendBtn').onclick = () => { sendCurrentMessage(); };
  el('msgInput').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendCurrentMessage(); } });
  el('muteBtn').onclick = () => { state.muted = !state.muted; if (state.localStream) state.localStream.getAudioTracks().forEach(t => t.enabled = !state.muted); el('muteBtn').textContent = state.muted ? 'Unmute' : 'Mute'; send({ type: 'mute', muted: state.muted }); };
  el('leaveBtn').onclick = () => { send({ type: 'leave' }); try { state.ws && state.ws.close(); } catch {} state.peers.forEach((p, id) => { try { p.pc && p.pc.close(); } catch {} removePeerTile(id); }); state.peers.clear(); hideAlert(); if (state.pitchInterval) clearInterval(state.pitchInterval); if (state.vadInterval) clearInterval(state.vadInterval); };
}

window.addEventListener('load', setupUI);
