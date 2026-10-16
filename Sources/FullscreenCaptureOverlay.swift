import AppKit
import Carbon

private final class CaptureOverlayWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

private struct ResizeEdges: OptionSet {
    let rawValue: Int
    static let left = ResizeEdges(rawValue: 1)
    static let right = ResizeEdges(rawValue: 2)
    static let top = ResizeEdges(rawValue: 4)
    static let bottom = ResizeEdges(rawValue: 8)
}

private final class CaptureOverlayView: NSView {
    enum DragMode { case none, select, move, resize(ResizeEdges), draw }

    let document: ScreenshotDocument
    var tool: DrawingTool?
    var drawingColor: NSColor = .systemRed
    var strokeWidth: CGFloat = 4
    var alternativeMode = false { didSet { needsDisplay = true } }
    var textPreview: Annotation? { didSet { needsDisplay = true } }
    var onSelectionChanged: (() -> Void)?
    var onTextRequested: ((CGPoint) -> Void)?
    var onGestureStarted: (() -> Void)?
    private var dragMode: DragMode = .none
    private var dragStart: CGPoint = .zero
    private var originalSelection: CGRect = .zero
    private var selectionPreview: CGRect?
    private var gesture: [CGPoint] = []

    init(document: ScreenshotDocument) {
        self.document = document
        super.init(frame: .zero)
        wantsLayer = true
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }

    var selectedRect: CGRect? { selectionPreview ?? document.crop }

    private var pixelScaleX: CGFloat { document.size.width / max(1, bounds.width) }
    private var pixelScaleY: CGFloat { document.size.height / max(1, bounds.height) }
    var textScale: CGFloat { min(1 / pixelScaleX, 1 / pixelScaleY) }
    func viewRect(_ pixelRect: CGRect) -> CGRect {
        CGRect(x: pixelRect.minX / pixelScaleX, y: pixelRect.minY / pixelScaleY,
               width: pixelRect.width / pixelScaleX, height: pixelRect.height / pixelScaleY)
    }
    func viewPoint(_ pixelPoint: CGPoint) -> CGPoint {
        CGPoint(x: pixelPoint.x / pixelScaleX, y: pixelPoint.y / pixelScaleY)
    }
    private func pixelPoint(_ event: NSEvent) -> CGPoint {
        let point = convert(event.locationInWindow, from: nil)
        return CGPoint(x: max(0, min(document.size.width, point.x * pixelScaleX)),
                       y: max(0, min(document.size.height, point.y * pixelScaleY)))
    }
    private func constrained(_ rect: CGRect) -> CGRect {
        rect.standardized.intersection(CGRect(origin: .zero, size: document.size)).integral
    }

    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.saveGState()
        context.scaleBy(x: 1 / pixelScaleX, y: 1 / pixelScaleY)
        document.renderBase(in: context)
        context.restoreGState()
        context.setFillColor(NSColor.black.withAlphaComponent(0.38).cgColor)
        context.fill(bounds)

        guard let selected = selectedRect, selected.width > 2, selected.height > 2 else { return }
        let displayRect = viewRect(selected)
        context.saveGState()
        context.clip(to: displayRect)
        context.scaleBy(x: 1 / pixelScaleX, y: 1 / pixelScaleY)
        document.renderBase(in: context)
        let preview = gesture.isEmpty || tool == nil ? nil : Annotation.drawing(
            tool: tool!, points: gesture, color: drawingColor, lineWidth: strokeWidth,
            alternative: alternativeMode)
        document.renderAnnotations(in: context, preview: preview)
        if let textPreview { document.renderAnnotation(textPreview, in: context) }
        context.restoreGState()

