import Foundation

@main struct HistoryCheck {
    static func main() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("JoxiLite-History-Test-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let history = HistoryStore(directoryURL: directory)
        let first = try history.save(Data(repeating: 1, count: 6_000_000), limitMB: 10)
        try FileManager.default.setAttributes([.creationDate: Date(timeIntervalSince1970: 1_000)],
                                              ofItemAtPath: first.path)
        let second = try history.save(Data(repeating: 2, count: 6_000_000), limitMB: 10)
        assert(!FileManager.default.fileExists(atPath: first.path))
        assert(FileManager.default.fileExists(atPath: second.path))
        do {
            _ = try history.save(Data(repeating: 3, count: 11_000_000), limitMB: 10)
            fatalError("Expected limit error")
        } catch HistoryFailure.tooLarge { }
        assert(FileManager.default.fileExists(atPath: second.path))
        print("OK: история и лимит размера")
    }
}
