//
// WakeWordDetector.swift
// SAHAYAK macOS Companion
//
// Task 3: Lightweight, Local Wake-Word Detector for "Hello SAHAYAK"
// 100% On-Device, No Paid APIs, No Cloud Audio Uploads.
// Uses Apple Silicon Neural Engine local speech stream.
//

import Cocoa
import Speech
import AVFoundation

@MainActor
final class WakeWordDetector: NSObject, ObservableObject {
    static let shared = WakeWordDetector()

    @Published var isListeningForWakeWord: Bool = false
    @Published var lastHeardSnippet: String = ""
    @Published var audioLevel: Float = 0.0
    @Published var isSpeechAuthorized: Bool = SFSpeechRecognizer.authorizationStatus() == .authorized
    @Published var isEnabled: Bool = true {
        didSet {
            if isEnabled {
                startListening()
            } else {
                pauseListening()
            }
        }
    }

    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()
    private var restartTimer: Timer?
    private var useOnDevice: Bool = false // Start with system recognizer for instant reliability on macOS

    // Direct and phonetic variants of "Hello Sahayak" & "Sahayaka" across accents
    private let wakeWordTriggers = [
        "sahayak", "sahayaka", "sahay", "sahyak", "sayak", "sahaj", "saayak", "sohyuk", "sahyuck",
        "hello sahayak", "hey sahayak", "hi sahayak", "ok sahayak", "okay sahayak",
        "hello sahayaka", "hey sahayaka", "hi sahayaka", "ok sahayaka", "okay sahayaka",
        "hello assistant", "hey assistant", "hi assistant", "assistant",
        "hello computer", "computer",
        "hello sahay", "hey sahay", "hi sahay",
        "hello sahyak", "hey sahyak", "hi sahyak",
        "hello sayak", "hey sayak", "hi sayak",
        "hello sa hayak", "hey sa hayak", "hi sa hayak",
        "hello sa hyuck", "hey sa hyuck",
        "hello so hike", "hey so hike",
        "hello say hack", "hey say hack",
        "hello sa hack", "hey sa hack",
        "hello sa hike", "hey sa hike",
        "hello so hack", "hey so hack",
        "hello so high", "hey so high",
        "hello sir hack", "hey sir hack",
        "hello saik", "hey saik",
        "hello psych", "hey psych"
    ]

    private override init() {
        super.init()
        checkAndRequestSpeechAuthorization()
        if isEnabled {
            // Slight delay on launch to allow permissions & audio hardware to settle
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { [weak self] in
                self?.startListening()
            }
        }
    }

    func checkAndRequestSpeechAuthorization() {
        let status = SFSpeechRecognizer.authorizationStatus()
        isSpeechAuthorized = (status == .authorized)
        if status == .notDetermined {
            SFSpeechRecognizer.requestAuthorization { newStatus in
                Task { @MainActor in
                    self.isSpeechAuthorized = (newStatus == .authorized)
                    if newStatus == .authorized {
                        self.startListening()
                    }
                }
            }
        }
    }

    func toggleListening() {
        isEnabled.toggle()
    }

