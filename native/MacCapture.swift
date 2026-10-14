import AppKit
import ScreenCaptureKit
import ImageIO

@main struct CaptureHelper {
    static func main() async {
        do {
            guard #available(macOS 14.0, *) else { throw Failure.message("ScreenCaptureKit требует macOS 14 или новее.") }
            let args = CommandLine.arguments
            guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else {
                throw Failure.message("Разрешите JoxiLite запись экрана в Системных настройках → Конфиденциальность и безопасность → Запись экрана. После выдачи доступа перезапустите JoxiLite.")
            }
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            let windows = content.windows.filter {
                $0.owningApplication?.bundleIdentifier != "com.german.joxilite" &&
                $0.owningApplication?.bundleIdentifier != "com.apple.dock" &&
                !($0.title ?? "").isEmpty && $0.frame.width > 40 && $0.frame.height > 40
            }
            if args[1] == "windows" {
                try emit(windows.map { ["id": $0.windowID, "title": "\($0.owningApplication?.applicationName ?? "") — \($0.title ?? "")"] as [String:Any] })
                return
            }
            let directory = URL(fileURLWithPath: args[2], isDirectory: true)
            let cursor = args.contains("--cursor")
            var output: [[String:Any]] = []
            if args[1] == "window" {
                guard let id = UInt32(args[3]), let window = windows.first(where: {$0.windowID == id}) else { throw Failure.message("Окно закрыто. Повторите выбор.") }
                let filter = SCContentFilter(desktopIndependentWindow: window)
                let path = directory.appendingPathComponent("window.png")
                try await capture(filter, path, cursor)
                output.append(["path":path.path, "x":0,"y":0,"width":window.frame.width,"height":window.frame.height,"name":window.title ?? "Окно"])
            } else {
                for display in content.displays {
                    let filter = SCContentFilter(display: display, excludingWindows: [])
                    let path = directory.appendingPathComponent("\(display.displayID).png")
                    try await capture(filter, path, cursor)
                    let bounds = CGDisplayBounds(display.displayID)
                    output.append(["path":path.path,"x":bounds.minX,"y":bounds.minY,"width":bounds.width,"height":bounds.height,"name":"\(display.displayID)"])
                }
            }
            try emit(output)
        } catch {
            FileHandle.standardError.write(Data(error.localizedDescription.utf8))
            exit(1)
        }
    }
    static func emit(_ value:Any) throws {
        let data = try JSONSerialization.data(withJSONObject:value, options:[.sortedKeys])
        FileHandle.standardOutput.write(data)
    }
    @available(macOS 14.0, *)
    static func capture(_ filter:SCContentFilter, _ url:URL, _ cursor:Bool) async throws {
        let config = SCStreamConfiguration()
        config.width = max(1,Int(filter.contentRect.width*CGFloat(filter.pointPixelScale)))
        config.height = max(1,Int(filter.contentRect.height*CGFloat(filter.pointPixelScale)))
        config.showsCursor = cursor
        config.ignoreShadowsSingleWindow = true
        let image = try await SCScreenshotManager.captureImage(contentFilter:filter, configuration:config)
        guard let dest = CGImageDestinationCreateWithURL(url as CFURL,"public.png" as CFString,1,nil) else { throw Failure.message("Не удалось создать PNG.") }
        CGImageDestinationAddImage(dest,image,nil)
        guard CGImageDestinationFinalize(dest) else { throw Failure.message("Не удалось записать PNG.") }
    }
}
enum Failure:LocalizedError {
    case message(String)
    var errorDescription:String? { if case let .message(text)=self {return text};return nil }
}
