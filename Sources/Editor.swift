import AppKit
import UniformTypeIdentifiers

private final class EditorWorkspace: NSView { override var isFlipped: Bool { true } }

final class ScreenshotCanvas: NSView {
    let document: ScreenshotDocument
    var tool: DrawingTool = .arrow
    var drawingColor: NSColor = .systemRed
    var strokeWidth: CGFloat = 4
    var alternativeMode = false { didSet { needsDisplay = true } }
    var textPreview: Annotation? { didSet { needsDisplay = true } }
    var zoom: CGFloat = 1 { didSet { resizeForZoom() } }
    var requestText: ((CGPoint) -> Void)?
    var onGestureStarted: (() -> Void)?
    private var gesture: [CGPoint] = []

    init(document: ScreenshotDocument) {
        self.document = document
        super.init(frame: CGRect(origin: .zero, size: document.size))
        wantsLayer = true
        layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }

    private func resizeForZoom() {
        frame.size = CGSize(width: document.size.width * zoom, height: document.size.height * zoom)
        needsDisplay = true
    }
    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.saveGState()
        context.scaleBy(x: zoom, y: zoom)
        let preview = gesture.isEmpty ? nil : Annotation.drawing(tool: tool, points: gesture,
            color: drawingColor, lineWidth: strokeWidth, alternative: alternativeMode)
        document.render(in: context, preview: preview, showCropMask: true)
        if let textPreview { document.renderAnnotation(textPreview, in: context) }
        context.restoreGState()
    }
    private func imagePoint(_ event: NSEvent) -> CGPoint {
        let point = convert(event.locationInWindow, from: nil)
        return CGPoint(x: max(0, min(document.size.width, point.x / zoom)),
                       y: max(0, min(document.size.height, point.y / zoom)))
    }
    override func mouseDown(with event: NSEvent) {
        onGestureStarted?()
        window?.makeFirstResponder(self)
        alternativeMode = event.modifierFlags.contains(.shift)
        let point = imagePoint(event)
        if tool == .text { requestText?(point); return }
        gesture = [point, point]
        needsDisplay = true
    }
    override func mouseDragged(with event: NSEvent) {
        guard !gesture.isEmpty else { return }
        alternativeMode = event.modifierFlags.contains(.shift)
        let point = imagePoint(event)
        if tool == .pen { gesture.append(point) }
        else { gesture[gesture.count - 1] = point }
        needsDisplay = true
    }
    override func mouseUp(with event: NSEvent) {
        guard gesture.count >= 2 else { return }
        alternativeMode = event.modifierFlags.contains(.shift)
        let point = imagePoint(event)
        if tool == .pen { gesture.append(point) }
        else { gesture[gesture.count - 1] = point }
        let first = gesture[0]
        if tool == .crop {
            let rect = Annotation.drawing(tool: .crop, points: gesture, color: .white,
                                          lineWidth: 1, alternative: alternativeMode).area
            if rect.width > 3 && rect.height > 3 { document.setCrop(rect) }
        } else if tool == .pen || hypot(point.x - first.x, point.y - first.y) > 2 {
            document.add(Annotation.drawing(tool: tool, points: gesture, color: drawingColor,
                                           lineWidth: strokeWidth, alternative: alternativeMode))
        }
        gesture.removeAll(); needsDisplay = true
    }
    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53 { cancelGesture() }
        else { super.keyDown(with: event) }
    }
    func cancelGesture() { gesture.removeAll(); needsDisplay = true }
}

final class Editor: NSWindowController, NSWindowDelegate {
    let screenshot: ScreenshotDocument
    let canvas: ScreenshotCanvas
    var onClose: (() -> Void)?
    private var savedRevision = -1
    private var revision = 0
    private var savedURL: URL?
    private let sourceName: String?
    private let sourceURL: URL?
    private var toolButtons: [NSButton] = []
    private let toolbar = DraggableToolbar(frame: .zero)
    private let options = DrawingOptionsView()
    private var toolbarOrigin = CGPoint(x: 12, y: 12)
    private var textEditor: InlineTextEditor?
    private var textPoint = CGPoint.zero
    private let statusLabel = NSTextField(labelWithString: "")
    private let undoButton = NSButton()
    private let redoButton = NSButton()
    private var scrollView: NSScrollView!
    private var keyMonitor: Any?
    var hasUnsavedChanges: Bool { revision != savedRevision }

