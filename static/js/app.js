// Configuration
const API_KEY = 'secret-api-key';
const API_BASE = window.location.origin;

// DOM Elements
const micButton = document.getElementById('micButton');
const status = document.getElementById('status');
const textInput = document.getElementById('textInput');
const submitButton = document.getElementById('submitButton');
const stopButton = document.getElementById('stopButton');
const chatHistory = document.getElementById('chatHistory');
const debugConsole = document.getElementById('debugConsole');
const debugLogs = document.getElementById('debugLogs');

function logDebug(msg, type = 'info') {
    if (!debugLogs) return;
    const entry = document.createElement('div');
    entry.className = `debug-entry ${type}`;
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    debugLogs.appendChild(entry);
    debugLogs.scrollTop = debugLogs.scrollHeight;
    console.log(`[DEBUG] ${msg}`);
}

window.clearDebug = () => { if (debugLogs) debugLogs.innerHTML = ''; };

let currentChatController = null;

// Session Management
// Session Management - Always generate a new session ID for a fresh start on every refresh
let sessionId = crypto.randomUUID();
logDebug(`New Session Initialized: ${sessionId}`, "success");

// Speech Recognition Setup
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let isListening = false;
let isCallActive = false;
let isAISpeaking = false;
let silenceTimer = null;
const SILENCE_TIMEOUT = 1500; // 1.5 seconds of silence before auto-submitting
if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onstart = () => {
        isListening = true;
        logDebug("Recognition Started", "success");
        if (!isCallActive) {
            micButton.classList.add('listening');
        }
        if (isCallActive) {
            if (isAISpeaking) {
                status.textContent = 'Call Active: AI Responding... (speak to interrupt)';
            } else {
                status.textContent = 'Call Active: Listening... Speak now!';
            }
        } else if (!isCallActive) {
            status.textContent = 'Listening... Speak now!';
        }
    };


    recognition.onspeechstart = () => {
        logDebug("Speech Start Detected");
        // Fires when speech specifically is detected.
        if (isCallActive && isAISpeaking) {
            logDebug("Barge-in: Interruption triggered (Speech Start)", "success");
            interruptAI();
        }
    };

    function interruptAI() {
        if (!isAISpeaking) return;

        console.log("Interrupting AI synthesis...");
        // Stop backend audio
        if (currentAudio) {
            currentAudio.pause();
            currentAudio = null;
        }
        window.speechSynthesis.cancel();
        isAISpeaking = false;
        micButton.classList.remove('speaking');
        micButton.classList.add('call-active');
        status.textContent = 'Call Active: Interrupted. Listening...';

        if (currentChatController) {
            currentChatController.abort();
            currentChatController = null;
            const thinkingBubble = chatHistory.querySelector('.chat-bubble.thinking');
            if (thinkingBubble) thinkingBubble.remove();
        }
    }

    recognition.onresult = (event) => {
        // Fallback Barge-in: If onsoundstart didn't catch it, the interim result certainly will.
        if (isAISpeaking) {
            console.log("Barge-in detected via onresult");
            interruptAI();
        }

        let interimTranscript = '';
        let finalTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; ++i) {
            if (event.results[i].isFinal) {
                finalTranscript += event.results[i][0].transcript;
            } else {
                interimTranscript += event.results[i][0].transcript;
            }
        }

        // Show interim status while user is speaking
        if (interimTranscript.trim() !== '') {
            status.textContent = 'Call Active: Hearing you...';
        }

        if (finalTranscript.trim() !== '') {
            status.textContent = 'Call Active: Processing...';
            // If we get a final transcript, reset the silence timer to auto-submit
            clearTimeout(silenceTimer);
            textInput.value = (textInput.value + ' ' + finalTranscript).trim();

            silenceTimer = setTimeout(() => {
                if (textInput.value.trim() !== '') {
                    const query = textInput.value;
                    textInput.value = ''; // clear immediately
                    handleQuery(query, true); // explicitly mark as voice
                }
            }, SILENCE_TIMEOUT);
        }
    };

    recognition.onerror = (event) => {
        logDebug(`Recognition Error: ${event.error}`, "error");

        if (isCallActive) {
            // In Call Mode, most errors (no-speech, network, etc.) should NOT kill the call.
            // We just let onend restart it.
            if (event.error === 'no-speech') {
                status.textContent = 'Call Active: Listening...';
            } else {
                status.textContent = `Call Active: Note - ${event.error}`;
            }
            return;
        }

        if (event.error !== 'aborted') {
            status.textContent = `Error: ${event.error}. Try again.`;
            micButton.classList.remove('listening');
            micButton.classList.remove('call-active');
            micButton.classList.remove('speaking');
            isListening = false;
            isCallActive = false;
        }
    };

    recognition.onend = () => {
        isListening = false;
        logDebug(`Recognition Ended (isCallActive: ${isCallActive})`, isCallActive ? 'info' : 'success');

        // In call mode, we ALWAYS want the mic listening, even if the AI is speaking.
        // If it stops for any reason (noise, timeout, etc.), we restart it with a small delay.
        if (isCallActive) {
            setTimeout(() => {
                if (isCallActive && !isListening) {
                    try {
                        recognition.start();
                        logDebug("Recognition Restarted", "info");
                    } catch (e) {
                        // Already started
                    }
                }
            }, 100); // 100ms delay to prevent browser throttling
        } else {
            micButton.classList.remove('listening');
            micButton.classList.remove('call-active');
            micButton.classList.remove('speaking');
            if (status.textContent.includes('Listening')) {
                status.textContent = 'Ready to listen...';
            }
        }
    };

    // Watchdog: Every 5 seconds, ensure mic is actually on if Call Active
    setInterval(() => {
        if (isCallActive && !isListening) {
            logDebug("Watchdog: Restarting mic...", "info");
            try { recognition.start(); } catch (e) { }
        }
    }, 5000);
} else {
    status.textContent = 'Speech recognition not supported. Use Chrome or Edge.';
    micButton.disabled = true;
}

