import AppKit
import ImageIO
import ScreenCaptureKit

enum NativeCapture {
    @available(macOS 14.0, *)
    static func availableWindows() async throws -> [SCWindow] {
        let content = try await SCShareableContent.excludingDesktopWindows(true,
                                                                            onScreenWindowsOnly: true)
        return content.windows.filter { window in
            window.owningApplication?.bundleIdentifier != Bundle.main.bundleIdentifier &&
            window.owningApplication?.bundleIdentifier != "com.apple.dock" &&
            !(window.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            window.frame.width > 200 && window.frame.height > 100
        }
    }

    @available(macOS 14.0, *)
    static func mainDisplay() async throws -> Data {
        try await display(CGMainDisplayID(), showsCursor: AppSettings.shared.includeCursor)
    }

    @available(macOS 14.0, *)
    static func display(_ displayID: CGDirectDisplayID, showsCursor: Bool) async throws -> Data {
        let content = try await SCShareableContent.excludingDesktopWindows(false,
                                                                            onScreenWindowsOnly: true)
        guard let display = content.displays.first(where: { $0.displayID == displayID })
                ?? content.displays.first else {
            throw CaptureFailure.noDisplay
        }
        let filter = SCContentFilter(display: display, excludingWindows: [])
        return try await capture(filter: filter, showsCursor: showsCursor)
    }

    @available(macOS 14.0, *)
    static func window(_ window: SCWindow) async throws -> Data {
        try await capture(filter: SCContentFilter(desktopIndependentWindow: window),
                          showsCursor: AppSettings.shared.includeCursor)
    }

    @available(macOS 14.0, *)
    private static func capture(filter: SCContentFilter, showsCursor: Bool) async throws -> Data {
        let configuration = SCStreamConfiguration()
        configuration.width = max(1, Int(filter.contentRect.width * CGFloat(filter.pointPixelScale)))
        configuration.height = max(1, Int(filter.contentRect.height * CGFloat(filter.pointPixelScale)))
        configuration.showsCursor = showsCursor
        let image = try await SCScreenshotManager.captureImage(contentFilter: filter,
                                                               configuration: configuration)
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, "public.png" as CFString, 1, nil) else {
            throw CaptureFailure.encode
        }
        CGImageDestinationAddImage(destination, image, nil)
        guard CGImageDestinationFinalize(destination) else { throw CaptureFailure.encode }
        return data as Data
    }
}

private enum CaptureFailure: LocalizedError {
    case noDisplay, encode
    var errorDescription: String? {
        switch self {
        case .noDisplay: return "Не найден экран для захвата."
        case .encode: return "Не удалось подготовить PNG."
        }
    }
}
