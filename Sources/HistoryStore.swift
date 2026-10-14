import Foundation

enum HistoryFailure: LocalizedError {
    case tooLarge
    var errorDescription: String? {
        switch self {
        case .tooLarge: return "Снимок превышает лимит папки истории. Увеличьте лимит в настройках."
        }
    }
}

final class HistoryStore {
    static let shared = HistoryStore()
    private let files = FileManager.default
    let directoryURL: URL

    init(directoryURL: URL? = nil) {
        self.directoryURL = directoryURL ?? FileManager.default.urls(for: .applicationSupportDirectory,
                                                                     in: .userDomainMask)[0]
            .appendingPathComponent("JoxiLite/History", isDirectory: true)
    }

    @discardableResult
    func save(_ png: Data, limitMB: Int) throws -> URL {
        let limit = Int64(max(10, limitMB)) * 1_000_000
        guard Int64(png.count) <= limit else { throw HistoryFailure.tooLarge }
        try files.createDirectory(at: directoryURL, withIntermediateDirectories: true)
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd_HH-mm-ss"
        let name = "\(formatter.string(from: Date()))_\(UUID().uuidString.prefix(8)).png"
        let destination = directoryURL.appendingPathComponent(name)
        try png.write(to: destination, options: .atomic)
        try prune(limitMB: limitMB)
        return destination
    }

    func prune(limitMB: Int) throws {
        let limit = Int64(max(10, limitMB)) * 1_000_000
        guard files.fileExists(atPath: directoryURL.path) else { return }
        let urls = try files.contentsOfDirectory(at: directoryURL,
                                                  includingPropertiesForKeys: [.fileSizeKey, .creationDateKey],
                                                  options: [.skipsHiddenFiles])
            .filter { $0.pathExtension.lowercased() == "png" }
        let entries = try urls.map { url -> (URL, Int64, Date) in
            let values = try url.resourceValues(forKeys: [.fileSizeKey, .creationDateKey])
            return (url, Int64(values.fileSize ?? 0), values.creationDate ?? .distantPast)
        }.sorted { $0.2 < $1.2 }
        var size = entries.reduce(Int64(0)) { $0 + $1.1 }
        for (url, bytes, _) in entries where size > limit {
            try files.removeItem(at: url)
            size -= bytes
        }
    }
}
