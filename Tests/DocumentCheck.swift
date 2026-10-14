import AppKit

@main
struct DocumentCheck {
    static func main() throws {
        let input = URL(fileURLWithPath: CommandLine.arguments[1])
        let directory = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
        guard let document = ScreenshotDocument(data: try Data(contentsOf: input)) else {
            throw NSError(domain: "DocumentCheck", code: 1)
        }
        func write(_ name: String) throws {
            guard let data = document.pngData() else { throw NSError(domain: "DocumentCheck", code: 2) }
            try data.write(to: directory.appendingPathComponent(name + ".png"))
        }
        try write("original")
        document.setCrop(CGRect(x: 8, y: 6, width: 20, height: 18))
        try write("cropped")
        document.undo()
        try write("restored")
        document.redo()
        try write("redone")
        document.undo()
        document.add(Annotation(tool: .pen,
                                points: [CGPoint(x: 4, y: 4), CGPoint(x: 20, y: 15), CGPoint(x: 48, y: 4)],
                                color: .white, lineWidth: 3, text: ""))
        try write("pen")
        document.undo()
        try write("penUndone")
        document.redo()
        try write("penRedone")
        document.add(Annotation(tool: .pixelate,
                                points: [CGPoint(x: 0, y: 0), CGPoint(x: 32, y: 24)],
                                color: .white, lineWidth: 3, text: ""))
        try write("mosaic")
    }
}
