//
// main.swift
// SAHAYAK macOS Companion Entry Point
//

import Cocoa

@main
struct SahayakCompanionApp {
    @MainActor
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        _ = NSApplicationMain(CommandLine.argc, CommandLine.unsafeArgv)
    }
}
