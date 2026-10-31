//
// CompanionView.swift
// SAHAYAK macOS Companion
//
// Task 2, 7: Accessible Companion Window & Voice-Guided Onboarding
// Displays live assistant state, permission status, keyboard shortcuts,
// live microphone feedback & volume meter, and accessible controls.
//

import SwiftUI
import Speech
import AVFoundation

@MainActor
final class CompanionViewModel: ObservableObject {
    @Published var hasMicPermission: Bool = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
    @Published var hasSpeechPermission: Bool = SFSpeechRecognizer.authorizationStatus() == .authorized
    @Published var hasAxPermission: Bool = AXIsProcessTrusted()

    func refreshPermissions() {
        hasMicPermission = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        hasSpeechPermission = SFSpeechRecognizer.authorizationStatus() == .authorized
        hasAxPermission = AXIsProcessTrusted()
    }

    func requestMicPermission() {
        AVCaptureDevice.requestAccess(for: .audio) { granted in
            Task { @MainActor in
                self.hasMicPermission = granted
                if granted {
                    self.requestSpeechPermission()
                } else {
                    SafetyManager.shared.openSystemSettings(for: "microphone")
                }
            }
        }
    }

    func requestSpeechPermission() {
        SFSpeechRecognizer.requestAuthorization { status in
            Task { @MainActor in
                self.hasSpeechPermission = (status == .authorized)
                if status == .authorized {
                    WakeWordDetector.shared.isSpeechAuthorized = true
                    WakeWordDetector.shared.startListening()
                    ActivationManager.shared.speakResponse("Permissions granted. SAHAYAK is listening for Hello SAHAYAK.")
                } else {
                    SafetyManager.shared.openSystemSettings(for: "speech")
                }
            }
        }
    }
}

struct CompanionView: View {
    @ObservedObject var activationManager = ActivationManager.shared
    @ObservedObject var wakeWordDetector = WakeWordDetector.shared
    @ObservedObject var viewModel = CompanionViewModel()

    var body: some View {
        VStack(spacing: 16) {
            // Header
            HStack {
                Text("🎙️ SAHAYAK")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundColor(.primary)
                Spacer()
                Text("Phase 2")
                    .font(.caption)
                    .padding(4)
                    .background(Color.blue.opacity(0.15))
                    .cornerRadius(4)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("SAHAYAK Assistant Phase 2")

            Divider()

            // Live Status & Real-Time Audio Level Card
            VStack(alignment: .leading, spacing: 8) {
                Text("Assistant Status")
                    .font(.subheadline)
                    .foregroundColor(.secondary)

                HStack {
                    Circle()
                        .fill(statusColor)
                        .frame(width: 12, height: 12)
                    Text(activationManager.currentState.rawValue)
                        .font(.headline)
                        .foregroundColor(.primary)
                    Spacer()
                }
                .padding(10)
                .background(Color(NSColor.controlBackgroundColor))
                .cornerRadius(8)

                // Live Real-Time Microphone Volume Meter
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Image(systemName: wakeWordDetector.audioLevel > 0.06 ? "waveform.path.ecg" : "mic.fill")
                            .foregroundColor(wakeWordDetector.audioLevel > 0.06 ? .green : .secondary)
                        Text("Microphone Activity:")
                            .font(.caption)
                            .fontWeight(.medium)
                        Spacer()
                        Text(wakeWordDetector.audioLevel > 0.06 ? "🟢 Sound Detected (\(Int(wakeWordDetector.audioLevel * 100))%)" : "⚪ Silent (Listening)")
                            .font(.caption)
                            .foregroundColor(wakeWordDetector.audioLevel > 0.06 ? .green : .secondary)
                    }

                    // Visual bouncing VU Meter bar
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            RoundedRectangle(cornerRadius: 4)
                                .fill(Color.gray.opacity(0.25))
                                .frame(height: 8)
                            RoundedRectangle(cornerRadius: 4)
                                .fill(wakeWordDetector.audioLevel > 0.06 ? Color.green : Color.blue.opacity(0.4))
                                .frame(width: max(6, geo.size.width * CGFloat(wakeWordDetector.audioLevel)), height: 8)
                                .animation(.easeOut(duration: 0.08), value: wakeWordDetector.audioLevel)
                        }
                    }
                    .frame(height: 8)
                }
                .padding(8)
                .background(Color(NSColor.controlBackgroundColor).opacity(0.6))
                .cornerRadius(6)

