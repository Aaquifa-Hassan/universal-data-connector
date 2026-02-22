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

let currentChatController = null;

// Session Management
let sessionId = localStorage.getItem('chat_session_id');
if (!sessionId) {
    sessionId = crypto.randomUUID();
    localStorage.setItem('chat_session_id', sessionId);
}

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
        micButton.classList.add('listening');
        if (isCallActive && !isAISpeaking) {
            status.textContent = 'Call Active: Listening... Speak now!';
        } else if (!isCallActive) {
            status.textContent = 'Listening... Speak now!';
        }
    };

    recognition.onresult = (event) => {
        // Barge-in: If the AI is speaking and we detect user audio, stop the AI unconditionally.
        if (isAISpeaking) {
            window.speechSynthesis.cancel();
            isAISpeaking = false;
            // Cancel the current fetch request to the AI if it's still thinking
            if (currentChatController) {
                currentChatController.abort();
                currentChatController = null;
                const thinkingBubble = chatHistory.querySelector('.chat-bubble.thinking');
                if (thinkingBubble) thinkingBubble.remove();
            }
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
                    handleQuery(query);
                }
            }, SILENCE_TIMEOUT);
        }
    };

    recognition.onerror = (event) => {
        console.error('Speech recognition error:', event.error);
        if (event.error !== 'aborted') {
            status.textContent = `Error: ${event.error}. Try again.`;
            micButton.classList.remove('listening');
            micButton.classList.remove('call-active');
            isListening = false;
            isCallActive = false;
        }
    };

    recognition.onend = () => {
        isListening = false;
        // In call mode, try to restart recognition immediately if not deliberately stopped
        // and if AI is not currently speaking (we'll start it after AI finishes)
        if (isCallActive && !isAISpeaking) {
            try {
                recognition.start();
            } catch (e) {
                // Ignore error if already started
            }
        } else if (!isCallActive) {
            micButton.classList.remove('listening');
            micButton.classList.remove('call-active');
            if (status.textContent.includes('Listening')) {
                status.textContent = 'Ready to listen...';
            }
        }
    };
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
async function handleQuery(query) {
    // Clear placeholder if first message
    const placeholder = chatHistory.querySelector('.chat-placeholder');
    if (placeholder) placeholder.remove();

    // Add user bubble
    addChatBubble(query, 'user');
    textInput.value = '';
    status.textContent = 'Asking the AI...';

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
        const result = await chatWithAI(query, currentChatController.signal);

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
async function chatWithAI(message, signal) {
    const url = `${API_BASE}/chat/`;
    // If no signal provided, create a default one with timeout
    let internalController = null;
    let fetchSignal = signal;

    if (!fetchSignal) {
        internalController = new AbortController();
        fetchSignal = internalController.signal;
    }

    // We still want a safety timeout of 25s even with manual stop
    const timeoutId = setTimeout(() => {
        if (internalController) internalController.abort();
        // If external signal, we can't abort it directly here easily without wrappers, 
        // but the manual stop is the main goal.
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
                session_id: sessionId
            }),
            signal: fetchSignal
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        return await response.json();
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
    let html = `<div class="ai-label">AI Assistant <button class="speak-inline" onclick="speak(this.closest('.chat-bubble').querySelector('.ai-text').textContent)">🔊</button><button class="copy-inline" title="Copy response">📋</button></div>`;

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
        <div class="ai-label">AI Assistant <button class="copy-inline" title="Copy response">📋</button><button class="retry-inline" title="Retry this question">🔄</button></div>
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
        const result = await chatWithAI(query);
        thinkingBubble.remove();
        const isOffline = result.response && result.response.includes('offline mode');
        addAIBubble(result, isOffline ? query : null);
        if (result.response) speak(result.response);
        status.textContent = 'Ready to listen...';
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

// ── Text-to-Speech ──
function speak(text) {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 0.9;
        utterance.pitch = 1;
        utterance.volume = 1;

        isAISpeaking = true;

        // Pause recognition while speaking to prevent AI hearing itself
        // But only if we are currently listening
        if (isCallActive && isListening) {
            recognition.stop();
        }

        if (isCallActive) {
            status.textContent = 'Call Active: AI Responding... (speak to interrupt)';
            micButton.classList.remove('listening');
            micButton.classList.add('speaking');
        }

        utterance.onend = () => {
            isAISpeaking = false;
            if (isCallActive) {
                micButton.classList.remove('speaking');
                // Restart listening after speech ends
                try {
                    recognition.start();
                } catch (e) { }
            }
        };

        utterance.onerror = (e) => {
            console.error("Speech Synthesis Error", e);
            isAISpeaking = false;
            if (isCallActive) {
                micButton.classList.remove('speaking');
                try {
                    recognition.start();
                } catch (e) { }
            }
        };

        window.speechSynthesis.speak(utterance);
    }
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
