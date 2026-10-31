# SAHAYAK

**A voice-first desktop accessibility assistant**

SAHAYAK is a desktop assistant designed to help people interact with their computer through spoken instructions and an accessible web dashboard. It combines speech input, AI-assisted conversation, screen understanding, desktop automation and spoken feedback.

The current implementation targets macOS. Some capabilities depend on macOS permissions and locally available system frameworks; AI-assisted features require a Google Gemini API key.

## Features

- **Voice interaction:** Use the dashboard microphone, supported keyboard controls or the desktop companion to submit spoken requests.
- **Conversational assistance:** Ask questions, request explanations and get help with information shown on screen.
- **Screen understanding:** Capture screen content and use available OCR and AI capabilities to interpret it.
- **Desktop actions:** Open applications and websites, navigate supported interfaces, click, scroll and use keyboard shortcuts.
- **Multi-step tasks:** Process supported workflows as a sequence of actions and provide progress or spoken feedback.
- **Action confirmation:** Sensitive operations are subject to confirmation safeguards before execution.
- **Accessible dashboard:** High-contrast presentation, keyboard controls, live status and transcript feedback.
- **Local session data:** SQLite is used for local application data where enabled.

## Technology

| Area | Technologies |
|---|---|
| Backend | Python, FastAPI, Uvicorn, WebSockets |
| AI | Google Gemini API (`google-genai`) |
| Speech recognition | `faster-whisper`, SpeechRecognition and browser speech input where supported |
| Speech output | macOS native speech synthesis |
| Screen understanding | macOS Vision framework and available AI image understanding |
| Desktop automation | PyAutoGUI, AppleScript and macOS system integration |
| Frontend | HTML, CSS and JavaScript |
| Local persistence | SQLite |

## Requirements

- macOS (the desktop automation and native speech/screen features are macOS-oriented)
- Python 3.10 or newer; Python 3.11 is recommended
- A modern browser
- Microphone and speakers/headphones for voice interaction
- A Google Gemini API key for Gemini-powered features

Some platform-specific Python dependencies are installed only on macOS. The project is not currently documented as a fully supported Windows or Linux desktop application.

## Quick start

1. Clone or download this repository and open a terminal in its root directory.
2. Run the setup script:

   ```bash
   bash setup_mac.sh
   ```

3. Add your Gemini API key to the generated `.env` file:

   ```env
   GEMINI_API_KEY=your_api_key_here
   ```

   Obtain a key through [Google AI Studio](https://aistudio.google.com/). API availability and usage limits are determined by the provider and may change.

4. Start the application:

   ```bash
   ./start.sh
   ```

5. Open the dashboard at [http://127.0.0.1:8080](http://127.0.0.1:8080) if it does not open automatically.

The setup script creates a local virtual environment, installs the Python dependencies and prepares the environment configuration. Review the script before running it if you want to inspect the setup steps.

## Configuration

Copy `.env.example` to `.env` if it was not created by the setup script. Common settings include:

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | API key used for Gemini-powered assistance |
| `SAHAYAK_TTS_VOICE` | Preferred macOS speech voice |
| `SAHAYAK_TTS_RATE` | Speech rate |
| `SAHAYAK_WHISPER_MODEL` | Local Whisper model selection |
| `HOST` | Server bind address |
| `PORT` | Server port |

Keep credentials in your local `.env` file. Do not commit API keys, access tokens or other secrets.

## macOS permissions

Depending on which features you use, grant the terminal or application the following permissions in **System Settings → Privacy & Security**:

- **Microphone:** for voice input.
- **Screen Recording:** for screen capture and screen understanding.
- **Accessibility:** for supported desktop automation and keyboard/mouse control.

Restart the terminal or application after changing permissions. Only grant permissions required for the features you intend to use.

## Usage

You can interact through the dashboard or the desktop companion. Example requests include:

- “Explain this concept in simple terms.”
- “What is visible on my screen?”
- “Read the text in this window.”
- “Open Safari and search for Python tutorials.”
- “Find a document on my computer.”
- “Open Notes and write down these tasks.”

The exact actions available depend on the active application, operating-system permissions and configured services. Review actions before allowing the assistant to perform sensitive operations.

## Run tests

From the repository root, activate the virtual environment and run:

```bash
source venv/bin/activate
pytest -q
```

Individual test modules are located in `tests/`. Some tests exercise macOS-specific functionality or require configured services, so results may vary by environment.

## Project layout

```text
.
├── client/                  # Desktop companion and wake-word interaction
├── server/                  # FastAPI backend and application engines
│   └── static/              # Dashboard frontend assets
├── tests/                   # Automated tests
├── .env.example             # Environment configuration template
├── requirements.txt         # Python dependencies
├── setup_mac.sh             # macOS setup script
└── start.sh                 # Application startup script
```

## Security and privacy

- Never commit `.env` files or credentials.
- Screen, microphone and desktop-control access are powerful permissions; enable them deliberately.
- Review the requested action before confirming sensitive or irreversible operations.
- Local session data may be stored on the machine. Protect the device and its local files accordingly.

## License

See [LICENSE](LICENSE) for the applicable license and notices.