                // Live microphone transcribed words
                if !wakeWordDetector.lastHeardSnippet.isEmpty {
                    HStack {
                        Image(systemName: "quote.opening")
                            .foregroundColor(.blue)
                        Text("Heard: \"\(wakeWordDetector.lastHeardSnippet)\"")
                            .font(.caption)
                            .foregroundColor(.secondary)
                            .lineLimit(1)
                        Spacer()
                    }
                    .padding(.horizontal, 4)
                }
            }

            // How to Activate Card
            VStack(alignment: .leading, spacing: 6) {
                Text("How to Activate")
                    .font(.subheadline)
                    .foregroundColor(.secondary)

                HStack {
                    Image(systemName: "mic.fill")
                        .foregroundColor(.blue)
                    Text("Voice Wake-Word:")
                        .fontWeight(.semibold)
                    Text("\"Hello SAHAYAK\" / \"Sahayaka\"")
                        .foregroundColor(.blue)
                    Spacer()
                    Text(wakeWordDetector.isEnabled ? "Enabled" : "Paused")
                        .font(.caption)
                        .foregroundColor(wakeWordDetector.isEnabled ? .green : .orange)
                }

                HStack {
                    Image(systemName: "keyboard.fill")
                        .foregroundColor(.purple)
                    Text("Keyboard Shortcut:")
                        .fontWeight(.semibold)
                    Text("⌥ Space (Option + Space)")
                        .foregroundColor(.purple)
                    Spacer()
                }

                HStack {
                    Image(systemName: "exclamationmark.octagon.fill")
                        .foregroundColor(.red)
                    Text("Emergency Stop:")
                        .fontWeight(.semibold)
                    Text("⌥ Esc (Option + Escape)")
                        .foregroundColor(.red)
                    Spacer()
                }
            }
            .padding(10)
            .background(Color(NSColor.controlBackgroundColor))
            .cornerRadius(8)

            // Permissions Checklist
            VStack(alignment: .leading, spacing: 6) {
                Text("System Permissions")
                    .font(.subheadline)
                    .foregroundColor(.secondary)

                // Microphone
                HStack {
                    Image(systemName: viewModel.hasMicPermission ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .foregroundColor(viewModel.hasMicPermission ? .green : .red)
                    Text("Microphone Access")
                    Spacer()
                    if !viewModel.hasMicPermission {
                        Button("Grant Access") {
                            viewModel.requestMicPermission()
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                    } else {
                        Text("Authorized")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }

                // Speech Recognition
                HStack {
                    Image(systemName: viewModel.hasSpeechPermission ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .foregroundColor(viewModel.hasSpeechPermission ? .green : .red)
                    Text("Speech Recognition")
                    Spacer()
                    if !viewModel.hasSpeechPermission {
                        Button("Authorize Speech") {
                            viewModel.requestSpeechPermission()
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                    } else {
                        Text("Authorized")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }

                // Accessibility
                HStack {
                    Image(systemName: viewModel.hasAxPermission ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .foregroundColor(viewModel.hasAxPermission ? .green : .red)
                    Text("Accessibility Automation")
                    Spacer()
                    if !viewModel.hasAxPermission {
                        Button("Open Settings") {
                            SafetyManager.shared.openSystemSettings(for: "accessibility")
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                    } else {
                        Text("Authorized")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }
            .padding(10)
            .background(Color(NSColor.controlBackgroundColor))
            .cornerRadius(8)

            // Primary Activation Buttons
            VStack(spacing: 8) {
                HStack(spacing: 10) {
                    Button(action: {
                        activationManager.handleWakeWordTriggered()
                    }) {
                        Label("🔘 Test Wake Word ('Hello Sahayak')", systemImage: "sparkles")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.blue)
                    .controlSize(.large)

                    Button(action: {
                        wakeWordDetector.toggleListening()
                    }) {
                        Label(wakeWordDetector.isEnabled ? "Pause Listener" : "Resume Listener",
                              systemImage: wakeWordDetector.isEnabled ? "pause.fill" : "play.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                }

                HStack {
                    Button(action: {
                        activationManager.handleHotkeyTriggered()
                    }) {
                        Label("⌥ Space", systemImage: "keyboard")
                    }
                    .buttonStyle(.bordered)

                    Button(action: {
                        SafetyManager.shared.triggerEmergencyStop()
                    }) {
                        Label("Emergency Stop (⌥Esc)", systemImage: "stop.fill")
                            .foregroundColor(.red)
                    }
                    .buttonStyle(.bordered)

                    Spacer()

                    Button("Open Web Dashboard") {
                        if let url = URL(string: "http://127.0.0.1:8080") {
                            NSWorkspace.shared.open(url)
                        }
                    }
                    .buttonStyle(.bordered)
                }
            }
        }
        .padding(18)
        .frame(width: 500, height: 600)
        .onAppear {
            viewModel.refreshPermissions()
        }
    }

    private var statusColor: Color {
        switch activationManager.currentState {
        case .waitingForWakeWord:
            return .green
        case .wakeWordDetected, .listeningToCommand:
            return .blue
        case .processingCommand:
            return .purple
        case .assistantResponding:
            return .cyan
        case .listeningDisabled:
            return .orange
        case .permissionUnavailable:
            return .red
        }
    }
}
