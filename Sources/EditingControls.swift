import AppKit

final class PaletteColorWell: NSColorWell {
    override func activate(_ exclusive: Bool) {
        super.activate(true)
        let panel = NSColorPanel.shared
        panel.showsAlpha = true
        panel.level = NSWindow.Level(rawValue: max(NSWindow.Level.floating.rawValue,
                                                  (window?.level.rawValue ?? 0) + 1))
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.makeKeyAndOrderFront(nil)
    }
    override func mouseDown(with event: NSEvent) {
        if isActive { deactivate(); NSColorPanel.shared.orderOut(nil) }
        else { activate(true) }
    }
}

private final class ToolbarGrip: NSView {
    weak var panel: DraggableToolbar?
    private var startPoint = CGPoint.zero
    private var startOrigin = CGPoint.zero
    override var isFlipped: Bool { true }
    override func resetCursorRects() { addCursorRect(bounds, cursor: .openHand) }
    override func draw(_ dirtyRect: NSRect) {
        NSColor(calibratedRed: 0.32, green: 0.58, blue: 1, alpha: 0.65).setFill()
        NSBezierPath(roundedRect: bounds.insetBy(dx: 3, dy: 5), xRadius: 5, yRadius: 5).fill()
        NSColor.white.withAlphaComponent(0.85).setFill()
        for x in [bounds.midX - 3, bounds.midX + 3] {
            for y in [bounds.midY - 8, bounds.midY, bounds.midY + 8] {
                NSBezierPath(ovalIn: CGRect(x: x - 1.3, y: y - 1.3, width: 2.6, height: 2.6)).fill()
            }
        }
    }
    override func mouseDown(with event: NSEvent) {
        guard let panel, let host = panel.superview else { return }
        startPoint = host.convert(event.locationInWindow, from: nil)
        startOrigin = panel.frame.origin
        NSCursor.closedHand.set()
    }
    override func mouseDragged(with event: NSEvent) {
        guard let panel, let host = panel.superview else { return }
        let point = host.convert(event.locationInWindow, from: nil)
        panel.move(to: CGPoint(x: startOrigin.x + point.x - startPoint.x,
                               y: startOrigin.y + point.y - startPoint.y))
    }
    override func mouseUp(with event: NSEvent) { NSCursor.openHand.set() }
}

final class DraggableToolbar: NSView {
    let content = NSStackView()
    private let grip = ToolbarGrip()
    var onMoved: ((CGPoint) -> Void)?
    override var isFlipped: Bool { true }

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        appearance = NSAppearance(named: .darkAqua)
        layer?.backgroundColor = NSColor(calibratedRed: 0.10, green: 0.20, blue: 0.43, alpha: 0.98).cgColor
        layer?.borderColor = NSColor(calibratedRed: 0.35, green: 0.62, blue: 1, alpha: 1).cgColor
        layer?.borderWidth = 1
        layer?.cornerRadius = 10
        layer?.shadowColor = NSColor.black.cgColor
        layer?.shadowOpacity = 0.35
        layer?.shadowRadius = 8
        content.orientation = .vertical
        content.alignment = .leading
        content.spacing = 6
        grip.panel = self
        grip.toolTip = "Перетащите панель инструментов"
        grip.setAccessibilityLabel("Переместить панель инструментов")
        addSubview(grip)
        addSubview(content)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func resizeToFit(maxWidth: CGFloat) {
        let desired = content.fittingSize
        frame.size = CGSize(width: min(maxWidth, desired.width + 42), height: desired.height + 18)
        grip.frame = CGRect(x: 3, y: 3, width: 25, height: bounds.height - 6)
        content.frame = CGRect(x: 32, y: 9, width: bounds.width - 42, height: bounds.height - 18)
        content.layoutSubtreeIfNeeded()
    }
    func move(to origin: CGPoint) {
        guard let host = superview else { return }
        frame.origin = CGPoint(x: max(8, min(host.bounds.width - bounds.width - 8, origin.x)),
                               y: max(8, min(host.bounds.height - bounds.height - 8, origin.y)))
        onMoved?(frame.origin)
    }
}

func toolButtonTitle(_ tool: DrawingTool) -> String {
    let key = AppSettings.shared.toolKey(for: tool).flatMap(KeyboardKeys.name)
    return tool.rawValue + (key.map { "  \($0)" } ?? "")
}

