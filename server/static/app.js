/**
 * SAHAYAK — Your Voice. Your Freedom.
 * Frontend Accessibility Client
 */

(function () {
  'use strict';

  // State Management
  const state = {
    isListening: false,
    isProcessing: false,
    wsConnected: false,
    contrastMode: localStorage.getItem('sahayak_contrast') || 'dark',
    fontSize: localStorage.getItem('sahayak_font') || 'medium',
    ttsVoice: localStorage.getItem('sahayak_voice') || 'Samantha',
    ttsRate: parseInt(localStorage.getItem('sahayak_rate') || '180', 10),
    lastSpokenText: '',
    pendingConfirmation: null,
    speechRecognitionSupported: ('webkitSpeechRecognition' in window) || ('SpeechRecognition' in window),
  };

  // DOM Elements
  const body = document.getElementById('app-body');
  const btnMic = document.getElementById('btn-mic-toggle');
  const micLabel = document.getElementById('mic-status-label');
  const voiceStatusDesc = document.getElementById('voice-status-desc');
  const audioWave = document.getElementById('audio-wave');
  const statusDot = document.getElementById('status-dot');
  const statusText = document.getElementById('status-text');
  const srPolite = document.getElementById('sr-announcements-polite');
  const srAssertive = document.getElementById('sr-announcements-assertive');
  const transcriptLog = document.getElementById('transcript-log');
  const latestSpokenText = document.getElementById('latest-spoken-text');
  const btnReplayLast = document.getElementById('btn-replay-last');
  const btnThemeToggle = document.getElementById('btn-theme-toggle');
  const btnFontLarger = document.getElementById('btn-font-larger');
  const btnFontSmaller = document.getElementById('btn-font-smaller');
  const btnRefreshScreen = document.getElementById('btn-refresh-screen');
  const screenImg = document.getElementById('screen-preview-img');
  const screenPlaceholder = document.getElementById('screen-placeholder');
  const activeAppName = document.getElementById('active-app-name');
  const actionsHistoryList = document.getElementById('actions-history-list');
  const textCommandForm = document.getElementById('text-command-form');
  const textCommandInput = document.getElementById('text-command-input');
  const selectVoice = document.getElementById('select-tts-voice');
  const rangeRate = document.getElementById('range-tts-rate');
  const rateLabel = document.getElementById('rate-value-label');
  const geminiStatusInd = document.getElementById('gemini-status-indicator');
  const geminiStatusHint = document.getElementById('gemini-status-hint');

  // Confirmation Modal Elements
  const modalBackdrop = document.getElementById('confirmation-dialog');
  const modalActionDetails = document.getElementById('modal-action-details');
  const btnModalConfirm = document.getElementById('btn-modal-confirm');
  const btnModalCancel = document.getElementById('btn-modal-cancel');

  // -------------------------------------------------------------------------
  // Accessible Audio Synthesizer (Web Audio API Cues)
  // -------------------------------------------------------------------------
  const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

  function playTone(freq, duration, type = 'sine') {
    try {
      if (audioCtx.state === 'suspended') {
        audioCtx.resume();
      }
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
      gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + duration);
    } catch (e) {
      // Audio cue fallback
    }
  }

  function chimeStart() {
    playTone(523.25, 0.12, 'sine'); // C5
    setTimeout(() => playTone(659.25, 0.18, 'sine'), 100); // E5
  }

  function chimeSuccess() {
    playTone(587.33, 0.1, 'sine'); // D5
    setTimeout(() => playTone(880, 0.22, 'sine'), 90); // A5
  }

  function chimeAlert() {
    playTone(330, 0.15, 'triangle');
    setTimeout(() => playTone(260, 0.25, 'triangle'), 120);
  }

  // -------------------------------------------------------------------------
  // Screen Reader Announcements
  // -------------------------------------------------------------------------
  function announce(text, assertive = false) {
    const target = assertive ? srAssertive : srPolite;
    target.textContent = '';
    setTimeout(() => {
      target.textContent = text;
    }, 50);
  }

  // -------------------------------------------------------------------------
  // Speech-to-Text (STT) Setup
  // -------------------------------------------------------------------------
  let recognition = null;
  if (state.speechRecognitionSupported) {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRec();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onstart = function () {
      state.isListening = true;
      updateStatus('Listening...', 'listening');
      btnMic.setAttribute('aria-pressed', 'true');
      micLabel.textContent = 'Listening...';
      voiceStatusDesc.textContent = 'I am listening to your voice. Speak your command.';
      audioWave.classList.add('active');
      chimeStart();
      announce('Microphone activated. I am listening.');
    };

    recognition.onresult = function (event) {
      let interim = '';
      let finalTranscript = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript;
        } else {
          interim += event.results[i][0].transcript;
        }
      }

      if (interim) {
        voiceStatusDesc.textContent = `Hearing: "${interim}"`;
      }

      if (finalTranscript) {
        finalTranscript = finalTranscript.trim();
        if (finalTranscript) {
          handleUserCommand(finalTranscript);
        }
      }
    };

    recognition.onerror = function (event) {
      console.warn('Speech recognition error:', event.error);
      stopListening();
      if (event.error === 'not-allowed') {
        const msg = 'Microphone permission denied. Please allow microphone access in your browser or macOS System Settings.';
        speakAndDisplay(msg, 'error');
        announce(msg, true);
      } else if (event.error !== 'no-speech') {
        voiceStatusDesc.textContent = `Recognition error: ${event.error}. Press Space to try again.`;
      }
    };

    recognition.onend = function () {
      stopListening();
    };
  }

  function startListening() {
    if (state.isListening) return;
    if (recognition) {
      try {
        recognition.start();
      } catch (err) {
        console.warn('Recognition start error:', err);
      }
    } else {
      // Fallback: Notify user to use text input or trigger local python wake-word
      const msg = 'In-browser speech recognition is unavailable. Please type your command or run python client/wake_word.py.';
      speakAndDisplay(msg, 'info');
    }
  }

  function stopListening() {
    if (!state.isListening) return;
    state.isListening = false;
    btnMic.setAttribute('aria-pressed', 'false');
    micLabel.textContent = 'Start Listening';
    audioWave.classList.remove('active');
    if (!state.isProcessing) {
      updateStatus('Ready', 'ready');
      voiceStatusDesc.textContent = 'Microphone is ready. Press Space or click the button to speak.';
    }
  }

  function toggleListening() {
    if (state.isListening) {
      if (recognition) recognition.stop();
      stopListening();
    } else {
      startListening();
    }
  }

  // -------------------------------------------------------------------------
  // WebSocket Connection to Backend
  // -------------------------------------------------------------------------
  let ws = null;
  function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/agent`;

    ws = new WebSocket(wsUrl);

    ws.onopen = function () {
      state.wsConnected = true;
      updateStatus('Ready', 'ready');
      console.log('Connected to SAHAYAK Agent WebSocket');
      // Send handshake
      ws.send(JSON.stringify({ event: 'wake_word_detected', timestamp: Date.now() / 1000 }));
    };

    ws.onmessage = function (event) {
      try {
        const data = JSON.parse(event.data);
        handleServerMessage(data);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', event.data);
      }
    };

    ws.onclose = function () {
      state.wsConnected = false;
      updateStatus('Reconnecting...', 'processing');
      setTimeout(initWebSocket, 2000);
    };

    ws.onerror = function (err) {
      console.error('WebSocket error:', err);
    };
  }

  function handleServerMessage(data) {
    console.log('SERVER MESSAGE:', data);

    if (data.status === 'handshake_complete') {
      // Handshake established
    } else if (data.command === 'speak') {
      speakAndDisplay(data.text, 'agent');
    } else if (data.command === 'screen_captured') {
      if (data.image_base64) {
        screenImg.src = `data:image/jpeg;base64,${data.image_base64}`;
        screenImg.classList.remove('hidden');
        screenPlaceholder.classList.add('hidden');
      }
      if (data.app_context && data.app_context.app_name) {
        activeAppName.textContent = data.app_context.app_name + (data.app_context.tab_title ? ` — ${data.app_context.tab_title}` : '');
      }
    } else if (data.command === 'confirm_required') {
      showConfirmationModal(data.action, data.description);
    } else if (data.command === 'action_executed') {
      addActionItem(data.action_type || 'EXEC', data.details || 'Action completed');
      chimeSuccess();
    }
  }

  // -------------------------------------------------------------------------
  // Spoken Feedback & TTS
  // -------------------------------------------------------------------------
  function speakAndDisplay(text, role = 'agent') {
    if (!text) return;
    state.lastSpokenText = text;
    latestSpokenText.textContent = text;
    announce(text);

    // Add to transcript
    addTranscriptEntry(text, role);

    // Call local server TTS or browser TTS
    fetch('/api/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: text,
        voice: state.ttsVoice,
        rate: state.ttsRate,
      }),
    }).catch(() => {
      // Fallback to browser SpeechSynthesis
      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = state.ttsRate / 180;
        window.speechSynthesis.speak(utterance);
      }
    });
  }

  // -------------------------------------------------------------------------
  // User Command Handling
  // -------------------------------------------------------------------------
  async function handleUserCommand(text) {
    addTranscriptEntry(text, 'user');
    updateStatus('Processing...', 'processing');
    state.isProcessing = true;
    voiceStatusDesc.textContent = `Processing: "${text}"`;

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });

      const result = await response.json();
      state.isProcessing = false;
      updateStatus('Ready', 'ready');
      voiceStatusDesc.textContent = 'Ready. Press Space to speak.';

      if (result.requires_confirmation) {
        showConfirmationModal(result.action, result.confirmation_prompt);
        speakAndDisplay(result.confirmation_prompt, 'agent');
      } else {
        if (result.spoken_response) {
          speakAndDisplay(result.spoken_response, 'agent');
        }
        if (result.action) {
          addActionItem(result.action.command || 'ACTION', result.action.explanation || JSON.stringify(result.action));
        }
        if (result.screen_image) {
          screenImg.src = `data:image/jpeg;base64,${result.screen_image}`;
          screenImg.classList.remove('hidden');
          screenPlaceholder.classList.add('hidden');
        }
      }
    } catch (err) {
      state.isProcessing = false;
      updateStatus('Ready', 'ready');
      console.error('Command processing failed:', err);
      speakAndDisplay('I encountered an error processing that instruction. Please try again.', 'error');
    }
  }

  // -------------------------------------------------------------------------
  // Confirmation Modal
  // -------------------------------------------------------------------------
  function showConfirmationModal(action, description) {
    state.pendingConfirmation = action;
    modalActionDetails.textContent = description || JSON.stringify(action);
    modalBackdrop.classList.remove('hidden');
    chimeAlert();
    btnModalConfirm.focus();
    announce(`Attention: Sensitive operation requires confirmation. ${description}. Press Enter to confirm, or Escape to cancel.`, true);
  }

  function hideConfirmationModal() {
    state.pendingConfirmation = null;
    modalBackdrop.classList.add('hidden');
    btnMic.focus();
  }

  async function confirmPendingAction() {
    if (!state.pendingConfirmation) return;
    const action = state.pendingConfirmation;
    hideConfirmationModal();

    updateStatus('Executing...', 'processing');
    try {
      const resp = await fetch('/api/confirm_action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmed: true, action: action }),
      });
      const data = await resp.json();
      updateStatus('Ready', 'ready');
      speakAndDisplay(data.spoken_response || 'Operation completed.', 'agent');
      addActionItem('CONFIRMED', data.details || 'Sensitive operation executed');
      chimeSuccess();
    } catch (e) {
      updateStatus('Ready', 'ready');
      speakAndDisplay('Failed to execute the confirmed operation.', 'error');
    }
  }

  // -------------------------------------------------------------------------
  // UI Helpers
  // -------------------------------------------------------------------------
  function updateStatus(text, type) {
    statusText.textContent = text;
    statusDot.className = `status-dot status-${type}`;
  }

  function addTranscriptEntry(text, role) {
    const entry = document.createElement('div');
    entry.className = `transcript-entry ${role === 'user' ? 'user-entry' : 'agent-entry'}`;

    const meta = document.createElement('span');
    meta.className = 'entry-meta';
    meta.textContent = role === 'user' ? 'You (Voice)' : 'SAHAYAK';

    const bodyP = document.createElement('p');
    bodyP.className = 'entry-body';
    bodyP.textContent = text;

    entry.appendChild(meta);
    entry.appendChild(bodyP);
    transcriptLog.appendChild(entry);
    transcriptLog.scrollTop = transcriptLog.scrollHeight;
  }

  function addActionItem(type, details) {
    const li = document.createElement('li');
    li.className = 'action-item';

    const badge = document.createElement('span');
    badge.className = 'badge badge-info';
    badge.textContent = type;

    const span = document.createElement('span');
    span.textContent = details;

    li.appendChild(badge);
    li.appendChild(span);
    actionsHistoryList.insertBefore(li, actionsHistoryList.firstChild);
  }

  // -------------------------------------------------------------------------
  // Theme & Accessibility Toggles
  // -------------------------------------------------------------------------
  function applyTheme(theme) {
    state.contrastMode = theme;
    localStorage.setItem('sahayak_contrast', theme);
    if (theme === 'high-contrast') {
      body.classList.add('theme-high-contrast');
      announce('High contrast mode enabled.');
    } else {
      body.classList.remove('theme-high-contrast');
      announce('Standard contrast mode enabled.');
    }
  }

  function applyFontSize(size) {
    body.classList.remove('font-small', 'font-medium', 'font-large', 'font-xlarge');
    body.classList.add(`font-${size}`);
    state.fontSize = size;
    localStorage.setItem('sahayak_font', size);
  }

  btnThemeToggle.addEventListener('click', () => {
    applyTheme(state.contrastMode === 'high-contrast' ? 'dark' : 'high-contrast');
  });

  btnFontLarger.addEventListener('click', () => {
    const sizes = ['small', 'medium', 'large', 'xlarge'];
    const idx = sizes.indexOf(state.fontSize);
    if (idx < sizes.length - 1) {
      applyFontSize(sizes[idx + 1]);
      announce(`Text size increased to ${sizes[idx + 1]}`);
    }
  });

  btnFontSmaller.addEventListener('click', () => {
    const sizes = ['small', 'medium', 'large', 'xlarge'];
    const idx = sizes.indexOf(state.fontSize);
    if (idx > 0) {
      applyFontSize(sizes[idx - 1]);
      announce(`Text size decreased to ${sizes[idx - 1]}`);
    }
  });

  // Replay Last Spoken
  btnReplayLast.addEventListener('click', () => {
    if (state.lastSpokenText) {
      speakAndDisplay(state.lastSpokenText, 'agent');
    }
  });

  // Quick Command Chips
  document.querySelectorAll('.btn-chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      const cmd = chip.getAttribute('data-cmd');
      if (cmd) handleUserCommand(cmd);
    });
  });

  // Manual Screen Inspection
  btnRefreshScreen.addEventListener('click', async () => {
    updateStatus('Inspecting...', 'processing');
    speakAndDisplay('Inspecting your screen now...', 'agent');
    try {
      const res = await fetch('/api/capture', { method: 'POST' });
      const data = await res.json();
      updateStatus('Ready', 'ready');
      if (data.image_base64) {
        screenImg.src = `data:image/jpeg;base64,${data.image_base64}`;
        screenImg.classList.remove('hidden');
        screenPlaceholder.classList.add('hidden');
      }
      if (data.app_name) {
        activeAppName.textContent = data.app_name + (data.tab_title ? ` — ${data.tab_title}` : '');
      }
      speakAndDisplay(data.description || 'Screen captured successfully.', 'agent');
    } catch (e) {
      updateStatus('Ready', 'ready');
      speakAndDisplay('Could not capture screen. Check macOS Screen Recording permissions.', 'error');
    }
  });

  // Text Form Submission
  textCommandForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const val = textCommandInput.value.trim();
    if (val) {
      textCommandInput.value = '';
      handleUserCommand(val);
    }
  });

  // Mic Button Click
  btnMic.addEventListener('click', toggleListening);

  // Modal Buttons
  btnModalConfirm.addEventListener('click', confirmPendingAction);
  btnModalCancel.addEventListener('click', () => {
    hideConfirmationModal();
    speakAndDisplay('Operation cancelled.', 'agent');
  });

  // Global Keyboard Navigation
  window.addEventListener('keydown', (e) => {
    // If confirmation modal is open:
    if (!modalBackdrop.classList.contains('hidden')) {
      if (e.key === 'Escape') {
        e.preventDefault();
        btnModalCancel.click();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        btnModalConfirm.click();
      }
      return;
    }

    // Spacebar toggles microphone when NOT focusing text input
    if (e.code === 'Space' && document.activeElement !== textCommandInput) {
      e.preventDefault();
      toggleListening();
    } else if (e.key === 'Escape') {
      if (state.isListening) {
        stopListening();
        announce('Listening cancelled.');
      }
    } else if (e.altKey && e.code === 'KeyT') {
      e.preventDefault();
      btnThemeToggle.click();
    } else if (e.altKey && e.code === 'KeyC') {
      e.preventDefault();
      btnRefreshScreen.click();
    } else if (e.altKey && e.code === 'KeyH') {
      e.preventDefault();
      btnReplayLast.click();
    }
  });

  // Settings updates
  selectVoice.value = state.ttsVoice;
  selectVoice.addEventListener('change', () => {
    state.ttsVoice = selectVoice.value;
    localStorage.setItem('sahayak_voice', state.ttsVoice);
    speakAndDisplay(`Voice set to ${state.ttsVoice}`, 'agent');
  });

  rangeRate.value = state.ttsRate;
  rangeRate.addEventListener('input', () => {
    state.ttsRate = parseInt(rangeRate.value, 10);
    rateLabel.textContent = `${state.ttsRate} wpm`;
    localStorage.setItem('sahayak_rate', state.ttsRate);
  });

  // Check System Status on Load
  async function checkSystemHealth() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      if (data.gemini_configured) {
        geminiStatusInd.className = 'badge badge-success';
        geminiStatusInd.textContent = data.gemini_model || 'gemini-3.8-flash';
        geminiStatusHint.textContent = 'Free Tier Active';
      } else {
        geminiStatusInd.className = 'badge badge-warning';
        geminiStatusInd.textContent = 'API Key Missing';
        geminiStatusHint.textContent = 'Add GEMINI_API_KEY to server/.env';
      }

      if (data.active_app) {
        activeAppName.textContent = data.active_app;
      }
    } catch (e) {
      console.warn('Status check failed:', e);
    }
  }

  // Initial Load
  applyTheme(state.contrastMode);
  applyFontSize(state.fontSize);
  initWebSocket();
  checkSystemHealth();
})();