        context.setStrokeColor(NSColor.white.cgColor)
        context.setLineWidth(1.5)
        context.stroke(displayRect)
        let handle: CGFloat = 8
        for point in handlePoints(for: displayRect) {
            let square = CGRect(x: point.x - handle / 2, y: point.y - handle / 2,
                                width: handle, height: handle)
            context.setFillColor(NSColor.white.cgColor)
            context.fill(square)
            context.setStrokeColor(NSColor.black.withAlphaComponent(0.65).cgColor)
            context.stroke(square)
        }
        let sizeText = "\(Int(selected.width)) × \(Int(selected.height))"
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .semibold),
            .foregroundColor: NSColor.white
        ]
        let textSize = (sizeText as NSString).size(withAttributes: attributes)
        let label = CGRect(x: max(8, min(bounds.width - textSize.width - 18, displayRect.minX)),
                           y: displayRect.minY > 30 ? displayRect.minY - 27 : displayRect.maxY + 7,
                           width: textSize.width + 14, height: 22)
        context.setFillColor(NSColor.black.withAlphaComponent(0.8).cgColor)
        context.fill(label)
        (sizeText as NSString).draw(at: CGPoint(x: label.minX + 7, y: label.minY + 3),
                                   withAttributes: attributes)
    }

    private func handlePoints(for rect: CGRect) -> [CGPoint] {
        let midX = rect.midX, midY = rect.midY
        return [CGPoint(x: rect.minX, y: rect.minY), CGPoint(x: midX, y: rect.minY),
                CGPoint(x: rect.maxX, y: rect.minY), CGPoint(x: rect.minX, y: midY),
                CGPoint(x: rect.maxX, y: midY), CGPoint(x: rect.minX, y: rect.maxY),
                CGPoint(x: midX, y: rect.maxY), CGPoint(x: rect.maxX, y: rect.maxY)]
    }

    private func edges(at point: CGPoint, in rect: CGRect) -> ResizeEdges {
        let thresholdX = 9 * pixelScaleX
        let thresholdY = 9 * pixelScaleY
        guard rect.insetBy(dx: -thresholdX, dy: -thresholdY).contains(point) else { return [] }
        var result: ResizeEdges = []
        if abs(point.x - rect.minX) <= thresholdX { result.insert(.left) }
        if abs(point.x - rect.maxX) <= thresholdX { result.insert(.right) }
        if abs(point.y - rect.minY) <= thresholdY { result.insert(.top) }
        if abs(point.y - rect.maxY) <= thresholdY { result.insert(.bottom) }
        return result
    }

    override func mouseDown(with event: NSEvent) {
        onGestureStarted?()
        window?.makeFirstResponder(self)
        alternativeMode = event.modifierFlags.contains(.shift)
        let point = pixelPoint(event)
        dragStart = point
        if let selected = document.crop {
            let resize = edges(at: point, in: selected)
            if !resize.isEmpty {
                originalSelection = selected
                dragMode = .resize(resize)
                return
            }
            if selected.contains(point) {
                if tool == nil {
                    originalSelection = selected
                    dragMode = .move
                } else if tool == .text {
                    onTextRequested?(point)
                } else {
                    gesture = [point, point]
                    dragMode = .draw
                }
                return
            }
        }
        dragMode = .select
        selectionPreview = CGRect(origin: point, size: .zero)
        onSelectionChanged?()
        needsDisplay = true
    }

    override func mouseDragged(with event: NSEvent) {
        alternativeMode = event.modifierFlags.contains(.shift)
        let point = pixelPoint(event)
        switch dragMode {
        case .none: return
        case .select:
            selectionPreview = constrained(Annotation.drawing(tool: .crop, points: [dragStart, point],
                color: .white, lineWidth: 1, alternative: alternativeMode).area)
        case .move:
            var dx = max(-originalSelection.minX,
                         min(document.size.width - originalSelection.maxX, point.x - dragStart.x))
            var dy = max(-originalSelection.minY,
                         min(document.size.height - originalSelection.maxY, point.y - dragStart.y))
            if alternativeMode {
                if abs(dx) >= abs(dy) { dy = 0 } else { dx = 0 }
            }
            selectionPreview = originalSelection.offsetBy(dx: dx, dy: dy).integral
        case .resize(let edges):
            var minX = originalSelection.minX, maxX = originalSelection.maxX
            var minY = originalSelection.minY, maxY = originalSelection.maxY
            let minimum = max(8, 4 * max(pixelScaleX, pixelScaleY))
            if edges.contains(.left) { minX = max(0, min(point.x, maxX - minimum)) }
            if edges.contains(.right) { maxX = min(document.size.width, max(point.x, minX + minimum)) }
            if edges.contains(.top) { minY = max(0, min(point.y, maxY - minimum)) }
            if edges.contains(.bottom) { maxY = min(document.size.height, max(point.y, minY + minimum)) }
            selectionPreview = CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY).integral
        case .draw:
            guard let selected = document.crop else { break }
            let clamped = CGPoint(x: max(selected.minX, min(selected.maxX, point.x)),
                                  y: max(selected.minY, min(selected.maxY, point.y)))
            if tool == .pen { gesture.append(clamped) }
            else if !gesture.isEmpty { gesture[gesture.count - 1] = clamped }
        }
        onSelectionChanged?()
        needsDisplay = true
    }

    override func mouseUp(with event: NSEvent) {
        alternativeMode = event.modifierFlags.contains(.shift)
        switch dragMode {
        case .select, .move, .resize:
            if let candidate = selectionPreview, candidate.width > 8, candidate.height > 8 {
                document.setCrop(candidate)
            }
            selectionPreview = nil
        case .draw:
            if !gesture.isEmpty, let tool {
                let point = pixelPoint(event)
                if let selected = document.crop {
                    let clamped = CGPoint(x: max(selected.minX, min(selected.maxX, point.x)),
                                          y: max(selected.minY, min(selected.maxY, point.y)))
                    if tool == .pen { gesture.append(clamped) }
                    else { gesture[gesture.count - 1] = clamped }
                    if tool == .pen || hypot(clamped.x - gesture[0].x,
                                             clamped.y - gesture[0].y) > 2 {
                        document.add(Annotation.drawing(tool: tool, points: gesture, color: drawingColor,
                                                       lineWidth: strokeWidth, alternative: alternativeMode))
                    }
                }
            }
            gesture.removeAll()
        case .none: break
        }
        dragMode = .none
        onSelectionChanged?()
        needsDisplay = true
    }
}

