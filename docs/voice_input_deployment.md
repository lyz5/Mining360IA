# Mining 360 Voice Input

## Runtime configuration

Voice input reuses the active OpenAI connection configured in:

`System Config -> Connections -> OpenAI`

The API key remains a backend secret. Configure voice behavior in:

`IA Config -> Voice Input Configuration`

The default transcription model is `gpt-4o-mini-transcribe`.

## Browser requirements

- Production must use HTTPS.
- `localhost` and `127.0.0.1` can use the microphone during development.
- Users must grant microphone permission to the site.
- The browser must support `navigator.mediaDevices.getUserMedia` and `MediaRecorder`.

The frontend selects a supported recording format at runtime. Safari commonly
uses MP4/M4A, while Chromium and Firefox commonly use WebM or Ogg.

## Server-side duration validation

The frontend stops automatically at the configured maximum duration. The
backend always validates the declared duration and file size.

For independent media-duration verification, install `ffprobe` and make it
available on `PATH`. When `ffprobe` is unavailable, the backend uses the
client duration and the strict file-size limit.

## Privacy and storage

Audio is read from Django's temporary upload stream, sent to the configured
transcription provider, and closed in a `finally` block. Mining 360 does not
persist audio or transcription text in `VoiceTranscriptionLog`.

The normal chat history stores the transcription only after the user sends it
as a question.

## Production cache

Configure a shared Django cache such as Redis when running multiple application
workers. The per-user concurrency lock and short idempotent-result cache use
Django's cache API. The default local-memory cache is suitable only for a
single development process.

## Validation

Run:

```powershell
python manage.py check
python manage.py migrate
python manage.py test reports.test_voice_input
```
