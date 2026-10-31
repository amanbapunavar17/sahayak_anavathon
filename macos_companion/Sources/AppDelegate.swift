//
// AppDelegate.swift
// SAHAYAK macOS Companion
//
// Task 1: Background Menu-Bar Accessory Application
// Task 2: Option + Space Global Hotkey Registration
// Task 4: Option + Escape Global Emergency Stop
//

import Cocoa
import Carbon
import SwiftUI
import Speech

let kSahayakActivateHotKeyID: UInt32 = 1
let kSahayakEmergencyHotKeyID: UInt32 = 2

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var statusItem: NSStatusItem!
    private var mainWindow: NSWindow?
    private var activateHotKeyRef: EventHotKeyRef?
    private var emergencyHotKeyRef: EventHotKeyRef?
    private var globalEventMonitor: Any?
    private var statusTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        print("[AppDelegate] SAHAYAK Companion launched.")

        // 1. Run as regular application with Dock visibility & accessible window
        NSApp.setActivationPolicy(.regular)

        // 2. Setup Menu Bar Status Item
        setupStatusItem()

        // 3. Register Global Shortcuts (Option+Space, Option+Escape)
        registerGlobalHotKeys()

        // 4. Initial Permission Checks
        checkPermissionsOnLaunch()

        // 5. Open Accessible Companion Window on launch
        showCompanionWindow()

        // 6. Start Wake Word listener if enabled
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            WakeWordDetector.shared.startListening()
        }

        // 7. Monitor Backend Status periodically
        startBackendStatusMonitor()

        // 8. Voice-guided onboarding announcement (Task 7)
        let onboardingSpeech = "Welcome to SAHAYAK. To activate me using your voice, I need permission to use your microphone. Say Hello SAHAYAK, or press Option Space at any time."
        ActivationManager.shared.speakResponse(onboardingSpeech)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            showCompanionWindow()
        }
        return true
    }

    func showCompanionWindow() {
        if mainWindow == nil {
            let window = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 500, height: 560),
                styleMask: [.titled, .closable, .miniaturizable, .resizable],
                backing: .buffered,
                defer: false
            )
            window.center()
            window.title = "SAHAYAK — Your Voice. Your Freedom."
            window.contentViewController = NSHostingController(rootView: CompanionView())
            window.isReleasedWhenClosed = false
            window.delegate = self
            self.mainWindow = window
        }
        mainWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationWillTerminate(_ notification: Notification) {
        print("[AppDelegate] SAHAYAK Companion terminating safely.")
        if let ref = activateHotKeyRef {
            UnregisterEventHotKey(ref)
        }
        if let ref = emergencyHotKeyRef {
            UnregisterEventHotKey(ref)
        }
        if let monitor = globalEventMonitor {
            NSEvent.removeMonitor(monitor)
        }
        statusTimer?.invalidate()
        VoiceManager.shared.cancelRecording()
        WakeWordDetector.shared.pauseListening()
    }

    // MARK: - Menu Bar Status Item
    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.title = "🎙️ SAHAYAK"
            button.toolTip = "SAHAYAK Accessibility Assistant (⌥Space to activate)"
        }

        buildMenu()
    }

    private func buildMenu(backendOnline: Bool = true) {
        let menu = NSMenu()

        let activateItem = NSMenuItem(title: "🎙️ Activate Voice (⌥Space)", action: #selector(handleActivateClicked), keyEquivalent: "")
        menu.addItem(activateItem)

        let stopItem = NSMenuItem(title: "🛑 Emergency Stop (⌥Esc)", action: #selector(handleEmergencyStopClicked), keyEquivalent: "")
        menu.addItem(stopItem)

        let showWindowItem = NSMenuItem(title: "🖥️ Show Assistant Window", action: #selector(handleShowWindow), keyEquivalent: "")
        menu.addItem(showWindowItem)

        menu.addItem(NSMenuItem.separator())

        let dashboardItem = NSMenuItem(title: "🌐 Open Web Dashboard", action: #selector(handleOpenDashboard), keyEquivalent: "")
        menu.addItem(dashboardItem)

        let wakeWordTitle = WakeWordDetector.shared.isEnabled ? "👂 Wake Word ('Hello SAHAYAK'): Enabled" : "👂 Wake Word: Disabled"
        let wakeWordItem = NSMenuItem(title: wakeWordTitle, action: #selector(handleToggleWakeWord), keyEquivalent: "")
        menu.addItem(wakeWordItem)

        let permItem = NSMenuItem(title: "🔒 Permission Setup Guide", action: #selector(handleOpenPermissionGuide), keyEquivalent: "")
        menu.addItem(permItem)

        menu.addItem(NSMenuItem.separator())

        let statusText = backendOnline ? "🟢 Backend: Online (localhost:8080)" : "🔴 Backend: Offline"
        let statusMenuItem = NSMenuItem(title: statusText, action: nil, keyEquivalent: "")
        statusMenuItem.isEnabled = false
        menu.addItem(statusMenuItem)

        menu.addItem(NSMenuItem.separator())

        let quitItem = NSMenuItem(title: "Quit SAHAYAK Companion", action: #selector(handleQuit), keyEquivalent: "q")
        menu.addItem(quitItem)

        statusItem.menu = menu
    }

    // MARK: - Global Hotkeys (Carbon API + NSEvent Tap)
    private func registerGlobalHotKeys() {
        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))

        InstallEventHandler(GetApplicationEventTarget(), { (nextHandler, theEvent, userData) -> OSStatus in
            var hotKeyID = EventHotKeyID()
            let status = GetEventParameter(theEvent, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil, MemoryLayout<EventHotKeyID>.size, nil, &hotKeyID)

            if status == noErr {
                Task { @MainActor in
                    if hotKeyID.id == kSahayakActivateHotKeyID {
                        print("[AppDelegate] 🎯 Global Option+Space hotkey triggered!")
                        ActivationManager.shared.handleHotkeyTriggered()
                    } else if hotKeyID.id == kSahayakEmergencyHotKeyID {
                        print("[AppDelegate] 🛑 Global Option+Escape emergency stop triggered!")
                        SafetyManager.shared.triggerEmergencyStop()
                    }
                }
            }
            return noErr
        }, 1, &eventType, nil, nil)

        // KeyCode 49 = Space, Option Key = 0x0800
        let activateID = EventHotKeyID(signature: OSType(0x53414831), id: kSahayakActivateHotKeyID)
        let actErr = RegisterEventHotKey(49, UInt32(optionKey), activateID, GetApplicationEventTarget(), 0, &activateHotKeyRef)
        if actErr == noErr {
            print("[AppDelegate] Registered Option+Space global hotkey successfully.")
        } else {
            print("[AppDelegate] Warning: Option+Space registration returned \(actErr)")
        }

        // KeyCode 53 = Escape, Option Key = 0x0800
        let emergencyID = EventHotKeyID(signature: OSType(0x53414832), id: kSahayakEmergencyHotKeyID)
        let emErr = RegisterEventHotKey(53, UInt32(optionKey), emergencyID, GetApplicationEventTarget(), 0, &emergencyHotKeyRef)
        if emErr == noErr {
            print("[AppDelegate] Registered Option+Escape global emergency hotkey successfully.")
        }

        // Supplementary NSEvent Global Monitor for redundancy
        globalEventMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { event in
            // Option modifier check
            if event.modifierFlags.contains(.option) {
                if event.keyCode == 49 { // Space
                    Task { @MainActor in
                        ActivationManager.shared.handleHotkeyTriggered()
                    }
                } else if event.keyCode == 53 { // Escape
                    Task { @MainActor in
                        SafetyManager.shared.triggerEmergencyStop()
                    }
                }
            }
        }
    }

    // MARK: - Menu Actions
    @objc private func handleActivateClicked() {
        VoiceManager.shared.activateVoiceInteraction()
    }

    @objc private func handleEmergencyStopClicked() {
        SafetyManager.shared.triggerEmergencyStop()
    }

    @objc private func handleShowWindow() {
        showCompanionWindow()
    }

    @objc private func handleOpenDashboard() {
        if let url = URL(string: "http://127.0.0.1:8080") {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func handleToggleWakeWord() {
        WakeWordDetector.shared.toggleListening()
        buildMenu()
        let msg = WakeWordDetector.shared.isEnabled ? "Wake word listening enabled." : "Wake word listening paused."
        NSSpeechSynthesizer().startSpeaking(msg)
    }

    @objc private func handleOpenPermissionGuide() {
        SafetyManager.shared.announcePermissionGuidance(for: "accessibility")
        SafetyManager.shared.openSystemSettings(for: "accessibility")
    }

    @objc private func handleQuit() {
        NSApp.terminate(nil)
    }

    // MARK: - Status Monitoring
    private func checkPermissionsOnLaunch() {
        if !SafetyManager.shared.checkAccessibilityPermission() {
            print("[AppDelegate] Accessibility permission not granted yet.")
            SafetyManager.shared.promptAccessibilityPermission()
        }
        if !SafetyManager.shared.checkMicrophonePermission() {
            print("[AppDelegate] Microphone permission not granted yet.")
            AVCaptureDevice.requestAccess(for: .audio) { _ in }
        }
        if SFSpeechRecognizer.authorizationStatus() == .notDetermined {
            SFSpeechRecognizer.requestAuthorization { status in
                print("[AppDelegate] SFSpeechRecognizer authorization status: \(status.rawValue)")
                if status == .authorized {
                    Task { @MainActor in
                        WakeWordDetector.shared.startListening()
                    }
                }
            }
        }
    }

    private func startBackendStatusMonitor() {
        statusTimer = Timer.scheduledTimer(withTimeInterval: 10.0, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            let url = URL(string: "http://127.0.0.1:8080/api/status")!
            var req = URLRequest(url: url)
            req.timeoutInterval = 2.0
            URLSession.shared.dataTask(with: req) { [weak self] _, response, error in
                let isOnline = (error == nil && (response as? HTTPURLResponse)?.statusCode == 200)
                Task { @MainActor [weak self] in
                    self?.buildMenu(backendOnline: isOnline)
                }
            }.resume()
        }
    }
}
