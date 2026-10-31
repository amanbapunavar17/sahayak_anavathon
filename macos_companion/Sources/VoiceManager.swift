//
// VoiceManager.swift
// SAHAYAK macOS Companion
//
// Native macOS Voice Capture & On-Device Speech Recognition (M4 Apple Silicon)
// Communicates with FastAPI backend http://127.0.0.1:8080
//

import Cocoa
import Speech
import AVFoundation

@MainActor
final class VoiceManager: NSObject, ObservableObject, SFSpeechRecognizerDelegate {
    static let shared = VoiceManager()

    @Published var isRecording: Bool = false
    @Published var isProcessing: Bool = false
    @Published var recognizedText: String = ""

    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()
    private let speechSynth = NSSpeechSynthesizer()

    private var silenceTimer: Timer?
    private var maxRecordingTimer: Timer?
    private var onRecordingFinished: ((String) -> Void)?
    private let backendURL = URL(string: "http://127.0.0.1:8080/api/chat")!

    private override init() {
        super.init()
        speechRecognizer?.delegate = self
        if let rec = speechRecognizer, rec.supportsOnDeviceRecognition {
            print("[VoiceManager] On-device speech recognition supported on Apple Silicon.")
        }
    }

    // MARK: - Direct Recording for ActivationManager
    func startDirectRecording(completion: @escaping (String) -> Void) {
        self.onRecordingFinished = completion
        startRecording()
    }

    // MARK: - Global Activation (Option + Space)
    func activateVoiceInteraction() {
        ActivationManager.shared.handleHotkeyTriggered()
    }

