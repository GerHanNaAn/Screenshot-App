import AppKit
import CoreText
import ImageIO

enum DrawingTool: String, CaseIterable {
    case arrow = "Стрелка"
    case rectangle = "Рамка"
    case ellipse = "Овал"
    case line = "Линия"
    case pen = "Перо"
    case text = "Текст"
    case pixelate = "Мозаика"
    case crop = "Обрезка"

    var shiftHint: String {
        switch self {
        case .ellipse, .rectangle: return "Shift — заливка фигуры"
        case .line, .arrow: return "Shift — направление с шагом 45°"
        case .pen: return "Shift — прямой штрих"
        case .pixelate: return "Shift — крупная мозаика"
        case .crop: return "Shift — квадратная область"
        case .text: return "Enter — применить · Shift+Enter — новая строка"
        }
    }
}

struct TextAppearance {
    var fontSize: CGFloat = 28
    var opacity: CGFloat = 1
    var showsBackground = false
    var backgroundColor: NSColor = .black
    var backgroundOpacity: CGFloat = 0.7

    func attributedString(_ text: String, color: NSColor) -> NSAttributedString {
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineBreakMode = .byClipping
        return NSAttributedString(string: text.isEmpty ? " " : text, attributes: [
            .font: NSFont.boldSystemFont(ofSize: fontSize),
            .foregroundColor: color.withAlphaComponent(color.alphaComponent * opacity),
            .paragraphStyle: paragraph
        ])
    }

    func textSize(_ text: String, color: NSColor) -> CGSize {
        let bounds = attributedString(text, color: color).boundingRect(
            with: CGSize(width: 20_000, height: 20_000),
            options: [.usesLineFragmentOrigin, .usesFontLeading])
        return CGSize(width: max(fontSize, ceil(bounds.width)),
                      height: max(ceil(NSFont.boldSystemFont(ofSize: fontSize).boundingRectForFont.height),
                                  ceil(bounds.height)))
    }
}

struct Annotation {
    let tool: DrawingTool
    let points: [CGPoint]
    let color: NSColor
    let lineWidth: CGFloat
    let text: String
    var filled = false
    var textAppearance: TextAppearance? = nil
    var mosaicBlockSize: CGFloat = 14

    var area: CGRect {
        guard let first = points.first, let last = points.last else { return .zero }
        return CGRect(x: min(first.x, last.x), y: min(first.y, last.y),
                      width: abs(last.x - first.x), height: abs(last.y - first.y))
    }

    static func drawing(tool: DrawingTool, points: [CGPoint], color: NSColor,
                        lineWidth: CGFloat, alternative: Bool) -> Annotation {
        var adjusted = points
        if alternative, let first = points.first, let last = points.last {
            switch tool {
            case .line, .arrow:
                let length = hypot(last.x - first.x, last.y - first.y)
                let angle = (atan2(last.y - first.y, last.x - first.x) / (.pi / 4)).rounded() * (.pi / 4)
                adjusted = [first, CGPoint(x: first.x + length * cos(angle), y: first.y + length * sin(angle))]
            case .pen: adjusted = [first, last]
            case .crop:
                let side = min(abs(last.x - first.x), abs(last.y - first.y))
                adjusted = [first, CGPoint(x: first.x + (last.x >= first.x ? side : -side),
                                           y: first.y + (last.y >= first.y ? side : -side))]
            default: break
            }
        }
        return Annotation(tool: tool, points: adjusted, color: color, lineWidth: lineWidth,
                          text: "", filled: alternative && (tool == .ellipse || tool == .rectangle),
                          mosaicBlockSize: alternative ? 28 : 14)
    }
}

private struct DocumentState {
    var annotations: [Annotation]
    var crop: CGRect?
}

final class ScreenshotDocument {
    let image: CGImage
    let size: CGSize
    private(set) var annotations: [Annotation] = []
    private(set) var crop: CGRect?
    private var undoStack: [DocumentState] = []
    private var redoStack: [DocumentState] = []
    var onChange: (() -> Void)?

    init?(data: Data) {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { return nil }
        self.image = image
        size = CGSize(width: image.width, height: image.height)
    }

    private var state: DocumentState { DocumentState(annotations: annotations, crop: crop) }
    private func checkpoint() {
        undoStack.append(state)
        if undoStack.count > 100 { undoStack.removeFirst() }
        redoStack.removeAll()
    }
    var canUndo: Bool { !undoStack.isEmpty }
    var canRedo: Bool { !redoStack.isEmpty }
    var hasEdits: Bool { !undoStack.isEmpty || !annotations.isEmpty || crop != nil }

    func add(_ annotation: Annotation) {
        checkpoint(); annotations.append(annotation); onChange?()
    }
    func setCrop(_ rect: CGRect?) {
        let bounded = rect?.standardized.intersection(CGRect(origin: .zero, size: size)).integral
        guard crop != bounded else { return }
        checkpoint(); crop = (bounded?.width ?? 0) > 2 && (bounded?.height ?? 0) > 2 ? bounded : nil
        onChange?()
    }
    func undo() {
        guard let previous = undoStack.popLast() else { return }
        redoStack.append(state); annotations = previous.annotations; crop = previous.crop; onChange?()
    }
    func redo() {
        guard let next = redoStack.popLast() else { return }
        undoStack.append(state); annotations = next.annotations; crop = next.crop; onChange?()
    }

