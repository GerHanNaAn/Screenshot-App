import AppKit

@main struct OverlayPreview {
    static func main() {
        guard CommandLine.arguments.count >= 3,
              let screen = NSScreen.main,
              let data = try? Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])),
              let document = ScreenshotDocument(data: data) else {
            fatalError("Usage: overlay-preview image.png history-directory")
        }
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        let history = HistoryStore(directoryURL: URL(fileURLWithPath: CommandLine.arguments[2]))
        let overlay = FullscreenCaptureOverlay(document: document, screen: screen, history: history)
        overlay.onClose = { app.terminate(nil) }
        overlay.present()
        DispatchQueue.main.asyncAfter(deadline: .now() + 900) { app.terminate(nil) }
        app.run()
    }
}
