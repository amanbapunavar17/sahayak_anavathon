//
// ActivationManager.swift
// SAHAYAK macOS Companion
//
// Task 5: Single Unified Activation Manager
// Coordinates:
//   METHOD A: "Hello SAHAYAK" (Voice Wake-Word)
//   METHOD B: Option + Space (Global Hotkey)
//   EMERGENCY STOP: Option + Escape
//
// Handles state transitions, prevents simultaneous activation conflicts,
// and ensures consistent voice-guided accessibility.
//

import Cocoa
import Speech
import AVFoundation

public enum AssistantState: String {
    case waitingForWakeWord = "Waiting for wake word"
    case wakeWordDetected = "Wake word detected"
    case listeningToCommand = "Listening to command"
    case processingCommand = "Processing command"
    case assistantResponding = "Assistant responding"
    case listeningDisabled = "Listening disabled"
    case permissionUnavailable = "Microphone permission unavailable"
}

@MainActor
final class ActivationManager: ObservableObject {
    static let shared = ActivationManager()

    @Published var currentState: AssistantState = .waitingForWakeWord
    @Published var statusMessage: String = "Ready"

    private let speechSynth = NSSpeechSynthesizer()
    private var isBusyProcessing: Bool = false

    private init() {
        configureVoice()
    }

    private func configureVoice() {
        if let samantha = NSSpeechSynthesizer.availableVoices.first(where: { $0.rawValue.lowercased().contains("samantha") }) {
            speechSynth.setVoice(samantha)
        }
        speechSynth.rate = 195
    }