final class DrawingOptionsView: NSStackView {
    var color: NSColor { colorWell.color }
    var lineWidth: CGFloat { CGFloat(widthSlider.doubleValue.rounded()) }
    var textAppearance: TextAppearance {
        TextAppearance(fontSize: CGFloat(fontSlider.doubleValue.rounded()),
                       opacity: CGFloat(textOpacitySlider.doubleValue / 100),
                       showsBackground: backgroundCheck.state == .on,
                       backgroundColor: backgroundWell.color,
                       backgroundOpacity: CGFloat(backgroundOpacitySlider.doubleValue / 100))
    }
    var onChange: (() -> Void)?
    var onLayoutChanged: (() -> Void)?
    private let colorWell = PaletteColorWell(frame: CGRect(x: 0, y: 0, width: 40, height: 26))
    private let widthSlider = NSSlider(value: 4, minValue: 1, maxValue: 30, target: nil, action: nil)
    private let widthValue = NSTextField(labelWithString: "4 px")
    private let hint = NSTextField(labelWithString: "")
    private let textRow = NSStackView()
    private let fontSlider = NSSlider(value: 28, minValue: 10, maxValue: 96, target: nil, action: nil)
    private let fontValue = NSTextField(labelWithString: "28 px")
    private let textOpacitySlider = NSSlider(value: 100, minValue: 0, maxValue: 100, target: nil, action: nil)
    private let textOpacityValue = NSTextField(labelWithString: "100%")
    private let backgroundCheck = NSButton(checkboxWithTitle: "Подложка", target: nil, action: nil)
    private let backgroundWell = PaletteColorWell(frame: CGRect(x: 0, y: 0, width: 36, height: 26))
    private let backgroundOpacitySlider = NSSlider(value: 70, minValue: 0, maxValue: 100, target: nil, action: nil)
    private let backgroundOpacityValue = NSTextField(labelWithString: "70%")