// Event Listeners
micButton.addEventListener('click', () => {
    if (!recognition) return;

    // Toggle Call Mode
    isCallActive = !isCallActive;

    if (isCallActive) {
        micButton.classList.add('call-active');
        micButton.classList.remove('listening');
        debugConsole.classList.remove('hidden'); // Show logs when call active
        logDebug("Call Mode Started", "success");
        status.textContent = 'Call Mode Started. Listening...';
        try {
            recognition.start();
        } catch (e) { }
    } else {
        micButton.classList.remove('call-active');
        micButton.classList.remove('listening');
        status.textContent = 'Call Mode Ended.';
        isAISpeaking = false;
        window.speechSynthesis.cancel();
        recognition.stop();
        clearTimeout(silenceTimer);
    }
});

submitButton.addEventListener('click', () => {
    const query = textInput.value.trim();
    if (query) {
        handleQuery(query);
    }
});

textInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        submitButton.click();
    }
});

stopButton.addEventListener('click', () => {
    if (currentChatController) {
        currentChatController.abort();
        currentChatController = null;
        stopButton.classList.add('hidden');
        submitButton.classList.remove('hidden');
        status.textContent = 'Request stopped.';
    }
});

// ── Handle Query ──
async function handleQuery(query, isVoice = false) {
    // Clear placeholder if first message
    const placeholder = chatHistory.querySelector('.chat-placeholder');
    if (placeholder) placeholder.remove();

    // Add user bubble
    addChatBubble(query, 'user');
    textInput.value = '';

    // Smooth conversational status
    if (isCallActive || isVoice) {
        status.textContent = 'Checking on that for you...';
    } else {
        status.textContent = 'Asking the AI...';
    }

    // Add thinking indicator
    const thinkingBubble = addThinkingBubble();

    // Setup AbortController
    if (currentChatController) {
        currentChatController.abort(); // Cancel previous if any
    }
    currentChatController = new AbortController();

    // Toggle buttons
    submitButton.classList.add('hidden');
    stopButton.classList.remove('hidden');

    try {
        const result = await chatWithAI(query, currentChatController.signal, isVoice || isCallActive);

        // Remove thinking indicator
        thinkingBubble.remove();

        // Add AI response bubble (with retry if offline)
        // Add AI response bubble
        const isOffline = result.response && result.response.includes('offline mode');
        addAIBubble(result);

        // Speak the AI's natural language response
        if (result.response) {
            speak(result.response);
        } else {
            // If no response text, ensure recognition restarts if call active
            if (isCallActive && !isListening) {
                try { recognition.start(); } catch (e) { }
            }
            if (isCallActive) {
                status.textContent = 'Call Active: Listening...';
            } else {
                status.textContent = 'Ready to listen...';
            }
        }
    } catch (error) {
        if (error.name === 'AbortError') {
            thinkingBubble.remove();
            addChatBubble('⚠️ Request stopped by user.', 'ai'); // Or specific style for stopped
            status.textContent = 'Stopped.';
        } else {
            console.error('Error fetching data:', error);
            thinkingBubble.remove();
            addErrorBubble(error.message || 'Something went wrong.', query);
            status.textContent = 'Error. Please try again.';
        }
    } finally {
        currentChatController = null;
        if (!isCallActive) {
            stopButton.classList.add('hidden');
            submitButton.classList.remove('hidden');
        }
    }
}

