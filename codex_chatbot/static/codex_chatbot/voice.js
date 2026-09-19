(() => {
  const form = document.querySelector('#codex-composer');
  if (!form) return;
  const root = document.querySelector('.codex-chat');
  const input = document.querySelector('#codex-question');
  const button = document.querySelector('#codex-microphone');
  const cancel = document.querySelector('#codex-voice-cancel');
  const language = document.querySelector('#codex-voice-language');
  const status = document.querySelector('#codex-voice-status');
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let pendingSend = false;
  let timer = null;
  let aborted = false;
  let hadError = false;
  let stopping = false;
  let received = new Set();
  if (!Recognition || !window.isSecureContext) {
    button.disabled = true;
    status.textContent = !window.isSecureContext ? 'Microphone access requires HTTPS or localhost.' : 'Dictation is unavailable in this browser. You can use Windows voice typing (Win+H) in this field.';
    return;
  }
  function reset() {
    clearTimeout(timer);
    root.dataset.voiceActive = '';
    button.setAttribute('aria-pressed', 'false');
    button.querySelector('span').textContent = 'Dictate';
    language.disabled = false;
    cancel.hidden = true;
    recognition = null;
    stopping = false;
    button.disabled = input.disabled;
  }
  function stop(send = false) {
    if (!recognition) return;
    pendingSend = pendingSend || send;
    if (stopping) return;
    stopping = true;
    button.disabled = true;
    status.textContent = 'Finishing dictation…';
    try { recognition.stop(); }
    catch (_) { pendingSend = false; recognition.abort(); }
  }
  button.addEventListener('click', () => {
    if (recognition) { stop(); return; }
    if (input.disabled) return;
    recognition = new Recognition();
    recognition.lang = language.value;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    received = new Set(); pendingSend = false; aborted = false; hadError = false;
    root.dataset.voiceActive = '1';
    language.disabled = true; cancel.hidden = false;
    button.setAttribute('aria-pressed', 'true');
    button.querySelector('span').textContent = 'Finish';
    status.textContent = 'Allow microphone access, then speak. You can continue typing.';
    recognition.onstart = () => { status.textContent = 'Listening… you can also type.'; };
    recognition.onresult = (event) => {
      if (aborted) return;
      const interim = [];
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (!result.isFinal) { interim.push(result[0].transcript); continue; }
        if (received.has(i)) continue;
        received.add(i);
        const transcript = result[0].transcript.trim();
        if (!transcript) continue;
        const start = input.selectionStart, end = input.selectionEnd;
        const prefix = start && !/\s/.test(input.value[start - 1]) ? ' ' : '';
        const suffix = end < input.value.length && !/\s/.test(input.value[end]) ? ' ' : '';
        const addition = prefix + transcript + suffix;
        if (input.value.length - (end - start) + addition.length > input.maxLength) {
          hadError = true; pendingSend = false;
          status.textContent = 'Message length limit reached. Shorten the text before resuming dictation.';
          recognition.abort(); return;
        }
        input.setRangeText(addition, start, end, 'end');
        input.dispatchEvent(new Event('input', {bubbles: true}));
      }
      status.textContent = interim.length ? `Dictation: ${interim.join(' ')}` : 'Text added. Continue typing or dictating.';
    };
    recognition.onerror = (event) => {
      hadError = true; pendingSend = false;
      const messages = {
        'not-allowed': 'Microphone access denied. Allow it in your browser or continue typing.',
        'service-not-allowed': 'The speech service is unavailable or disabled by your browser.',
        'audio-capture': 'No microphone available.',
        'network': 'The browser speech service is unavailable. Your text has been preserved.',
        'no-speech': 'No speech detected. Try again or continue typing.',
        'language-not-supported': 'This dictation language is unavailable in your browser.',
      };
      status.textContent = messages[event.error] || 'Dictation interrupted. Your text has been preserved.';
    };
    recognition.onend = () => {
      const send = pendingSend && !hadError && !aborted;
      pendingSend = false; reset();
      if (!hadError) status.textContent = 'You can edit the text, dictate again or press Enter to send.';
      if (send) form.requestSubmit();
    };
    try {
      recognition.start();
      timer = setTimeout(() => stop(), 90000);
      input.focus();
    } catch (_) {
      reset(); status.textContent = 'Unable to start dictation. Continue typing.';
    }
  });
  cancel.addEventListener('click', () => {
    aborted = true; pendingSend = false;
    recognition?.abort();
  });
  form.addEventListener('codex:voice-send', () => stop(true));
  new MutationObserver(() => { button.disabled = input.disabled; }).observe(input, {attributes: true, attributeFilter: ['disabled']});
  window.addEventListener('pagehide', () => { aborted = true; pendingSend = false; recognition?.abort(); clearTimeout(timer); });
})();
