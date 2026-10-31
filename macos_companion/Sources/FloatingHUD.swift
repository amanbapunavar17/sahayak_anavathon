//
// FloatingHUD.swift
// SAHAYAK macOS Companion
//
// Accessible, high-contrast, non-activating floating HUD window.
// Appears on top of all macOS applications without stealing keyboard focus.
//

import Cocoa
import SwiftUI

@MainActor
final class FloatingHUD: ObservableObject {
    static let shared = FloatingHUD()

    @Published var isVisible: Bool = false
    @Published var title: String = "SAHAYAK"
    @Published var subtitle: String = "Ready"
    @Published var isListening: Bool = false
    @Published var isError: Bool = false

    private var panel: NSPanel?
    private var dismissTimer: Timer?

    private init() {
        setupPanel()
    }

    private func setupPanel() {
        let p = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 440, height: 110),
            styleMask: [.nonactivatingPanel, .titled, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )

        p.isFloatingPanel = true
        p.level = .floating
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        p.titleVisibility = .hidden
        p.titlebarAppearsTransparent = true
        p.isMovableByWindowBackground = true
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = true

        let rootView = HUDContentView(hud: self)
        p.contentView = NSHostingView(rootView: rootView)

        // Center near top-center of primary screen (accessibility position)
        if let screen = NSScreen.main {
            let x = (screen.frame.width - 440) / 2.0
            let y = screen.frame.height - 180
            p.setFrameOrigin(NSPoint(x: x, y: y))
        }

        self.panel = p
    }

    func showListening() {
        dismissTimer?.invalidate()
        title = "🎙️ Listening..."
        subtitle = "Speak your command clearly (e.g., 'Open Safari and search for Python')"
        isListening = true
        isError = false
        isVisible = true
        panel?.orderFrontRegardless()
    }

    func showTranscribing(_ text: String) {
        dismissTimer?.invalidate()
        title = "Recognizing..."
        subtitle = text.isEmpty ? "..." : "\"\(text)\""
        isListening = true
        isError = false
        isVisible = true
        panel?.orderFrontRegardless()
    }

    func showProcessing(query: String) {
        dismissTimer?.invalidate()
        title = "Processing Command"
        subtitle = "\"\(query)\""
        isListening = false
        isError = false
        isVisible = true
        panel?.orderFrontRegardless()
    }

    func showResponse(title: String = "SAHAYAK", message: String) {
        dismissTimer?.invalidate()
        self.title = title
        self.subtitle = message
        self.isListening = false
        self.isError = false
        self.isVisible = true
        panel?.orderFrontRegardless()

        // Auto-hide after user has had time to read / hear response
        dismissTimer = Timer.scheduledTimer(withTimeInterval: 6.0, repeats: false) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.hide()
            }
        }
    }

    func showStatus(title: String, message: String, isError: Bool = false) {
        dismissTimer?.invalidate()
        self.title = title
        self.subtitle = message
        self.isListening = false
        self.isError = isError
        self.isVisible = true
        panel?.orderFrontRegardless()

        dismissTimer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: false) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.hide()
            }
        }
    }

    func hide() {
        dismissTimer?.invalidate()
        isVisible = false
        panel?.orderOut(nil)
    }
}

struct HUDContentView: View {
    @ObservedObject var hud: FloatingHUD

    var body: some View {
        HStack(spacing: 16) {
            // Visual indicator icon
            ZStack {
                Circle()
                    .fill(hud.isError ? Color.red.opacity(0.85) : (hud.isListening ? Color.orange.opacity(0.85) : Color.blue.opacity(0.85)))
                    .frame(width: 48, height: 48)

                Image(systemName: hud.isError ? "exclamationmark.triangle.fill" : (hud.isListening ? "mic.fill" : "sparkles"))
                    .font(.system(size: 22, weight: .bold))
                    .foregroundColor(.white)
            }
            .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 4) {
                Text(hud.title)
                    .font(.system(size: 15, weight: .bold, design: .rounded))
                    .foregroundColor(.white)

                Text(hud.subtitle)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundColor(Color.white.opacity(0.88))
                    .lineLimit(2)
            }

            Spacer()
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Color(nsColor: .windowBackgroundColor).opacity(0.92))
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(hud.isError ? Color.red.opacity(0.6) : (hud.isListening ? Color.orange.opacity(0.6) : Color.white.opacity(0.2)), lineWidth: 1.5)
                )
                .shadow(color: Color.black.opacity(0.35), radius: 12, x: 0, y: 6)
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(hud.title): \(hud.subtitle)")
    }
}

