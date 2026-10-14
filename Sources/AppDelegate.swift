import AppKit
import Carbon
import CoreGraphics
import ScreenCaptureKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var editors: [Editor] = []
    private var overlay: FullscreenCaptureOverlay?
    private var settingsWindow: SettingsWindow?
    private var statusCaptureItems: [CaptureAction: NSMenuItem] = [:]
    private var hotKeys: [CaptureAction: EventHotKeyRef] = [:]
    private var hotKeyHandler: EventHandlerRef?
    private var captureInProgress = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        installHotKeyHandler()
        _ = registerHotKeys()
    }
    func application(_ sender: NSApplication, openFile filename: String) -> Bool {
        loadImage(at: URL(fileURLWithPath: filename))
    }
    private func buildMenu() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let image = NSImage(systemSymbolName: "camera.viewfinder", accessibilityDescription: "JoxiLite") {
            image.isTemplate = true
            statusItem.button?.image = image
        } else { statusItem.button?.title = "✂︎" }
        let statusMenu = NSMenu()
        statusCaptureItems[.area] = add("Выделить область", to: statusMenu, action: #selector(captureArea))
        statusCaptureItems[.window] = add("Снять окно", to: statusMenu, action: #selector(captureWindow))
        statusCaptureItems[.screen] = add("Снять экран под курсором", to: statusMenu, action: #selector(captureScreen))
        add("Экран через 3 секунды", to: statusMenu, action: #selector(captureDelayed))
        statusMenu.addItem(.separator())
        add("Открыть снимок…", to: statusMenu, action: #selector(openImage))
        add("История снимков…", to: statusMenu, action: #selector(openHistory))
        statusMenu.addItem(.separator())
        add("Настройки…", to: statusMenu, action: #selector(showSettings))
        add("Выход", to: statusMenu, action: #selector(quit))
        statusItem.menu = statusMenu

        let mainMenu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        add("Настройки…", to: appMenu, action: #selector(showSettings), key: ",")
        appMenu.addItem(.separator())
        add("Выход из JoxiLite", to: appMenu, action: #selector(quit), key: "q")
        appItem.submenu = appMenu; mainMenu.addItem(appItem)
        let fileItem = NSMenuItem()
        let fileMenu = NSMenu(title: "Файл")
        add("Выделить область", to: fileMenu, action: #selector(captureArea))
        add("Снять окно", to: fileMenu, action: #selector(captureWindow))
        add("Снять экран под курсором", to: fileMenu, action: #selector(captureScreen))
        add("Открыть снимок…", to: fileMenu, action: #selector(openImage), key: "o")
        fileMenu.addItem(.separator())
        add("Сохранить…", to: fileMenu, action: #selector(saveCurrent), key: "s")
        add("Копировать PNG", to: fileMenu, action: #selector(copyCurrent), key: "c")
        fileItem.submenu = fileMenu; mainMenu.addItem(fileItem)
        let editItem = NSMenuItem()
        let editMenu = NSMenu(title: "Правка")
        add("Отменить", to: editMenu, action: #selector(undoCurrent), key: "z")
        let redo = add("Повторить", to: editMenu, action: #selector(redoCurrent), key: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editItem.submenu = editMenu; mainMenu.addItem(editItem)
        NSApp.mainMenu = mainMenu
        updateCaptureMenuTitles()
    }
    @discardableResult
    private func add(_ title: String, to menu: NSMenu, action: Selector, key: String = "") -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        menu.addItem(item)
        return item
    }
    private func updateCaptureMenuTitles() {
        for action in CaptureAction.allCases {
            let suffix = AppSettings.shared.hotKey(for: action).map { "  \($0.title)" } ?? ""
            statusCaptureItems[action]?.title = action.title + suffix
        }
    }
    private func installHotKeyHandler() {
        let handler: EventHandlerUPP = { _, event, userData in
            guard let event, let userData else { return noErr }
            let delegate = Unmanaged<AppDelegate>.fromOpaque(userData).takeUnretainedValue()
            var hotKeyID = EventHotKeyID(signature: 0, id: 0)
            var size = 0
            let result = GetEventParameter(event, EventParamName(kEventParamDirectObject),
                                           EventParamType(typeEventHotKeyID), nil,
                                           MemoryLayout<EventHotKeyID>.size, &size, &hotKeyID)
            if result == noErr, hotKeyID.signature == OSType(0x4A584C54),
               let action = CaptureAction(rawValue: Int(hotKeyID.id)) {
                DispatchQueue.main.async { delegate.runCapture(action) }
            }
            return noErr
        }
        var event = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                  eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), handler, 1, &event,
                            Unmanaged.passUnretained(self).toOpaque(), &hotKeyHandler)
    }
    private func unregisterHotKeys() {
        for hotKey in hotKeys.values { UnregisterEventHotKey(hotKey) }
        hotKeys.removeAll()
    }
    @discardableResult
    private func registerHotKeys() -> String? {
        unregisterHotKeys()
        updateCaptureMenuTitles()
        var errorMessage: String?
        for action in CaptureAction.allCases {
            guard let shortcut = AppSettings.shared.hotKey(for: action) else { continue }
            let id = EventHotKeyID(signature: OSType(0x4A584C54), id: UInt32(action.rawValue))
            var reference: EventHotKeyRef?
            let result = RegisterEventHotKey(UInt32(shortcut.keyCode), shortcut.modifiers,
                                             id, GetApplicationEventTarget(), 0, &reference)
            if result == noErr, let reference { hotKeys[action] = reference }
            else { errorMessage = "Не удалось включить \(shortcut.title) для «\(action.title)» (код \(result))." }
        }
        return errorMessage
    }
    private func runCapture(_ action: CaptureAction) {
        switch action {
        case .area: captureArea()
        case .window: captureWindow()
        case .screen: captureScreen()
        }
    }
    @objc private func showSettings() {
        if settingsWindow == nil {
            let controller = SettingsWindow()
            controller.onSettingsChanged = { [weak self] in self?.registerHotKeys() }
            controller.onRecordingChanged = { [weak self] recording in
                if recording { self?.unregisterHotKeys() }
                else { _ = self?.registerHotKeys() }
            }
            settingsWindow = controller
        }
        settingsWindow?.present()
    }
    @objc private func captureArea() {
        if #available(macOS 14.0, *) { captureOverlay(fullSelection: false) }
        else { capture(arguments: ["-i", "-s", "-x", "-r"]) }
    }
    @objc private func captureWindow() {
        if #available(macOS 14.0, *) { chooseNativeWindow() }
        else { capture(arguments: ["-i", "-w", "-o", "-x", "-r"]) }
    }
    @objc private func captureScreen() {
        if #available(macOS 14.0, *) { captureOverlay(fullSelection: true) }
        else { capture(arguments: ["-m", "-x", "-r"]) }
    }
    @objc private func captureDelayed() {
        if #available(macOS 14.0, *) { captureOverlay(fullSelection: true, delay: 3) }
        else { capture(arguments: ["-m", "-x", "-r", "-T3"]) }
    }

    @available(macOS 14.0, *)
    private func captureOverlay(fullSelection: Bool, delay: TimeInterval = 0) {
        guard !captureInProgress else { return }
        guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else {
            showError("macOS не разрешила захват экрана для JoxiLite. Включите доступ в настройках записи экрана, затем перезапустите приложение.")
            return
        }
        captureInProgress = true
        let pointer = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { $0.frame.contains(pointer) } ?? NSScreen.main
        guard let screen else {
            captureInProgress = false
            showError("Не найден экран для захвата.")
            return
        }
        let displayID = (screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)
            .map { CGDirectDisplayID($0.uint32Value) } ?? CGMainDisplayID()
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            Task { @MainActor [weak self] in
                do {
                    let data = try await NativeCapture.display(displayID,
                                                               showsCursor: AppSettings.shared.includeCursor)
                    guard let document = ScreenshotDocument(data: data) else {
                        throw OverlayCaptureFailure.decode
                    }
                    let overlay = FullscreenCaptureOverlay(document: document, screen: screen,
                                                           fullSelection: fullSelection)
                    self?.overlay = overlay
                    overlay.onClose = { [weak self] in
                        self?.overlay = nil
                        self?.captureInProgress = false
                    }
                    overlay.present()
                } catch {
                    self?.captureInProgress = false
                    self?.showError("Не удалось снять экран: \(error.localizedDescription)")
                }
            }
        }
    }

    @available(macOS 14.0, *)
    private func chooseNativeWindow() {
        guard !captureInProgress else { return }
        Task { @MainActor [weak self] in
            do {
                let windows = try await NativeCapture.availableWindows()
                guard !windows.isEmpty else {
                    self?.showError("Не найдено открытых окон для снимка.")
                    return
                }
                let picker = NSPopUpButton(frame: CGRect(x: 0, y: 0, width: 360, height: 28))
                for window in windows {
                    let app = window.owningApplication?.applicationName ?? "Приложение"
                    picker.addItem(withTitle: "\(app) — \(window.title ?? "Окно")")
                    picker.lastItem?.representedObject = window
                }
                let alert = NSAlert()
                alert.messageText = "Снять окно"
                alert.informativeText = "Выберите окно для снимка."
                alert.accessoryView = picker
                alert.addButton(withTitle: "Снять")
                alert.addButton(withTitle: "Отмена")
                guard alert.runModal() == .alertFirstButtonReturn else { return }
                guard let window = picker.selectedItem?.representedObject as? SCWindow else {
                    self?.showError("Не удалось определить выбранное окно.")
                    return
                }
                self?.captureSelectedWindow(window)
            } catch { self?.showError("Не удалось получить список окон: \(error.localizedDescription)") }
        }
    }
    @available(macOS 14.0, *)
    private func captureSelectedWindow(_ window: SCWindow) {
        captureInProgress = true
        NSApp.hide(nil)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            Task { @MainActor [weak self] in
                do {
                    let data = try await NativeCapture.window(window)
                    self?.captureInProgress = false
                    NSApp.unhideWithoutActivation()
                    if let document = ScreenshotDocument(data: data) { self?.showEditor(document) }
                } catch {
                    self?.captureInProgress = false
                    NSApp.unhideWithoutActivation()
                    self?.showError("Не удалось снять окно: \(error.localizedDescription)")
                }
            }
        }
    }

    private func capture(arguments: [String]) {
        guard !captureInProgress else { return }
        guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else {
            showError("macOS не разрешила захват экрана для JoxiLite. Включите доступ в настройках записи экрана, затем перезапустите JoxiLite.")
            return
        }
        captureInProgress = true
        NSApp.hide(nil)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            self?.launchCapture(arguments: arguments)
        }
    }
    private func launchCapture(arguments: [String]) {
        let interactive = arguments.contains("-i")
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("JoxiLite-\(UUID().uuidString).png")
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        task.arguments = arguments + [url.path]
        let errorPipe = Pipe()
        task.standardError = errorPipe
        task.terminationHandler = { [weak self] finished in
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
            let message = String(data: errorData, encoding: .utf8) ?? ""
            let data = try? Data(contentsOf: url)
            try? FileManager.default.removeItem(at: url)
            DispatchQueue.main.async {
                self?.captureInProgress = false
                NSApp.unhideWithoutActivation()
                guard let self else { return }
                if let data, let document = ScreenshotDocument(data: data) {
                    self.showEditor(document)
                } else if !interactive || !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    self.showError("Не удалось снять экран. Проверьте разрешение «Запись экрана» для JoxiLite в Системных настройках.\n\n\(message)")
                }
            }
        }
        do { try task.run() }
        catch {
            captureInProgress = false
            NSApp.unhideWithoutActivation()
            showError("Не удалось запустить захват экрана: \(error.localizedDescription)")
        }
    }
    private func showEditor(_ document: ScreenshotDocument, sourceURL: URL? = nil,
                            initialTool: DrawingTool = .arrow) {
        let editor = Editor(document: document, sourceURL: sourceURL, initialTool: initialTool)
        editors.append(editor)
        editor.onClose = { [weak self, weak editor] in
            guard let editor else { return }
            self?.editors.removeAll { $0 === editor }
        }
        NSApp.activate(ignoringOtherApps: true)
    }
    private var currentEditor: Editor? {
        editors.first { $0.window?.isKeyWindow == true } ?? editors.last
    }
    @objc private func openImage() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.png, .jpeg, .tiff, .heic]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        _ = loadImage(at: url)
    }
    @objc private func openHistory() {
        do {
            try FileManager.default.createDirectory(at: HistoryStore.shared.directoryURL,
                                                    withIntermediateDirectories: true)
            NSWorkspace.shared.open(HistoryStore.shared.directoryURL)
        } catch { showError("Не удалось открыть историю снимков: \(error.localizedDescription)") }
    }
    @discardableResult
    private func loadImage(at url: URL) -> Bool {
        do {
            let data = try Data(contentsOf: url)
            guard let document = ScreenshotDocument(data: data) else {
                showError("Не удалось открыть изображение."); return false
            }
            showEditor(document, sourceURL: url)
            return true
        } catch {
            showError("Не удалось открыть изображение: \(error.localizedDescription)")
            return false
        }
    }
    @objc private func saveCurrent() { currentEditor?.saveImage() }
    @objc private func copyCurrent() { currentEditor?.copyImage() }
    @objc private func undoCurrent() { currentEditor?.undo() }
    @objc private func redoCurrent() { currentEditor?.redo() }
    @objc private func quit() { NSApp.terminate(nil) }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard AppSettings.shared.confirmUnsaved else { return .terminateNow }
        let count = editors.filter(\.hasUnsavedChanges).count
        guard count > 0 else { return .terminateNow }
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "Закрыть JoxiLite?"
        alert.informativeText = "Несохранённые снимки (\(count)) будут потеряны."
        alert.addButton(withTitle: "Отмена")
        alert.addButton(withTitle: "Выйти без сохранения")
        return alert.runModal() == .alertSecondButtonReturn ? .terminateNow : .terminateCancel
    }
    private func showError(_ message: String) {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "JoxiLite"
        alert.informativeText = message
        alert.runModal()
    }
    func applicationWillTerminate(_ notification: Notification) {
        unregisterHotKeys()
        if let hotKeyHandler { RemoveEventHandler(hotKeyHandler) }
    }
}

private enum OverlayCaptureFailure: LocalizedError {
    case decode
    var errorDescription: String? { "Не удалось открыть захваченный кадр." }
}