// ── Chat with AI Backend ──
async function chatWithAI(message, signal, isVoice = false) {
    const url = `${API_BASE}/chat/`;

    let internalController = null;
    let fetchSignal = signal;
    if (!fetchSignal) {
        internalController = new AbortController();
        fetchSignal = internalController.signal;
    }

    const timeoutId = setTimeout(() => {
        if (internalController) internalController.abort();
    }, 25000);

    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': API_KEY
            },
            body: JSON.stringify({
                message: message,
                session_id: sessionId,
                voice_mode: isVoice
            }),
            signal: fetchSignal
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        // ── Read SSE stream line-by-line ──────────────────────────────────────
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullText = '';
        let finalData = [];

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // keep incomplete last line

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const jsonStr = line.substring(6).trim();
                if (!jsonStr) continue;

                let parsed;
                try { parsed = JSON.parse(jsonStr); } catch { continue; }

                if (parsed.text) {
                    fullText += parsed.text;
                }
                if (parsed.done) {
                    finalData = parsed.data || [];
                }
            }
        }

        return { response: fullText.trim() || null, data: finalData };

    } catch (err) {
        clearTimeout(timeoutId);
        if (err.name === 'AbortError') {
            throw new Error('Request timed out. Please try again.');
        }
        throw err;
    }
}


// ── Add a simple chat bubble ──
function addChatBubble(text, role) {
    const bubble = document.createElement('div');
    bubble.className = `chat-bubble ${role}`;

    // Text content
    const textSpan = document.createElement('span');
    textSpan.textContent = text;
    bubble.appendChild(textSpan);

    // If user, add retry button
    if (role === 'user') {
        const retryBtn = document.createElement('button');
        retryBtn.className = 'user-retry-button';
        retryBtn.innerHTML = '↻';
        retryBtn.title = 'Retry this query';
        retryBtn.onclick = () => retryMessage(text);
        bubble.appendChild(retryBtn);
    }

    chatHistory.appendChild(bubble);
    scrollToBottom();
    return bubble;
}

// ── Add an AI response bubble (with optional data cards + retry) ──
function addAIBubble(result, retryQuery) {
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble ai';

    // Label + speak button + copy
    let html = `<div class="ai-label">Universal Data Connector <button class="speak-inline" onclick="speak(this.closest('.chat-bubble').querySelector('.ai-text').textContent)">🔊</button><button class="copy-inline" title="Copy response">📋</button></div>`;

    // AI text
    const responseText = result.response || 'Here are the results.';
    html += `<div class="ai-text">${responseText}</div>`;

    // Data cards (generic - works for any data source)
    const records = result.data || [];
    if (records.length > 0) {
        html += '<div class="data-cards">';
        records.forEach(record => {
            // Pick a display title: use the first string-valued field as the card title
            const titleKey = Object.keys(record).find(k =>
                typeof record[k] === 'string' && record[k].length > 0
            );
            const title = titleKey ? record[titleKey] : 'Record';

            html += `<div class="student-card">
                <div class="student-name">${title}</div>
                <div class="student-details">`;

            Object.entries(record).forEach(([key, value]) => {
                if (key === titleKey) return; // skip title field (already shown above)
                const label = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                const displayValue = (value !== null && value !== undefined && value !== '')
                    ? (typeof value === 'object' ? JSON.stringify(value) : value)
                    : 'N/A';
                html += `<div class="detail-item"><strong>${label}:</strong> ${displayValue}</div>`;
            });

            html += `</div></div>`;
        });
        html += '</div>';
    }

    bubble.innerHTML = html;
    chatHistory.appendChild(bubble);
    scrollToBottom();

    // Attach copy handler
    const copyEl = bubble.querySelector('.copy-inline');
    if (copyEl) {
        copyEl.addEventListener('click', () => copyResponse(bubble));
    }



    return bubble;
}

