import AppKit

private final class ShortcutRecorder: NSButton {
    private static weak var active: ShortcutRecorder?
    private var monitor: Any?
    private var displayTitle = ""
    var onRecorded: ((NSEvent?) -> Void)?
    var onRecordingChanged: ((Bool) -> Void)?

    init(title: String) {
        super.init(frame: .zero)
        displayTitle = title
        self.title = title
        bezelStyle = .rounded
        target = self
        action = #selector(beginRecording)
        setContentHuggingPriority(.required, for: .horizontal)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func setShortcutTitle(_ title: String) {
        displayTitle = title
        if monitor == nil { self.title = title }
    }

    @objc private func beginRecording() {
        Self.active?.stopRecording()
        Self.active = self
        title = "Нажмите клавиши…"
        onRecordingChanged?(true)
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self else { return event }
            if event.keyCode == 53 {
                self.stopRecording()
            } else {
                self.stopRecording()
                self.onRecorded?(event.keyCode == 51 || event.keyCode == 117 ? nil : event)
            }
            return nil
        }
    }

    func stopRecording() {
        guard let monitor else { return }
        NSEvent.removeMonitor(monitor)
        self.monitor = nil
        title = displayTitle
        if Self.active === self { Self.active = nil }
        onRecordingChanged?(false)
    }
    deinit { if let monitor { NSEvent.removeMonitor(monitor) } }
}

final class SettingsWindow: NSWindowController, NSWindowDelegate, NSTextFieldDelegate {
    var onSettingsChanged: (() -> String?)?
    var onRecordingChanged: ((Bool) -> Void)?
    private let settings = AppSettings.shared
    private var recorders: [ShortcutRecorder] = []
    private let escapeCheck = NSButton(checkboxWithTitle: "Закрывать редактор клавишей Esc", target: nil, action: nil)
    private let confirmCheck = NSButton(checkboxWithTitle: "Спрашивать перед закрытием несохранённых снимков", target: nil, action: nil)
    private let cursorCheck = NSButton(checkboxWithTitle: "Включать курсор в исходный снимок", target: nil, action: nil)
    private let historyLimitField = NSTextField()
    private let message = NSTextField(labelWithString: "")