final class FullscreenCaptureOverlay: NSObject, NSWindowDelegate {
    let document: ScreenshotDocument
    let window: NSWindow
    private let history: HistoryStore
    private let surface: CaptureOverlayView
    private let toolbar = DraggableToolbar(frame: .zero)
    private let tools = NSStackView()
    private let options = DrawingOptionsView()
    private var moveButton: NSButton!
    private var toolButtons: [NSButton] = []
    private var undoButton: NSButton!
    private var redoButton: NSButton!
    private var keyMonitor: Any?
    private var textField: InlineTextEditor?
    private var textPoint: CGPoint = .zero
    private var toolbarOrigin: CGPoint?
    var onClose: (() -> Void)?

    init(document: ScreenshotDocument, screen: NSScreen, fullSelection: Bool = false,
         history: HistoryStore = .shared) {
        self.document = document
        self.history = history
        surface = CaptureOverlayView(document: document)
        window = CaptureOverlayWindow(contentRect: screen.frame, styleMask: .borderless,
                                      backing: .buffered, defer: false, screen: screen)
        super.init()
        window.delegate = self
        window.level = .screenSaver
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        window.isReleasedWhenClosed = false
        window.hasShadow = false
        window.backgroundColor = .black
        window.contentView = surface
        surface.frame = CGRect(origin: .zero, size: screen.frame.size)
        surface.onSelectionChanged = { [weak self] in self?.updateToolbar() }
        surface.onTextRequested = { [weak self] point in self?.beginText(at: point) }
        surface.onGestureStarted = { [weak self] in self?.commitText() }
        buildToolbar()
        if fullSelection { document.setCrop(CGRect(origin: .zero, size: document.size)) }
        updateToolbar()
        NotificationCenter.default.addObserver(self, selector: #selector(refreshToolShortcuts),
                                               name: AppSettings.changed, object: nil)
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .flagsChanged]) { [weak self] event in
            guard let self, self.window.isKeyWindow else { return event }
            if event.type == .flagsChanged {
                self.surface.alternativeMode = event.modifierFlags.contains(.shift)
                self.options.showTool(self.surface.tool, shift: self.surface.alternativeMode)
                return event
            }
            if event.keyCode == 53 { self.cancel(); return nil }
            let flags = event.modifierFlags.intersection([.command, .control, .option, .shift])
            if event.keyCode == kVK_ANSI_C && (flags == [.control] || flags == [.command]) {
                self.finish()
                return nil
            }
            if event.keyCode == kVK_ANSI_Z && flags == [.command] {
                self.document.undo(); self.updateToolbar(); self.surface.needsDisplay = true
                return nil
            }
            if event.keyCode == kVK_ANSI_Z && flags == [.command, .shift] {
                self.document.redo(); self.updateToolbar(); self.surface.needsDisplay = true
                return nil
            }
            if flags.isEmpty, !(self.window.firstResponder is NSTextView),
               let tool = AppSettings.shared.tool(for: Int(event.keyCode)) {
                self.commitText()
                self.surface.tool = tool == .crop ? nil : tool
                self.refreshToolButtons()
                return nil
            }
            return event
        }
    }

    func present() {
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0
            window.makeKeyAndOrderFront(nil)
        }
        NSApp.activate(ignoringOtherApps: true)
        window.makeFirstResponder(surface)
        NSCursor.crosshair.set()
    }

    private func buildToolbar() {
        tools.orientation = .horizontal
        tools.alignment = .centerY
        tools.spacing = 4
        moveButton = makeButton("Двигать", #selector(selectMove))
        moveButton.setButtonType(.toggle)
        for tool in DrawingTool.allCases where tool != .crop {
            let button = makeButton(toolButtonTitle(tool), #selector(selectTool(_:)))
            button.tag = DrawingTool.allCases.firstIndex(of: tool) ?? 0
            button.setButtonType(.toggle)
            tools.addArrangedSubview(button)
            toolButtons.append(button)
        }
        tools.addArrangedSubview(moveButton)
        let actions = NSStackView()
        actions.spacing = 6
        undoButton = makeButton("↶  ⌘Z", #selector(undo))
        redoButton = makeButton("↷  ⇧⌘Z", #selector(redo))
        actions.addArrangedSubview(undoButton)
        actions.addArrangedSubview(redoButton)
        actions.addArrangedSubview(makeButton("Готово  Ctrl+C", #selector(finish)))
        actions.addArrangedSubview(makeButton("Отмена  Esc", #selector(cancel)))
        toolbar.content.addArrangedSubview(tools)
        toolbar.content.addArrangedSubview(options)
        toolbar.content.addArrangedSubview(actions)
        surface.addSubview(toolbar)
        toolbar.onMoved = { [weak self] origin in self?.toolbarOrigin = origin }
        options.onChange = { [weak self] in self?.styleChanged() }
        options.onLayoutChanged = { [weak self] in self?.updateToolbar() }
        refreshToolButtons()
    }
    private func makeButton(_ title: String, _ action: Selector) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.bezelStyle = .rounded
        return button
    }
    private func updateToolbar() {
        guard let selected = surface.selectedRect, selected.width > 8, selected.height > 8 else {
            toolbar.isHidden = true
            return
        }
        toolbar.isHidden = false
        let selectedView = surface.viewRect(selected)
        toolbar.resizeToFit(maxWidth: surface.bounds.width - 16)
        let width = toolbar.bounds.width, height = toolbar.bounds.height
        let x = max(8, min(surface.bounds.width - width - 8, selectedView.minX))
        let y = selectedView.maxY + height + 12 < surface.bounds.height
            ? selectedView.maxY + 8 : max(8, selectedView.minY - height - 8)
        let origin = toolbarOrigin ?? CGPoint(x: x, y: y)
        toolbar.frame.origin = CGPoint(x: max(8, min(surface.bounds.width - width - 8, origin.x)),
                                       y: max(8, min(surface.bounds.height - height - 8, origin.y)))
        undoButton.isEnabled = document.canUndo
        redoButton.isEnabled = document.canRedo
    }
    private func refreshToolButtons() {
        let moveKey = AppSettings.shared.toolKey(for: .crop).flatMap(KeyboardKeys.name)
        moveButton.title = "Двигать" + (moveKey.map { "  \($0)" } ?? "")
        moveButton.state = surface.tool == nil ? .on : .off
        for button in toolButtons {
            let tool = DrawingTool.allCases[button.tag]
            button.state = tool == surface.tool ? .on : .off
            button.title = toolButtonTitle(tool)
            button.toolTip = tool.shiftHint
        }
        options.showTool(surface.tool, shift: surface.alternativeMode)
        updateToolbar()
    }
    @objc private func refreshToolShortcuts() { refreshToolButtons() }
    @objc private func selectMove() { commitText(); surface.tool = nil; refreshToolButtons(); window.makeFirstResponder(surface) }
    @objc private func selectTool(_ sender: NSButton) {
        commitText()
        surface.tool = DrawingTool.allCases[sender.tag]
        refreshToolButtons()
        window.makeFirstResponder(surface)
    }
    private func styleChanged() {
        surface.drawingColor = options.color
        surface.strokeWidth = options.lineWidth
        updateTextPreview()
    }
    @objc private func undo() { document.undo(); updateToolbar(); surface.needsDisplay = true }
    @objc private func redo() { document.redo(); updateToolbar(); surface.needsDisplay = true }

    private func beginText(at point: CGPoint) {
        commitText()
        textPoint = point
        let viewPoint = surface.viewPoint(point)
        let field = InlineTextEditor()
        field.frame.origin = viewPoint
        field.onChange = { [weak self] _ in self?.updateTextPreview() }
        field.onCommit = { [weak self] in self?.commitText() }
        surface.addSubview(field)
        textField = field
        updateTextPreview()
        field.focus()
    }
    private func updateTextPreview() {
        guard let field = textField else { return }
        field.update(appearance: options.textAppearance, color: options.color, scale: surface.textScale)
        surface.textPreview = Annotation(tool: .text, points: [textPoint], color: options.color,
                                         lineWidth: options.lineWidth, text: field.text,
                                         textAppearance: options.textAppearance)
    }
    private func commitText() {
        guard let field = textField else { return }
        let text = field.text.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.isEmpty {
            document.add(Annotation(tool: .text, points: [textPoint], color: options.color,
                                    lineWidth: options.lineWidth, text: text, textAppearance: options.textAppearance))
        }
        field.removeFromSuperview()
        textField = nil
        surface.textPreview = nil
        window.makeFirstResponder(surface)
        surface.needsDisplay = true
        updateToolbar()
    }

    @objc private func finish() {
        if textField != nil { commitText() }
        guard document.crop != nil, let data = document.pngData() else { NSSound.beep(); return }
        NSPasteboard.general.clearContents()
        guard NSPasteboard.general.setData(data, forType: .png) else { NSSound.beep(); return }
        do { try history.save(data, limitMB: AppSettings.shared.historyLimitMB) }
        catch { NSLog("JoxiLite: не удалось сохранить снимок в историю: %@", error.localizedDescription) }
        close()
    }
    @objc private func cancel() { close() }
    private func close() {
        options.dismissPalette()
        if let keyMonitor { NSEvent.removeMonitor(keyMonitor); self.keyMonitor = nil }
        NSCursor.arrow.set()
        window.orderOut(nil)
        window.close()
        onClose?()
    }
    deinit {
        if let keyMonitor { NSEvent.removeMonitor(keyMonitor) }
        NotificationCenter.default.removeObserver(self)
    }
}