    // MARK: - Audio Recording & Transcription
    private func startRecording() {
        cancelRecording()

        let node = audioEngine.inputNode
        let recordingFormat = node.outputFormat(forBus: 0)

        guard recordingFormat.sampleRate > 0 && recordingFormat.channelCount > 0 else {
            print("[VoiceManager] Invalid audio recording format.")
            FloatingHUD.shared.showStatus(title: "Microphone Error", message: "Audio input format is invalid.", isError: true)
            onRecordingFinished?("")
            return
        }

        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest = recognitionRequest else { return }

        recognitionRequest.shouldReportPartialResults = true
        // Set to false so recognition relies on reliable system recognition and never silently drops audio
        recognitionRequest.requiresOnDeviceRecognition = false

        isRecording = true
        recognizedText = ""

        recognitionTask = speechRecognizer?.recognitionTask(with: recognitionRequest) { [weak self] result, error in
            guard let self = self else { return }

            if let result = result {
                let transcription = result.bestTranscription.formattedString
                Task { @MainActor in
                    self.recognizedText = transcription
                    WakeWordDetector.shared.lastHeardSnippet = transcription
                    FloatingHUD.shared.showTranscribing(transcription)
                    self.resetSilenceTimer()
                }

                if result.isFinal {
                    Task { @MainActor in
                        self.stopRecordingAndSend()
                    }
                }
            }

            if let error = error {
                let nsError = error as NSError
                // 216 is recognition cancelled, 209 is silence timeout
                if nsError.code != 216 && nsError.code != 209 {
                    print("[VoiceManager] Speech recognition error: \(error.localizedDescription)")
                }
            }
        }

        node.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { [weak self] buffer, _ in
            guard let self = self else { return }
            self.recognitionRequest?.append(buffer)

            // Update live microphone VU meter while recording command
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
                    WakeWordDetector.shared.audioLevel = normalized
                }
            }
        }

        do {
            audioEngine.prepare()
            try audioEngine.start()
            print("[VoiceManager] Microphone stream started successfully.")
            // Allow up to 3.5s for user to begin speaking, then 1.3s between words
            resetSilenceTimer(interval: 3.5)
            // Safety cap: maximum 14s total per utterance to prevent runaway recording
            maxRecordingTimer?.invalidate()
            maxRecordingTimer = Timer.scheduledTimer(withTimeInterval: 14.0, repeats: false) { [weak self] _ in
                Task { @MainActor [weak self] in
                    self?.stopRecordingAndSend()
                }
            }
        } catch {
            print("[VoiceManager] Could not start audio engine: \(error.localizedDescription)")
            isRecording = false
            FloatingHUD.shared.showStatus(title: "Audio Error", message: "Could not start audio input.", isError: true)
            onRecordingFinished?("")
        }
    }

    private func resetSilenceTimer(interval: TimeInterval = 1.3) {
        silenceTimer?.invalidate()
        silenceTimer = Timer.scheduledTimer(withTimeInterval: interval, repeats: false) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self = self, self.isRecording else { return }
                if !self.recognizedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    print("[VoiceManager] Silence detected. Submitting command: '\(self.recognizedText)'")
                    self.stopRecordingAndSend()
                }
            }
        }
    }

    func stopRecordingAndSend() {
        silenceTimer?.invalidate()
        silenceTimer = nil
        maxRecordingTimer?.invalidate()
        maxRecordingTimer = nil

        guard isRecording else { return }
        isRecording = false

        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()

        let commandToSend = recognizedText.trimmingCharacters(in: .whitespacesAndNewlines)
        if let callback = onRecordingFinished {
            onRecordingFinished = nil
            callback(commandToSend)
            return
        }

        if commandToSend.isEmpty {
            FloatingHUD.shared.showStatus(title: "No Speech Detected", message: "Press Option+Space to speak again.")
            return
        }

        print("[VoiceManager] Final command to send: '\(commandToSend)'")
        FloatingHUD.shared.showProcessing(query: commandToSend)
        sendCommandToBackend(commandToSend)
    }

    func cancelRecording() {
        silenceTimer?.invalidate()
        silenceTimer = nil
        maxRecordingTimer?.invalidate()
        maxRecordingTimer = nil
        isRecording = false

        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
    }

    // MARK: - Backend Communication
    func sendCommandToBackend(_ message: String, completion: ((Result<[String: Any], Error>) -> Void)? = nil) {
        isProcessing = true

        var request = URLRequest(url: backendURL)
        request.httpMethod = "POST"
        request.addValue("application/json", forHTTPHeaderField: "Content-Type")
        request.addValue("sahayak-companion", forHTTPHeaderField: "X-Client")
        request.timeoutInterval = 30.0

        let body: [String: Any] = ["message": message]
        do {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        } catch {
            print("[VoiceManager] JSON encoding error: \(error.localizedDescription)")
            isProcessing = false
            completion?(.failure(error))
            return
        }

        let task = URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            guard let self = self else { return }

            Task { @MainActor in
                self.isProcessing = false

                if let error = error {
                    print("[VoiceManager] Backend unavailable: \(error.localizedDescription)")
                    if let comp = completion {
                        comp(.failure(error))
                    } else {
                        let errorMsg = "SAHAYAK server is not reachable at localhost 8080. Please ensure start.sh is running."
                        ActivationManager.shared.speakResponse(errorMsg)
                        FloatingHUD.shared.showStatus(title: "Backend Unavailable", message: errorMsg, isError: true)
                    }
                    return
                }

                guard let data = data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    let parseErr = NSError(domain: "SahayakCompanion", code: 500, userInfo: [NSLocalizedDescriptionKey: "Unparseable response"])
                    if let comp = completion {
                        comp(.failure(parseErr))
                    } else {
                        let msg = "Received unparseable response from SAHAYAK server."
                        ActivationManager.shared.speakResponse(msg)
                        FloatingHUD.shared.showStatus(title: "Response Error", message: msg, isError: true)
                    }
                    return
                }

                if let comp = completion {
                    comp(.success(json))
                } else {
                    // Check for sensitive confirmation
                    if let requiresConfirm = json["requires_confirmation"] as? Bool, requiresConfirm {
                        let prompt = json["confirmation_prompt"] as? String ?? "Sensitive operation requires confirmation."
                        ActivationManager.shared.speakResponse(prompt)
                        FloatingHUD.shared.showStatus(title: "⚠️ Confirmation Needed", message: prompt, isError: false)
                        return
                    }

                    // Normal response
                    let spoken = json["spoken_response"] as? String ?? "Command executed."
                    let actionDict = json["action"] as? [String: Any]
                    let lang = actionDict?["language"] as? String

                    FloatingHUD.shared.showResponse(title: "SAHAYAK", message: spoken)
                    ActivationManager.shared.speakResponse(spoken, language: lang)
                }
            }
        }
        task.resume()
    }
}