    // MARK: - Method A: Voice Wake-Word Trigger ("Hello SAHAYAK")
    func handleWakeWordTriggered() {
        guard !isBusyProcessing else {
            print("[ActivationManager] Ignored wake word trigger: assistant is currently busy.")
            return
        }

        guard currentState != .listeningDisabled else {
            print("[ActivationManager] Ignored wake word: listening is disabled.")
            return
        }

        print("[ActivationManager] 🎯 Handling Wake Word 'Hello SAHAYAK' activation.")
        currentState = .wakeWordDetected
        isBusyProcessing = true

        // 1. Temporarily pause the background wake-word listener
        WakeWordDetector.shared.pauseListening()

        // 2. Bring SAHAYAK Companion to front and ensure web dashboard is open
        NSApp.activate(ignoringOtherApps: true)
        if let appDelegate = NSApp.delegate as? AppDelegate {
            appDelegate.showCompanionWindow()
        }
        if let url = URL(string: "http://127.0.0.1:8080") {
            NSWorkspace.shared.open(url)
        }

        // 3. Announce prompt: "Hello! I'm listening. How can I help you?"
        let greeting = "Hello! I'm listening. How can I help you?"
        FloatingHUD.shared.showStatus(title: "Hello SAHAYAK", message: greeting)
        
        speechSynth.stopSpeaking()
        speechSynth.startSpeaking(greeting)

        // 4. Begin command capture immediately after greeting prompt
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) { [weak self] in
            guard let self = self, self.isBusyProcessing else { return }
            self.currentState = .listeningToCommand
            FloatingHUD.shared.showListening()
            VoiceManager.shared.startDirectRecording { [weak self] recognizedText in
                self?.handleCommandCaptured(recognizedText)
            }
        }
    }

    // MARK: - Method B: Keyboard Shortcut Trigger (Option + Space)
    func handleHotkeyTriggered() {
        print("[ActivationManager] ⌨️ Handling Option+Space Hotkey activation.")

        if currentState == .listeningToCommand {
            print("[ActivationManager] Already recording: stopping early to submit command.")
            VoiceManager.shared.stopRecordingAndSend()
            return
        }

        guard SafetyManager.shared.checkMicrophonePermission() else {
            currentState = .permissionUnavailable
            SafetyManager.shared.announcePermissionGuidance(for: "microphone")
            return
        }

        isBusyProcessing = true
        WakeWordDetector.shared.pauseListening()

        speechSynth.stopSpeaking()
        speechSynth.startSpeaking("SAHAYAK listening.")
        currentState = .listeningToCommand
        FloatingHUD.shared.showListening()

        VoiceManager.shared.startDirectRecording { [weak self] recognizedText in
            self?.handleCommandCaptured(recognizedText)
        }
    }

    // MARK: - Command Processing & Backend Communication
    private func handleCommandCaptured(_ command: String) {
        let trimmed = command.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            print("[ActivationManager] No speech detected after activation.")
            let timeoutMsg = "I didn't hear anything. Ready for your command."
            FloatingHUD.shared.showStatus(title: "No Speech Detected", message: timeoutMsg)
            speechSynth.stopSpeaking()
            speechSynth.startSpeaking(timeoutMsg)
            finishInteraction()
            return
        }

        print("[ActivationManager] 🚀 Processing captured command: '\(trimmed)'")
        currentState = .processingCommand
        FloatingHUD.shared.showProcessing(query: trimmed)

        VoiceManager.shared.sendCommandToBackend(trimmed) { [weak self] result in
            Task { @MainActor in
                self?.handleBackendResponse(result)
            }
        }
    }

    private func handleBackendResponse(_ result: Result<[String: Any], Error>) {
        currentState = .assistantResponding

        switch result {
        case .failure(let error):
            print("[ActivationManager] Backend communication error: \(error.localizedDescription)")
            let errText = "SAHAYAK server is not reachable at localhost 8080. Please ensure start.sh is running."
            FloatingHUD.shared.showStatus(title: "Backend Unavailable", message: errText, isError: true)
            speakResponse(errText)
            finishInteraction()

        case .success(let json):
            if let requiresConfirm = json["requires_confirmation"] as? Bool, requiresConfirm {
                let prompt = json["confirmation_prompt"] as? String ?? "Sensitive operation requires confirmation."
                FloatingHUD.shared.showStatus(title: "⚠️ Confirmation Needed", message: prompt)
                speakResponse(prompt)
                finishInteraction()
                return
            }

            let spoken = json["spoken_response"] as? String ?? "Command executed."

            FloatingHUD.shared.showResponse(title: "SAHAYAK", message: spoken)
            // Note: The FastAPI backend already executes tts.speak(spoken, language=lang)
            // using the unified female voice (Samantha for English, Soumya for Kannada).
            // Do NOT call speakResponse here to prevent voice overlapping and duplicate speech.

            // Allow time for spoken response to finish, then return to wake-word mode
            let delay = max(2.5, Double(spoken.split(separator: " ").count) * 0.32)
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                self?.finishInteraction()
            }
        }
    }

    // MARK: - Return to Background Listening
    private func finishInteraction() {
        isBusyProcessing = false
        if WakeWordDetector.shared.isEnabled {
            currentState = .waitingForWakeWord
            WakeWordDetector.shared.startListening()
            print("[ActivationManager] 👂 Resumed background wake-word detection.")
        } else {
            currentState = .listeningDisabled
        }
    }

    // MARK: - Speech Synthesis Helper (Cleans Punctuation & Routes Kannada Voice)
    func speakResponse(_ text: String, language: String? = nil) {
        speechSynth.stopSpeaking()

        let isKannada = text.unicodeScalars.contains { $0.value >= 0x0C80 && $0.value <= 0x0CFF }
            || (language?.lowercased().starts(with: "kn") ?? false)

        // CRITICAL FIX: Strip all question marks and symbols so macOS voice NEVER says "question mark question mark"
        let cleanText = text
            .replacingOccurrences(of: "??", with: "")
            .replacingOccurrences(of: "?", with: "")
            .replacingOccurrences(of: "!", with: "")
            .replacingOccurrences(of: "*", with: "")
            .replacingOccurrences(of: "#", with: "")
            .replacingOccurrences(of: "\"", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)

        if isKannada {
            if let soumya = NSSpeechSynthesizer.availableVoices.first(where: {
                $0.rawValue.lowercased().contains("soumya") ||
                $0.rawValue.lowercased().contains("kn_in") ||
                $0.rawValue.lowercased().contains("kn-in")
            }) {
                speechSynth.setVoice(soumya)
            }
        } else {
            if let samantha = NSSpeechSynthesizer.availableVoices.first(where: { $0.rawValue.lowercased().contains("samantha") }) {
                speechSynth.setVoice(samantha)
            }
        }

        speechSynth.startSpeaking(cleanText)
    }

    // MARK: - Emergency Stop Handler
    func triggerEmergencyStop() {
        print("[ActivationManager] 🛑 EMERGENCY STOP ACTIVATED.")
        isBusyProcessing = false
        currentState = .listeningDisabled

        speechSynth.stopSpeaking()
        VoiceManager.shared.cancelRecording()
        WakeWordDetector.shared.pauseListening()

        FloatingHUD.shared.showStatus(title: "🛑 Emergency Stop", message: "All operations halted.", isError: true)
        speechSynth.startSpeaking("Emergency stop activated. All operations halted.")
    }
}