    init() {
        let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: 620, height: 710),
                              styleMask: [.titled, .closable, .miniaturizable],
                              backing: .buffered, defer: false)
        window.title = "Настройки — JoxiLite"
        window.center()
        super.init(window: window)
        window.delegate = self
        buildUI(in: window)
        refresh()
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func present() {
        refresh()
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func buildUI(in window: NSWindow) {
        let root = NSView()
        window.contentView = root
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 8
        stack.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -24),
            stack.topAnchor.constraint(equalTo: root.topAnchor, constant: 20)
        ])

        stack.addArrangedSubview(heading("Глобальные сочетания"))
        stack.addArrangedSubview(hint("Для снимка используйте букву или цифру с ⌘, ⌃ или ⌥."))
        for action in CaptureAction.allCases {
            let recorder = makeRecorder()
            recorder.onRecorded = { [weak self, weak recorder] event in
                guard let self else { return }
                let shortcut = event.flatMap(KeyCombination.from)
                if event != nil && shortcut == nil {
                    self.message.stringValue = "Нужна буква или цифра."
                    return
                }
                if let error = self.settings.setHotKey(shortcut, for: action) {
                    self.message.stringValue = error
                } else {
                    self.message.stringValue = self.onSettingsChanged?() ?? "Настройки сохранены"
                }
                recorder?.setShortcutTitle(self.settings.hotKey(for: action)?.title ?? "Не назначено")
            }
            stack.addArrangedSubview(row(action.title, recorder: recorder))
        }

        let spacer = NSView(frame: CGRect(x: 0, y: 0, width: 1, height: 8))
        stack.addArrangedSubview(spacer)
        stack.addArrangedSubview(heading("Инструменты редактора"))
        stack.addArrangedSubview(hint("Назначьте букву или цифру без модификаторов. Delete удаляет сочетание."))
        for tool in DrawingTool.allCases {
            let recorder = makeRecorder()
            recorder.onRecorded = { [weak self, weak recorder] event in
                guard let self else { return }
                let flags = event?.modifierFlags.intersection([.command, .control, .option, .shift])
                if event != nil && flags != [] {
                    self.message.stringValue = "Для инструментов используйте клавишу без модификаторов."
                    return
                }
                self.message.stringValue = self.settings.setToolKey(event.map { Int($0.keyCode) }, for: tool)
                    ?? "Настройки сохранены"
                recorder?.setShortcutTitle(self.settings.toolKey(for: tool).flatMap(KeyboardKeys.name) ?? "Не назначено")
            }
            stack.addArrangedSubview(row(tool.rawValue, recorder: recorder))
        }

        stack.addArrangedSubview(spacerView(height: 5))
        escapeCheck.target = self; escapeCheck.action = #selector(toggleEscape)
        confirmCheck.target = self; confirmCheck.action = #selector(toggleConfirmation)
        cursorCheck.target = self; cursorCheck.action = #selector(toggleCursor)
        stack.addArrangedSubview(escapeCheck)
        stack.addArrangedSubview(confirmCheck)
        stack.addArrangedSubview(cursorCheck)
        let historyRow = NSStackView()
        historyRow.orientation = .horizontal
        historyRow.spacing = 8
        historyRow.addArrangedSubview(NSTextField(labelWithString: "Лимит папки истории:"))
        historyLimitField.widthAnchor.constraint(equalToConstant: 70).isActive = true
        historyLimitField.alignment = .right
        historyLimitField.target = self
        historyLimitField.action = #selector(updateHistoryLimit)
        historyLimitField.delegate = self
        historyRow.addArrangedSubview(historyLimitField)
        historyRow.addArrangedSubview(NSTextField(labelWithString: "МБ"))
        stack.addArrangedSubview(historyRow)
        let bottom = NSStackView()
        bottom.orientation = .horizontal
        bottom.spacing = 12
        let restore = NSButton(title: "По умолчанию", target: self, action: #selector(restoreDefaults))
        bottom.addArrangedSubview(restore)
        message.textColor = .secondaryLabelColor
        message.lineBreakMode = .byTruncatingTail
        message.widthAnchor.constraint(equalToConstant: 435).isActive = true
        bottom.addArrangedSubview(message)
        stack.addArrangedSubview(bottom)
    }

    private func makeRecorder() -> ShortcutRecorder {
        let recorder = ShortcutRecorder(title: "Не назначено")
        recorder.widthAnchor.constraint(equalToConstant: 170).isActive = true
        recorder.onRecordingChanged = { [weak self] recording in
            self?.onRecordingChanged?(recording)
        }
        recorders.append(recorder)
        return recorder
    }

    private func row(_ title: String, recorder: ShortcutRecorder) -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        let label = NSTextField(labelWithString: title)
        label.widthAnchor.constraint(equalToConstant: 385).isActive = true
        row.addArrangedSubview(label)
        row.addArrangedSubview(recorder)
        return row
    }

    private func heading(_ title: String) -> NSTextField {
        let label = NSTextField(labelWithString: title)
        label.font = .boldSystemFont(ofSize: 14)
        return label
    }
    private func hint(_ title: String) -> NSTextField {
        let label = NSTextField(labelWithString: title)
        label.textColor = .secondaryLabelColor
        label.font = .systemFont(ofSize: 11)
        return label
    }
    private func spacerView(height: CGFloat) -> NSView {
        NSView(frame: CGRect(x: 0, y: 0, width: 1, height: height))
    }

    private func refresh() {
        var index = 0
        for action in CaptureAction.allCases {
            recorders[index].setShortcutTitle(settings.hotKey(for: action)?.title ?? "Не назначено")
            index += 1
        }
        for tool in DrawingTool.allCases {
            recorders[index].setShortcutTitle(settings.toolKey(for: tool).flatMap(KeyboardKeys.name) ?? "Не назначено")
            index += 1
        }
        escapeCheck.state = settings.closeOnEscape ? .on : .off
        confirmCheck.state = settings.confirmUnsaved ? .on : .off
        cursorCheck.state = settings.includeCursor ? .on : .off
        historyLimitField.stringValue = String(settings.historyLimitMB)
    }

    @objc private func toggleEscape() {
        settings.closeOnEscape = escapeCheck.state == .on
        message.stringValue = "Настройки сохранены"
    }
    @objc private func toggleConfirmation() {
        settings.confirmUnsaved = confirmCheck.state == .on
        message.stringValue = "Настройки сохранены"
    }
    @objc private func toggleCursor() {
        settings.includeCursor = cursorCheck.state == .on
        message.stringValue = "Настройки сохранены"
    }
    @objc private func updateHistoryLimit() {
        guard let value = Int(historyLimitField.stringValue), (10...10_000).contains(value) else {
            historyLimitField.stringValue = String(settings.historyLimitMB)
            message.stringValue = "Укажите число от 10 до 10 000 МБ."
            return
        }
        settings.historyLimitMB = value
        do {
            try HistoryStore.shared.prune(limitMB: value)
            message.stringValue = "Настройки сохранены"
        } catch { message.stringValue = "Не удалось очистить историю: \(error.localizedDescription)" }
    }
    func controlTextDidEndEditing(_ obj: Notification) { updateHistoryLimit() }
    @objc private func restoreDefaults() {
        recorders.forEach { $0.stopRecording() }
        settings.restoreDefaults()
        refresh()
        message.stringValue = onSettingsChanged?() ?? "Настройки по умолчанию восстановлены"
    }
    func windowWillClose(_ notification: Notification) { recorders.forEach { $0.stopRecording() } }
}