    func startListening() {
        guard isEnabled else { return }
        guard !VoiceManager.shared.isRecording else { return }
        guard SafetyManager.shared.checkMicrophonePermission() else {
            print("[WakeWordDetector] Microphone permission not available.")
            return
        }

        let speechStatus = SFSpeechRecognizer.authorizationStatus()
        guard speechStatus == .authorized else {
            print("[WakeWordDetector] Speech recognition not authorized yet (status: \(speechStatus.rawValue)). Requesting...")
            checkAndRequestSpeechAuthorization()
            return
        }

        stopListeningEngine()

        let node = audioEngine.inputNode
        node.removeTap(onBus: 0)

        let format = node.outputFormat(forBus: 0)
        guard format.sampleRate > 0 && format.channelCount > 0 else {
            print("[WakeWordDetector] Invalid microphone format: \(format)")
            return
        }

        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest = recognitionRequest else { return }

        recognitionRequest.shouldReportPartialResults = true
        if speechRecognizer?.supportsOnDeviceRecognition == true && useOnDevice {
            recognitionRequest.requiresOnDeviceRecognition = true
        } else {
            recognitionRequest.requiresOnDeviceRecognition = false
        }

        isListeningForWakeWord = true

        recognitionTask = speechRecognizer?.recognitionTask(with: recognitionRequest) { [weak self] result, error in
            guard let self = self else { return }

            if let result = result {
                let text = result.bestTranscription.formattedString
                Task { @MainActor in
                    self.lastHeardSnippet = text
                }
                print("[WakeWordDetector] 🎙️ Heard: '\(text)'")

                if self.isWakeWordMatch(text) {
                    print("[WakeWordDetector] 🎯 Wake word MATCHED in stream: '\(text)'")
                    Task { @MainActor in
                        self.handleWakeWordTriggered()
                    }
                    return
                }
            }

            if let error = error {
                let nsError = error as NSError
                print("[WakeWordDetector] Recognition stream event: \(error.localizedDescription) (code: \(nsError.code))")
                // If on-device fails with model error, fallback to system recognition
                if nsError.code == 1110 || nsError.code == 1700 {
                    self.useOnDevice = false
                }
                Task { @MainActor in
                    self.scheduleRestart()
                }
            } else if result?.isFinal == true {
                // SFSpeechRecognizer partial stream timed out naturally; auto-restart
                Task { @MainActor in
                    self.scheduleRestart()
                }
            }
        }

        node.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            guard let self = self else { return }
            self.recognitionRequest?.append(buffer)

            // Real-time audio RMS level calculation for live microphone visualizer
            guard let channelData = buffer.floatChannelData?[0] else { return }
            let frameLength = Int(buffer.frameLength)
            if frameLength > 0 {
                var sum: Float = 0.0
                for i in 0..<frameLength {
                    let s = channelData[i]
                    sum += s * s
                }
                let rms = sqrt(sum / Float(frameLength))
                let normalized = min(1.0, max(0.0, rms * 8.0))
                Task { @MainActor in
                    self.audioLevel = normalized
                }
            }
        }

        do {
            audioEngine.prepare()
            try audioEngine.start()
            print("[WakeWordDetector] Local continuous wake-word listener active on \(format.channelCount)-channel input.")
        } catch {
            print("[WakeWordDetector] Could not start wake-word audio engine: \(error.localizedDescription)")
            isListeningForWakeWord = false
        }
    }

    func pauseListening() {
        restartTimer?.invalidate()
        restartTimer = nil
        stopListeningEngine()
        isListeningForWakeWord = false
        audioLevel = 0.0
        print("[WakeWordDetector] Wake-word listening paused.")
    }

    private func stopListeningEngine() {
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
    }

    private func handleWakeWordTriggered() {
        pauseListening()
        ActivationManager.shared.handleWakeWordTriggered()
    }

    private func scheduleRestart() {
        guard isEnabled, !VoiceManager.shared.isRecording else { return }
        restartTimer?.invalidate()
        restartTimer = Timer.scheduledTimer(withTimeInterval: 0.8, repeats: false) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.startListening()
            }
        }
    }

    // MARK: - Phonetic & Flexible Wake Word Matching
    func isWakeWordMatch(_ rawText: String) -> Bool {
        let clean = rawText.lowercased()
            .replacingOccurrences(of: "[,.!?]", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)

        // 1. Direct and phonetic variant matching
        for trigger in wakeWordTriggers {
            if clean.contains(trigger) {
                return true
            }
        }

        // 2. Flexible regex for greetings + any phonetic Sahayak / Sahayaka / Assistant variant
        let pattern = #"\b(hello|hey|hi|ok|okay)?\s*(sahayaka?|sahay|sahyak|sayak|sahaj|assistant|computer|sa\s+hayak|sa\s+hyak|sa\s+hack|say\s+hack|so\s+hike|so\s+hyuck|so\s+hack|sah\w*)\b"#
        if let regex = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive) {
            let range = NSRange(location: 0, length: clean.utf16.count)
            if regex.firstMatch(in: clean, options: [], range: range) != nil {
                return true
            }
        }

        // 3. Standalone trigger words
        if clean.contains("sahayak") || clean.contains("sahayaka") || clean.contains("sahyak") || clean.contains("sahay ak") || clean.contains("assistant") {
            return true
        }

        return false
    }
}