    init(document: ScreenshotDocument, sourceURL: URL? = nil, initialTool: DrawingTool = .arrow) {
        screenshot = document
        self.sourceURL = sourceURL
        sourceName = sourceURL?.lastPathComponent
        if sourceURL != nil { savedRevision = 0 }
        canvas = ScreenshotCanvas(document: document)
        canvas.tool = initialTool
        let screen = NSScreen.main?.visibleFrame.size ?? CGSize(width: 1200, height: 800)
        let width = min(max(900, screen.width * 0.82), screen.width)
        let height = min(max(600, screen.height * 0.82), screen.height)
        let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: width, height: height),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        window.title = "Новый снимок — JoxiLite"
        window.minSize = CGSize(width: min(900, screen.width), height: 500)
        window.center()
        super.init(window: window)
        window.delegate = self
        buildUI(in: window)
        screenshot.onChange = { [weak self] in
            guard let self else { return }
            self.revision += 1
            self.canvas.needsDisplay = true
            self.updateStatus()
        }
        canvas.requestText = { [weak self] point in self?.insertText(at: point) }
        canvas.onGestureStarted = { [weak self] in self?.commitText() }
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .flagsChanged]) { [weak self] event in
            guard let self, self.window?.isKeyWindow == true, NSApp.modalWindow == nil else { return event }
            if event.type == .flagsChanged {
                self.canvas.alternativeMode = event.modifierFlags.contains(.shift)
                self.options.showTool(self.canvas.tool, shift: self.canvas.alternativeMode)
                return event
            }
            if event.keyCode == 53 && !event.isARepeat {
                if AppSettings.shared.closeOnEscape { self.window?.performClose(nil) }
                else { self.canvas.cancelGesture() }
                return nil
            }
            guard event.modifierFlags.intersection([.command, .control, .option, .shift]).isEmpty,
                  !(self.window?.firstResponder is NSTextView),
                  let tool = AppSettings.shared.tool(for: Int(event.keyCode)) else { return event }
            self.commitText()
            self.canvas.tool = tool
            self.updateStatus()
            self.window?.makeFirstResponder(self.canvas)
            return nil
        }
        NotificationCenter.default.addObserver(self, selector: #selector(refreshToolShortcuts),
                                               name: AppSettings.changed, object: nil)
        window.contentView?.layoutSubtreeIfNeeded()
        fitToWindow()
        updateStatus()
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(canvas)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    deinit {
        if let keyMonitor { NSEvent.removeMonitor(keyMonitor) }
        NotificationCenter.default.removeObserver(self)
    }

    private func buildUI(in window: NSWindow) {
        let root = EditorWorkspace()
        window.contentView = root
        let tools = NSStackView()
        tools.spacing = 5
        for (index, tool) in DrawingTool.allCases.enumerated() {
            let button = NSButton(title: toolButtonTitle(tool), target: self, action: #selector(selectTool(_:)))
            button.tag = index
            button.setButtonType(.toggle)
            button.bezelStyle = .rounded
            button.state = index == 0 ? .on : .off
            button.toolTip = tool == .crop ? "Выделите часть снимка; область обрезки можно заменить или отменить" : nil
            tools.addArrangedSubview(button)
            toolButtons.append(button)
        }
        let actions = NSStackView()
        actions.spacing = 7
        undoButton.title = "↶ ⌘Z"
        undoButton.target = self; undoButton.action = #selector(undo)
        actions.addArrangedSubview(undoButton)
        redoButton.title = "↷ ⇧⌘Z"
        redoButton.target = self; redoButton.action = #selector(redo)
        actions.addArrangedSubview(redoButton)
        actions.addArrangedSubview(makeButton("−", #selector(zoomOut), tip: "Уменьшить"))
        actions.addArrangedSubview(makeButton("+", #selector(zoomIn), tip: "Увеличить"))
        actions.addArrangedSubview(makeButton("Вместить", #selector(fitToWindow), tip: "Показать снимок целиком"))
        actions.addArrangedSubview(makeButton("Копировать ⌘C", #selector(copyImage), tip: "Скопировать PNG в буфер обмена"))
        actions.addArrangedSubview(makeButton("Сохранить… ⌘S", #selector(saveImage), tip: "Сохранить PNG"))
        toolbar.content.addArrangedSubview(tools)
        toolbar.content.addArrangedSubview(options)
        toolbar.content.addArrangedSubview(actions)
        toolbar.onMoved = { [weak self] point in self?.toolbarOrigin = point }
        options.onChange = { [weak self] in self?.styleChanged() }
        options.onLayoutChanged = { [weak self] in self?.layoutToolbar() }
        scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = true
        scrollView.borderType = .bezelBorder
        scrollView.documentView = canvas
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        statusLabel.translatesAutoresizingMaskIntoConstraints = false
        statusLabel.textColor = .secondaryLabelColor
        root.addSubview(scrollView)
        root.addSubview(statusLabel)
        root.addSubview(toolbar)
        NSLayoutConstraint.activate([
            scrollView.topAnchor.constraint(equalTo: root.topAnchor, constant: 8),
            scrollView.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 8),
            scrollView.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -8),
            scrollView.bottomAnchor.constraint(equalTo: statusLabel.topAnchor, constant: -5),
            statusLabel.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 10),
            statusLabel.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -6),
            statusLabel.heightAnchor.constraint(equalToConstant: 17)
        ])
        layoutToolbar()
    }
    private func layoutToolbar() {
        guard let root = window?.contentView else { return }
        toolbar.resizeToFit(maxWidth: max(600, root.bounds.width - 24))
        toolbar.move(to: toolbarOrigin)
    }
    private func makeButton(_ title: String, _ action: Selector, tip: String) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.toolTip = tip
        return button
    }
    private func updateStatus() {
        let crop = screenshot.crop
        let dimensions = crop?.size ?? screenshot.size
        let selected = DrawingTool.allCases.firstIndex(of: canvas.tool) ?? 0
        for (index, button) in toolButtons.enumerated() {
            let tool = DrawingTool.allCases[index]
            button.state = index == selected ? .on : .off
            button.title = toolButtonTitle(tool)
            let shortcut = AppSettings.shared.toolKey(for: tool).flatMap(KeyboardKeys.name)
            let detail = tool == .crop ? "Выделите часть снимка; область обрезки можно заменить или отменить" : tool.rawValue
            button.toolTip = detail + (shortcut.map { " · \($0)" } ?? "") + " · " + tool.shiftHint
        }
        options.showTool(canvas.tool, shift: canvas.alternativeMode)
        layoutToolbar()
        undoButton.isEnabled = screenshot.canUndo
        redoButton.isEnabled = screenshot.canRedo
        statusLabel.stringValue = "\(Int(dimensions.width)) × \(Int(dimensions.height)) px  ·  \(Int(canvas.zoom * 100))%" +
            (crop != nil ? "  ·  Обрезка активна" : "")
        window?.title = (savedURL?.lastPathComponent ?? sourceName ?? "Новый снимок") +
            (revision != savedRevision ? " ●" : "") + " — JoxiLite"
    }
    private func insertText(at point: CGPoint) {
        commitText()
        textPoint = point
        let field = InlineTextEditor()
        field.frame.origin = CGPoint(x: point.x * canvas.zoom, y: point.y * canvas.zoom)
        field.onChange = { [weak self] _ in self?.updateTextPreview() }
        field.onCommit = { [weak self] in self?.commitText() }
        canvas.addSubview(field)
        textEditor = field
        updateTextPreview()
        field.focus()
    }
    private func updateTextPreview() {
        guard let field = textEditor else { return }
        field.frame.origin = CGPoint(x: textPoint.x * canvas.zoom, y: textPoint.y * canvas.zoom)
        field.update(appearance: options.textAppearance, color: options.color, scale: canvas.zoom)
        canvas.textPreview = Annotation(tool: .text, points: [textPoint], color: options.color,
                                        lineWidth: options.lineWidth, text: field.text,
                                        textAppearance: options.textAppearance)
    }
    private func commitText() {
        guard let field = textEditor else { return }
        let text = field.text.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.isEmpty {
            screenshot.add(Annotation(tool: .text, points: [textPoint], color: options.color,
                                      lineWidth: options.lineWidth, text: text,
                                      textAppearance: options.textAppearance))
        }
        field.removeFromSuperview()
        textEditor = nil
        canvas.textPreview = nil
        window?.makeFirstResponder(canvas)
    }
    private func styleChanged() {
        canvas.drawingColor = options.color
        canvas.strokeWidth = options.lineWidth
        updateTextPreview()
    }
    @objc private func selectTool(_ button: NSButton) {
        commitText()
        canvas.tool = DrawingTool.allCases[button.tag]
        updateStatus()
    }
    @objc private func refreshToolShortcuts() { updateStatus() }
    @objc func undo() { screenshot.undo() }
    @objc func redo() { screenshot.redo() }
    @objc private func zoomIn() { setZoom(canvas.zoom * 1.25) }
    @objc private func zoomOut() { setZoom(canvas.zoom / 1.25) }
    private func setZoom(_ value: CGFloat) {
        canvas.zoom = max(0.1, min(4, value))
        updateTextPreview()
        updateStatus()
    }
    @objc func fitToWindow() {
        guard let scrollView else { return }
        let visible = scrollView.contentView.bounds.size
        guard visible.width > 0, visible.height > 0 else { return }
        setZoom(min(1, (visible.width - 4) / screenshot.size.width,
                       (visible.height - 4) / screenshot.size.height))
    }
    @objc func copyImage() {
        commitText()
        guard let data = screenshot.pngData() else { showError("Не удалось подготовить PNG."); return }
        NSPasteboard.general.clearContents()
        guard NSPasteboard.general.setData(data, forType: .png) else {
            showError("Не удалось скопировать снимок."); return
        }
        statusLabel.stringValue = "Снимок скопирован в буфер обмена"
    }
    @objc func saveImage() {
        commitText()
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.png]
        panel.canCreateDirectories = true
        panel.nameFieldStringValue = savedURL?.lastPathComponent ?? sourceName.map {
            URL(fileURLWithPath: $0).deletingPathExtension().lastPathComponent + ".png"
        } ?? "Снимок \(DateFormatter.filename.string(from: Date())).png"
        if let directory = (savedURL ?? sourceURL)?.deletingLastPathComponent() {
            panel.directoryURL = directory
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        guard let data = screenshot.pngData() else { showError("Не удалось подготовить PNG."); return }
        do {
            try data.write(to: url, options: .atomic)
            savedURL = url
            savedRevision = revision
            updateStatus()
        } catch { showError("Не удалось сохранить снимок: \(error.localizedDescription)") }
    }
    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = message
        alert.runModal()
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        commitText()
        guard AppSettings.shared.confirmUnsaved else { return true }
        guard hasUnsavedChanges else { return true }
        let alert = NSAlert()
        alert.messageText = "Сохранить снимок перед закрытием?"
        alert.informativeText = "Несохранённый снимок и пометки будут потеряны."
        alert.addButton(withTitle: "Сохранить…")
        alert.addButton(withTitle: "Не сохранять")
        alert.addButton(withTitle: "Отмена")
        switch alert.runModal() {
        case .alertFirstButtonReturn: saveImage(); return revision == savedRevision
        case .alertSecondButtonReturn: return true
        default: return false
        }
    }
    func windowDidResize(_ notification: Notification) { layoutToolbar() }
    func windowWillClose(_ notification: Notification) { options.dismissPalette(); onClose?() }
}

private extension DateFormatter {
    static let filename: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH.mm.ss"
        return formatter
    }()
}
