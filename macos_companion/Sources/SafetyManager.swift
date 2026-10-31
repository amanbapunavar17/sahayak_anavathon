//
// SafetyManager.swift
// SAHAYAK macOS Companion
//
// Handles:
// 1. Global Emergency Stop (Option + Escape)
// 2. Cancellation of running computer-control tasks and speech
// 3. User-guided Accessibility & Microphone permission verification
// 4. Safe communication without exposing secrets or unrestricted shell execution
//

import Cocoa
import AVFoundation
import Speech

@MainActor
final class SafetyManager: ObservableObject {
    static let shared = SafetyManager()

    @Published var lastAlertMessage: String = ""
    @Published var isShowingPermissionGuide: Bool = false

    private let speechSynth = NSSpeechSynthesizer()
    private let backendBaseURL = URL(string: "http://127.0.0.1:8080")!

    private init() {
        if let samantha = NSSpeechSynthesizer.availableVoices.first(where: { $0.rawValue.lowercased().contains("samantha") }) {
            speechSynth.setVoice(samantha)
        }
    }

    // MARK: - Global Emergency Stop (Task 4)
    func triggerEmergencyStop() {
        print("[SafetyManager] 🛑 EMERGENCY STOP TRIGGERED!")

        // 1. Silence local speech immediately
        speechSynth.stopSpeaking()

        // 2. Stop ongoing voice capture
        VoiceManager.shared.cancelRecording()
        WakeWordDetector.shared.pauseListening()

        // 3. Announce emergency stop aloud
        speechSynth.startSpeaking("Emergency stop activated. Halting all operations.")
        FloatingHUD.shared.showStatus(title: "Emergency Stop", message: "All operations halted immediately.", isError: true)

        // 4. Notify FastAPI backend to cancel pending tasks and stop TTS
        let cancelURL = backendBaseURL.appendingPathComponent("/api/emergency_stop")
        var request = URLRequest(url: cancelURL)
        request.httpMethod = "POST"
        request.timeoutInterval = 2.0

        let task = URLSession.shared.dataTask(with: request) { data, response, error in
            if let error = error {
                print("[SafetyManager] Emergency stop backend notification error: \(error.localizedDescription)")
            } else {
                print("[SafetyManager] Backend successfully confirmed emergency stop.")
            }
        }
        task.resume()
    }

    // MARK: - Permission Verification & Guidance (Task 4)
    func checkMicrophonePermission() -> Bool {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            return true
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                print("[SafetyManager] Microphone permission requested: \(granted)")
            }
            return false
        case .denied, .restricted:
            return false
        @unknown default:
            return false
        }
    }

    func checkSpeechRecognitionPermission() -> Bool {
        return SFSpeechRecognizer.authorizationStatus() == .authorized
    }

    func requestSpeechRecognitionPermission(completion: @escaping (Bool) -> Void) {
        SFSpeechRecognizer.requestAuthorization { status in
            Task { @MainActor in
                print("[SafetyManager] Speech recognition permission status: \(status.rawValue)")
                completion(status == .authorized)
            }
        }
    }

    func checkAccessibilityPermission() -> Bool {
        return AXIsProcessTrusted()
    }

    func promptAccessibilityPermission() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
        _ = AXIsProcessTrustedWithOptions(options as CFDictionary)
    }

    func openSystemSettings(for permission: String) {
        let urlString: String
        if permission == "microphone" {
            urlString = "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
        } else if permission == "speech" {
            urlString = "x-apple.systempreferences:com.apple.preference.security?Privacy_SpeechRecognition"
        } else {
            urlString = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
        }

        if let url = URL(string: urlString) {
            NSWorkspace.shared.open(url)
        }
    }

    func announcePermissionGuidance(for permission: String) {
        let message: String
        if permission == "microphone" {
            message = "Microphone access is needed for SAHAYAK. Please open System Settings, go to Privacy and Security, select Microphone, and enable SAHAYAK."
        } else if permission == "speech" {
            message = "Speech Recognition permission is required for SAHAYAK to hear the wake word. Please open System Settings, go to Privacy and Security, select Speech Recognition, and enable SAHAYAK."
        } else {
            message = "Accessibility access is required for global keyboard shortcuts and computer automation. Please open System Settings, go to Privacy and Security, select Accessibility, and enable SAHAYAK."
        }

        speechSynth.startSpeaking(message)
        FloatingHUD.shared.showStatus(title: "Permission Setup Required", message: message, isError: true)
    }
}