    init() {
        super.init(frame: .zero)
        orientation = .vertical
        alignment = .leading
        spacing = 6
        let basic = NSStackView()
        basic.spacing = 7
        basic.alignment = .centerY
        colorWell.color = .systemRed
        colorWell.toolTip = "Полная палитра цвета"
        colorWell.setAccessibilityLabel("Цвет инструмента")
        basic.addArrangedSubview(label("Цвет"))
        basic.addArrangedSubview(colorWell)
        basic.addArrangedSubview(label("Толщина"))
        basic.addArrangedSubview(widthSlider)
        basic.addArrangedSubview(widthValue)
        hint.font = .systemFont(ofSize: 11)
        hint.textColor = .white.withAlphaComponent(0.85)
        basic.addArrangedSubview(hint)
        addArrangedSubview(basic)

        textRow.alignment = .centerY
        textRow.spacing = 6
        textRow.addArrangedSubview(label("Текст"))
        textRow.addArrangedSubview(fontSlider)
        textRow.addArrangedSubview(fontValue)
        textRow.addArrangedSubview(label("Непрозрачность"))
        textRow.addArrangedSubview(textOpacitySlider)
        textRow.addArrangedSubview(textOpacityValue)
        textRow.addArrangedSubview(backgroundCheck)
        backgroundWell.color = .black
        backgroundWell.toolTip = "Цвет подложки текста"
        backgroundWell.setAccessibilityLabel("Цвет подложки текста")
        textRow.addArrangedSubview(backgroundWell)
        textRow.addArrangedSubview(backgroundOpacitySlider)
        textRow.addArrangedSubview(backgroundOpacityValue)
        addArrangedSubview(textRow)
        textRow.isHidden = true

        for well in [colorWell, backgroundWell] { well.target = self; well.action = #selector(changed) }
        for (slider, width, title) in [(widthSlider, 100.0, "Толщина линии"),
                                       (fontSlider, 85.0, "Размер текста в пикселях"),
                                       (textOpacitySlider, 65.0, "Непрозрачность текста"),
                                       (backgroundOpacitySlider, 65.0, "Непрозрачность подложки")] {
            slider.target = self; slider.action = #selector(changed)
            slider.isContinuous = true
            slider.widthAnchor.constraint(equalToConstant: width).isActive = true
            slider.setAccessibilityLabel(title)
        }
        for value in [widthValue, fontValue, textOpacityValue, backgroundOpacityValue] {
            value.font = .monospacedDigitSystemFont(ofSize: 11, weight: .medium)
            value.widthAnchor.constraint(equalToConstant: 45).isActive = true
        }
        colorWell.widthAnchor.constraint(equalToConstant: 40).isActive = true
        backgroundWell.widthAnchor.constraint(equalToConstant: 36).isActive = true
        backgroundCheck.target = self; backgroundCheck.action = #selector(changed)
        updateValues()
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    private func label(_ title: String) -> NSTextField {
        let label = NSTextField(labelWithString: title)
        label.font = .systemFont(ofSize: 11)
        return label
    }
    func showTool(_ tool: DrawingTool?, shift: Bool = false) {
        let hidden = tool != .text
        if textRow.isHidden != hidden {
            textRow.isHidden = hidden
            onLayoutChanged?()
        }
        hint.stringValue = tool?.shiftHint ?? "Shift — движение по одной оси"
        hint.textColor = shift ? .systemYellow : .white.withAlphaComponent(0.85)
    }
    private func updateValues() {
        widthValue.stringValue = "\(Int(widthSlider.doubleValue.rounded())) px"
        fontValue.stringValue = "\(Int(fontSlider.doubleValue.rounded())) px"
        textOpacityValue.stringValue = "\(Int(textOpacitySlider.doubleValue))%"
        backgroundOpacityValue.stringValue = "\(Int(backgroundOpacitySlider.doubleValue))%"
        backgroundWell.isEnabled = backgroundCheck.state == .on
        backgroundOpacitySlider.isEnabled = backgroundCheck.state == .on
    }
    @objc private func changed() { updateValues(); onChange?() }
    func dismissPalette() {
        let active = colorWell.isActive || backgroundWell.isActive
        colorWell.deactivate(); backgroundWell.deactivate()
        if active { NSColorPanel.shared.orderOut(nil) }
    }
}

private final class InlineAnnotationTextView: NSTextView {
    var onCommit: (() -> Void)?
    // The color panel edits the annotation controls, not the transparent input layer.
    override func changeColor(_ sender: Any?) { }
    override func keyDown(with event: NSEvent) {
        if (event.keyCode == 36 || event.keyCode == 76), !event.modifierFlags.contains(.shift) {
            onCommit?()
        } else { super.keyDown(with: event) }
    }
}

final class InlineTextEditor: NSView, NSTextViewDelegate {
    private let input = InlineAnnotationTextView()
    var onChange: ((String) -> Void)?
    var onCommit: (() -> Void)?
    var text: String { input.string }
    override var isFlipped: Bool { true }

    init() {
        super.init(frame: .zero)
        input.isRichText = false
        input.isHorizontallyResizable = false
        input.isVerticallyResizable = false
        input.drawsBackground = false
        input.textContainerInset = .zero
        input.textContainer?.lineFragmentPadding = 0
        input.textContainer?.widthTracksTextView = true
        input.textColor = .clear
        input.insertionPointColor = .white
        input.delegate = self
        input.onCommit = { [weak self] in self?.onCommit?() }
        input.setAccessibilityLabel("Текст аннотации")
        addSubview(input)
        wantsLayer = true
        layer?.borderColor = NSColor.white.withAlphaComponent(0.45).cgColor
        layer?.borderWidth = 0.5
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    func update(appearance: TextAppearance, color: NSColor, scale: CGFloat) {
        let size = appearance.textSize(text + " ", color: color)
        frame.size = CGSize(width: max(100, size.width * scale + 8),
                            height: max(24, size.height * scale + 3))
        input.frame = bounds
        let font = NSFont.boldSystemFont(ofSize: appearance.fontSize * scale)
        input.font = font
        input.textColor = .clear
        input.typingAttributes = [.font: font, .foregroundColor: NSColor.clear]
        input.selectedTextAttributes = [.backgroundColor: NSColor.selectedTextBackgroundColor,
                                        .foregroundColor: color]
        needsDisplay = true
    }
    func focus() { window?.makeFirstResponder(input) }
    func textDidChange(_ notification: Notification) { onChange?(text) }
}