// ── Add an error bubble with retry ──
function addErrorBubble(errorMsg, retryQuery) {
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble ai';
    bubble.innerHTML = `
        <div class="ai-label">Universal Data Connector <button class="copy-inline" title="Copy response">📋</button><button class="retry-inline" title="Retry this question">🔄</button></div>
        <div class="ai-text error-text">${errorMsg}</div>`;
    chatHistory.appendChild(bubble);
    scrollToBottom();

    bubble.querySelector('.copy-inline')?.addEventListener('click', () => copyResponse(bubble));
    const retryEl = bubble.querySelector('.retry-inline');
    if (retryEl) {
        retryEl.addEventListener('click', () => retryMessage(retryQuery, bubble));
    }
    return bubble;
}

// ── Retry a message ──
async function retryMessage(query) {
    // Add thinking bubble at the bottom (new response)
    const thinkingBubble = addThinkingBubble();
    status.textContent = 'Retrying...';

    try {
        const result = await chatWithAI(query, null, isCallActive);
        thinkingBubble.remove();
        const isOffline = result.response && result.response.includes('offline mode');
        addAIBubble(result, isOffline ? query : null);
        if (result.response) speak(result.response);
        if (isCallActive) {
            status.textContent = 'Call Active: Listening...';
        } else {
            status.textContent = 'Ready to listen...';
        }
    } catch (error) {
        console.error('Retry error:', error);
        thinkingBubble.remove();
        addErrorBubble(error.message || 'Retry failed.', query);
        status.textContent = 'Error. Please try again.';
    }
}

// ── Thinking bubble ──
function addThinkingBubble() {
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble thinking';
    bubble.innerHTML = 'Thinking<span class="dot-pulse"></span>';
    chatHistory.appendChild(bubble);
    scrollToBottom();
    return bubble;
}