    func render(in context: CGContext, preview: Annotation? = nil, showCropMask: Bool = false) {
        let imageRect = CGRect(origin: .zero, size: size)
        context.saveGState()
        context.clip(to: imageRect)
        renderBase(in: context)
        renderAnnotations(in: context, preview: preview)
        if showCropMask, let crop {
            context.setFillColor(NSColor.black.withAlphaComponent(0.48).cgColor)
            context.fill(CGRect(x: 0, y: 0, width: size.width, height: crop.minY))
            context.fill(CGRect(x: 0, y: crop.maxY, width: size.width, height: size.height - crop.maxY))
            context.fill(CGRect(x: 0, y: crop.minY, width: crop.minX, height: crop.height))
            context.fill(CGRect(x: crop.maxX, y: crop.minY, width: size.width - crop.maxX, height: crop.height))
            context.setStrokeColor(NSColor.white.cgColor)
            context.setLineWidth(2)
            context.stroke(crop)
        }
        context.restoreGState()
    }

    func renderBase(in context: CGContext) {
        let imageRect = CGRect(origin: .zero, size: size)
        context.saveGState()
        context.translateBy(x: 0, y: size.height)
        context.scaleBy(x: 1, y: -1)
        context.interpolationQuality = .high
        context.draw(image, in: imageRect)
        context.restoreGState()
    }

    func renderAnnotations(in context: CGContext, preview: Annotation? = nil) {
        for annotation in annotations { draw(annotation, in: context) }
        if let preview { draw(preview, in: context) }
    }

    func renderAnnotation(_ annotation: Annotation, in context: CGContext) { draw(annotation, in: context) }

    private func draw(_ annotation: Annotation, in context: CGContext) {
        guard let first = annotation.points.first else { return }
        context.saveGState()
        context.setStrokeColor(annotation.color.cgColor)
        context.setFillColor(annotation.color.cgColor)
        context.setLineWidth(annotation.lineWidth)
        context.setLineCap(.round)
        context.setLineJoin(.round)
        let last = annotation.points.last ?? first
        switch annotation.tool {
        case .pen:
            context.move(to: first)
            for point in annotation.points.dropFirst() { context.addLine(to: point) }
            if annotation.points.count == 1 { context.addLine(to: CGPoint(x: first.x + 0.01, y: first.y)) }
            context.strokePath()
        case .line, .arrow:
            context.move(to: first); context.addLine(to: last); context.strokePath()
            if annotation.tool == .arrow {
                let angle = atan2(last.y - first.y, last.x - first.x)
                let length = max(12, annotation.lineWidth * 5)
                for offset in [-CGFloat.pi / 6, CGFloat.pi / 6] {
                    context.move(to: last)
                    context.addLine(to: CGPoint(x: last.x - length * cos(angle + offset),
                                                y: last.y - length * sin(angle + offset)))
                }
                context.strokePath()
            }
        case .rectangle:
            if annotation.filled { context.fill(annotation.area) }
            else { context.stroke(annotation.area) }
        case .ellipse:
            if annotation.filled { context.fillEllipse(in: annotation.area) }
            else { context.strokeEllipse(in: annotation.area) }
        case .text:
            let style = annotation.textAppearance ?? TextAppearance(fontSize: max(18, annotation.lineWidth * 6))
            let textRect = CGRect(origin: first, size: style.textSize(annotation.text, color: annotation.color))
            if style.showsBackground {
                context.setFillColor(style.backgroundColor.withAlphaComponent(
                    style.backgroundColor.alphaComponent * style.backgroundOpacity).cgColor)
                let padding = max(4, style.fontSize * 0.2)
                context.fill(textRect.insetBy(dx: -padding, dy: -padding))
            }
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
            style.attributedString(annotation.text, color: annotation.color).draw(
                with: textRect, options: [.usesLineFragmentOrigin, .usesFontLeading])
            NSGraphicsContext.restoreGraphicsState()
        case .pixelate: pixelate(annotation.area, block: annotation.mosaicBlockSize, in: context)
        case .crop:
            context.setStrokeColor(NSColor.white.cgColor)
            context.setLineWidth(2)
            context.setLineDash(phase: 0, lengths: [7, 5])
            context.stroke(annotation.area)
        }
        context.restoreGState()
    }

    private func pixelate(_ area: CGRect, block: CGFloat, in context: CGContext) {
        let rect = area.integral.intersection(CGRect(origin: .zero, size: size))
        guard rect.width > 2, rect.height > 2, let source = image.cropping(to: rect) else { return }
        let width = max(1, Int(ceil(rect.width / block)))
        let height = max(1, Int(ceil(rect.height / block)))
        guard let small = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                    bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return }
        small.interpolationQuality = .low
        small.draw(source, in: CGRect(x: 0, y: 0, width: width, height: height))
        guard let mosaic = small.makeImage() else { return }
        context.saveGState()
        context.clip(to: rect)
        context.translateBy(x: rect.minX, y: rect.maxY)
        context.scaleBy(x: 1, y: -1)
        context.interpolationQuality = .none
        context.draw(mosaic, in: CGRect(origin: .zero, size: rect.size))
        context.restoreGState()
    }

    func pngData() -> Data? {
        let output = (crop ?? CGRect(origin: .zero, size: size)).integral
        let width = Int(output.width), height = Int(output.height)
        guard width > 0, height > 0,
              let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                      bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        context.translateBy(x: 0, y: output.height)
        context.scaleBy(x: 1, y: -1)
        context.translateBy(x: -output.minX, y: -output.minY)
        render(in: context)
        guard let result = context.makeImage() else { return nil }
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, "public.png" as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(destination, result, nil)
        guard CGImageDestinationFinalize(destination) else { return nil }
        return data as Data
    }
}
