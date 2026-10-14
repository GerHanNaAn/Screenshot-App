import AppKit

@main struct AnnotationStyleCheck {
    static func main() throws {
        let width = 420, height = 240
        let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        context.setFillColor(NSColor.white.cgColor)
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let base = NSBitmapImageRep(cgImage: context.makeImage()!).representation(using: .png, properties: [:])!
        func render(_ annotation: Annotation) -> NSBitmapImageRep {
            let document = ScreenshotDocument(data: base)!
            document.add(annotation)
            return NSBitmapImageRep(data: document.pngData()!)!
        }
        func pixel(_ image: NSBitmapImageRep, _ x: Int, _ y: Int) -> (CGFloat, CGFloat, CGFloat) {
            var channels = [Int](repeating: 0, count: image.samplesPerPixel)
            image.getPixel(&channels, atX: x, y: y)
            return (CGFloat(channels[0]) / 255, CGFloat(channels[1]) / 255, CGFloat(channels[2]) / 255)
        }
        let points = [CGPoint(x: 20, y: 20), CGPoint(x: 120, y: 100)]
        for tool in [DrawingTool.ellipse, .rectangle] {
            let outline = render(.drawing(tool: tool, points: points, color: .red, lineWidth: 4, alternative: false))
            let filled = render(.drawing(tool: tool, points: points, color: .red, lineWidth: 4, alternative: true))
            precondition(pixel(outline, 70, 60).1 > 0.99, "Shape interior should stay hollow")
            precondition(pixel(filled, 70, 60).1 < 0.01,
                         "Shift should fill the shape interior")
            precondition(pixel(filled, 5, 5).1 > 0.99, "Fill must stay inside the shape")
        }
        let snapped = Annotation.drawing(tool: .arrow, points: points, color: .red, lineWidth: 4, alternative: true)
        let delta = CGPoint(x: snapped.points.last!.x - 20, y: snapped.points.last!.y - 20)
        precondition(abs(delta.x - delta.y) < 0.001, "Shift arrow must snap to 45 degrees")
        let square = Annotation.drawing(tool: .crop, points: points, color: .red, lineWidth: 4, alternative: true).area
        precondition(square.width == square.height && square.width == 80)
        let pen = Annotation.drawing(tool: .pen, points: [points[0], CGPoint(x: 30, y: 90), points[1]],
                                     color: .red, lineWidth: 4, alternative: true)
        precondition(pen.points == points, "Shift pen should draw a straight stroke")

        func text(_ style: TextAppearance, value: String = "Текст") -> NSBitmapImageRep {
            render(Annotation(tool: .text, points: [CGPoint(x: 24, y: 24)], color: .black,
                              lineWidth: 4, text: value, textAppearance: style))
        }
        let solid = text(TextAppearance(fontSize: 40))
        let translucent = text(TextAppearance(fontSize: 40, opacity: 0.5))
        let invisible = text(TextAppearance(fontSize: 40, opacity: 0))
        var testedGlyph = false
        for y in 24..<90 {
            for x in 24..<170 where pixel(solid, x, y).0 < 0.01 {
                precondition(abs(pixel(translucent, x, y).0 - 0.5) < 0.02, "Text opacity was lost in PNG")
                precondition(pixel(invisible, x, y).0 > 0.99)
                testedGlyph = true
            }
        }
        precondition(testedGlyph, "Text did not render")
        let background = text(TextAppearance(fontSize: 40, opacity: 0, showsBackground: true,
                                              backgroundColor: .blue, backgroundOpacity: 0.5))
        let color = pixel(background, 18, 18)
        precondition(abs(color.0 - 0.5) < 0.02 && abs(color.1 - 0.5) < 0.02 && color.2 > 0.99,
                     "Background color/opacity was lost in PNG")
        precondition(pixel(background, 5, 5).0 > 0.99)
        func inkBounds(_ image: NSBitmapImageRep) -> CGRect {
            var minX = width, minY = height, maxX = 0, maxY = 0
            for y in 0..<height { for x in 0..<width where pixel(image, x, y).0 < 0.9 {
                minX = min(minX, x); minY = min(minY, y); maxX = max(maxX, x); maxY = max(maxY, y)
            } }
            return CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY)
        }
        let smallBounds = inkBounds(text(TextAppearance(fontSize: 20)))
        let largeBounds = inkBounds(solid)
        precondition(largeBounds.width > smallBounds.width * 1.8 && largeBounds.height > smallBounds.height * 1.8)
        let multiline = inkBounds(text(TextAppearance(fontSize: 40), value: "Текст\nТекст"))
        precondition(multiline.height > largeBounds.height * 2, "Second text line was clipped")
        print("OK: Shift, заливка фигур, размер/прозрачность текста и подложки, многострочный PNG")
    }
}