// ── Scroll chat to bottom ──
function scrollToBottom() {
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

// ── Text-to-Speech (via backend edge_tts) ──
let currentAudio = null;

function speak(text) {
    // Stop any currently playing audio
    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
    }
    window.speechSynthesis.cancel(); // stop browser TTS if any lingered

    isAISpeaking = true;
    logDebug("AI Started Speaking");

    if (isCallActive) {
        status.textContent = 'Call Active: AI Responding... (speak to interrupt)';
        micButton.classList.add('speaking');
    }

    // Call backend TTS (edge_tts — SaraNeural soft voice)
    fetch(`${API_BASE}/chat/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
        body: JSON.stringify({ text })
    })
    .then(res => {
        if (!res.ok) throw new Error(`TTS HTTP ${res.status}`);
        return res.blob();
    })
    .then(blob => {
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        currentAudio = audio;

        audio.onended = () => {
            isAISpeaking = false;
            currentAudio = null;
            URL.revokeObjectURL(url);
            if (isCallActive) {
                micButton.classList.remove('speaking');
                status.textContent = 'Call Active: Listening...';
            }
            logDebug("AI Finished Speaking");
        };

        audio.onerror = () => {
            isAISpeaking = false;
            currentAudio = null;
            if (isCallActive) {
                micButton.classList.remove('speaking');
                status.textContent = 'Call Active: Listening...';
            }
        };

        audio.play().catch(err => {
            logDebug(`Audio play error: ${err}`, 'error');
            isAISpeaking = false;
        });
    })
    .catch(err => {
        logDebug(`TTS backend error: ${err.message} — falling back to browser TTS`, 'error');
        // Fallback to browser speech synthesis
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 0.85;
        utterance.pitch = 0.9;
        utterance.volume = 1;
        utterance.onend = () => {
            isAISpeaking = false;
            if (isCallActive) {
                micButton.classList.remove('speaking');
                status.textContent = 'Call Active: Listening...';
            }
        };
        window.speechSynthesis.speak(utterance);
    });
}

// Expose interruptAI to stop backend audio too
function stopAudio() {
    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
    }
    window.speechSynthesis.cancel();
    isAISpeaking = false;
}


// ── Copy AI response to clipboard ──
function copyResponse(bubble) {
    const aiText = bubble.querySelector('.ai-text')?.textContent || '';
    const cards = bubble.querySelectorAll('.student-card');
    let copyText = aiText;

    if (cards.length > 0) {
        copyText += '\n\n';
        cards.forEach(card => {
            const details = card.querySelectorAll('.detail-item');
            const line = Array.from(details).map(d => d.textContent.trim()).join(' | ');
            copyText += line + '\n';
        });
    }

    navigator.clipboard.writeText(copyText.trim()).then(() => {
        const btn = bubble.querySelector('.copy-inline');
        if (btn) {
            const original = btn.textContent;
            btn.textContent = '✓';
            setTimeout(() => btn.textContent = original, 1500);
        }
    });
}

// ══════════════════════════════════════════════
// ── Streaming (SSE) Section ──
// ══════════════════════════════════════════════
let activeEventSource = null;

function toggleStreamPanel() {
    const panel = document.getElementById('streamPanel');
    const arrow = document.getElementById('streamArrow');
    panel.classList.toggle('hidden');
    arrow.classList.toggle('open');
}

function clearStreamOutput() {
    document.getElementById('streamOutput').innerHTML = '';
    document.getElementById('streamStatus').textContent = '';
}

function startStream() {
    const btn = document.getElementById('streamButton');

    // If already streaming, stop
    if (activeEventSource) {
        activeEventSource.close();
        activeEventSource = null;
        btn.textContent = '▶ Start';
        btn.classList.remove('streaming');
        document.getElementById('streamStatus').textContent = 'Stream stopped.';
        return;
    }

    const source = document.getElementById('streamSource').value;
    const limit = document.getElementById('streamLimit').value;
    const delay = document.getElementById('streamDelay').value;
    const output = document.getElementById('streamOutput');
    const statusEl = document.getElementById('streamStatus');

    output.innerHTML = '';
    statusEl.textContent = 'Connecting...';
    btn.textContent = '⏹ Stop';
    btn.classList.add('streaming');

    const url = `${API_BASE}/stream/${source}?limit=${limit}&delay=${delay}`;

    // Use fetch with ReadableStream for SSE (EventSource doesn't support custom headers)
    fetch(url, {
        headers: { 'X-API-Key': API_KEY }
    }).then(response => {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let recordCount = 0;

        function processChunk({ done, value }) {
            if (done) {
                btn.textContent = '▶ Start';
                btn.classList.remove('streaming');
                activeEventSource = null;
                return;
            }

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Keep incomplete line in buffer

            let currentEvent = '';
            for (const line of lines) {
                if (line.startsWith('event: ')) {
                    currentEvent = line.substring(7).trim();
                } else if (line.startsWith('data: ')) {
                    const data = line.substring(6);
                    try {
                        const parsed = JSON.parse(data);
                        const div = document.createElement('div');
                        div.className = `stream-event ${currentEvent}`;

                        if (currentEvent === 'start') {
                            div.textContent = `⚡ Stream started: ${parsed.source} (${parsed.total_records} records)`;
                        } else if (currentEvent === 'record') {
                            recordCount++;
                            div.textContent = `[${parsed._index}/${parsed._of}] ${JSON.stringify(parsed).substring(0, 120)}...`;
                        } else if (currentEvent === 'done') {
                            div.textContent = `✓ Done: ${parsed.records_sent} records streamed`;
                        } else if (currentEvent === 'error') {
                            div.textContent = `✕ Error: ${parsed.error}`;
                        }

                        output.appendChild(div);
                        output.scrollTop = output.scrollHeight;
                        statusEl.textContent = `Records received: ${recordCount}`;
                    } catch (e) {
                        // Skip non-JSON lines
                    }
                }
            }

            return reader.read().then(processChunk);
        }

        // Store a fake "close" handle
        activeEventSource = { close: () => reader.cancel() };
        return reader.read().then(processChunk);
    }).catch(err => {
        output.innerHTML += `<div class="stream-event error">Connection error: ${err.message}</div>`;
        btn.textContent = '▶ Start';
        btn.classList.remove('streaming');
        activeEventSource = null;
        statusEl.textContent = 'Disconnected.';
    });
}
