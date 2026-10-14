import AppKit
import Carbon

enum CaptureAction: Int, CaseIterable {
    case area = 1, window, screen

    var title: String {
        switch self {
        case .area: return "Выделить область"
        case .window: return "Снять окно"
        case .screen: return "Снять экран под курсором"
        }
    }
}

struct KeyCombination: Equatable {
    let keyCode: Int
    let modifiers: UInt32

    var title: String {
        var result = ""
        if modifiers & UInt32(controlKey) != 0 { result += "⌃" }
        if modifiers & UInt32(optionKey) != 0 { result += "⌥" }
        if modifiers & UInt32(shiftKey) != 0 { result += "⇧" }
        if modifiers & UInt32(cmdKey) != 0 { result += "⌘" }
        return result + (KeyboardKeys.name(for: keyCode) ?? "?")
    }

    static func from(_ event: NSEvent) -> KeyCombination? {
        guard KeyboardKeys.name(for: Int(event.keyCode)) != nil else { return nil }
        let flags = event.modifierFlags.intersection([.command, .control, .option, .shift])
        var modifiers: UInt32 = 0
        if flags.contains(.command) { modifiers |= UInt32(cmdKey) }
        if flags.contains(.control) { modifiers |= UInt32(controlKey) }
        if flags.contains(.option) { modifiers |= UInt32(optionKey) }
        if flags.contains(.shift) { modifiers |= UInt32(shiftKey) }
        return KeyCombination(keyCode: Int(event.keyCode), modifiers: modifiers)
    }
}

enum KeyboardKeys {
    private static let entries: [(String, Int)] = [
        ("1", kVK_ANSI_1), ("2", kVK_ANSI_2), ("3", kVK_ANSI_3), ("4", kVK_ANSI_4),
        ("5", kVK_ANSI_5), ("6", kVK_ANSI_6), ("7", kVK_ANSI_7), ("8", kVK_ANSI_8),
        ("9", kVK_ANSI_9), ("0", kVK_ANSI_0),
        ("A", kVK_ANSI_A), ("B", kVK_ANSI_B), ("C", kVK_ANSI_C), ("D", kVK_ANSI_D),
        ("E", kVK_ANSI_E), ("F", kVK_ANSI_F), ("G", kVK_ANSI_G), ("H", kVK_ANSI_H),
        ("I", kVK_ANSI_I), ("J", kVK_ANSI_J), ("K", kVK_ANSI_K), ("L", kVK_ANSI_L),
        ("M", kVK_ANSI_M), ("N", kVK_ANSI_N), ("O", kVK_ANSI_O), ("P", kVK_ANSI_P),
        ("Q", kVK_ANSI_Q), ("R", kVK_ANSI_R), ("S", kVK_ANSI_S), ("T", kVK_ANSI_T),
        ("U", kVK_ANSI_U), ("V", kVK_ANSI_V), ("W", kVK_ANSI_W), ("X", kVK_ANSI_X),
        ("Y", kVK_ANSI_Y), ("Z", kVK_ANSI_Z)
    ]

    static func name(for code: Int) -> String? { entries.first { $0.1 == code }?.0 }
    static func isEditorKey(_ code: Int) -> Bool { name(for: code) != nil }
}

final class AppSettings {
    static let shared = AppSettings()
    static let changed = Notification.Name("JoxiLiteSettingsChanged")
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    var closeOnEscape: Bool {
        get { defaults.object(forKey: "closeOnEscape") as? Bool ?? true }
        set { defaults.set(newValue, forKey: "closeOnEscape"); notify() }
    }
    var confirmUnsaved: Bool {
        get { defaults.object(forKey: "confirmUnsaved") as? Bool ?? true }
        set { defaults.set(newValue, forKey: "confirmUnsaved"); notify() }
    }
    var includeCursor: Bool {
        get { defaults.object(forKey: "includeCursor") as? Bool ?? false }
        set { defaults.set(newValue, forKey: "includeCursor"); notify() }
    }
    var historyLimitMB: Int {
        get {
            guard let stored = defaults.object(forKey: "historyLimitMB") as? Int else { return 100 }
            return max(10, min(10_000, stored))
        }
        set { defaults.set(max(10, min(10_000, newValue)), forKey: "historyLimitMB"); notify() }
    }

    func hotKey(for action: CaptureAction) -> KeyCombination? {
        let prefix = "capture.\(action.rawValue)"
        guard let code = defaults.object(forKey: "\(prefix).keyCode") as? Int else {
            switch action {
            case .area: return KeyCombination(keyCode: kVK_ANSI_2, modifiers: UInt32(cmdKey | shiftKey))
            case .window: return KeyCombination(keyCode: kVK_ANSI_3, modifiers: UInt32(controlKey | optionKey))
            case .screen: return KeyCombination(keyCode: kVK_ANSI_4, modifiers: UInt32(controlKey | optionKey))
            }
        }
        guard code >= 0 else { return nil }
        return KeyCombination(keyCode: code,
                              modifiers: UInt32(defaults.integer(forKey: "\(prefix).modifiers")))
    }

    func setHotKey(_ shortcut: KeyCombination?, for action: CaptureAction) -> String? {
        if let shortcut {
            guard KeyboardKeys.name(for: shortcut.keyCode) != nil,
                  shortcut.modifiers & UInt32(cmdKey | controlKey | optionKey) != 0 else {
                return "Для снимка укажите букву или цифру вместе с ⌘, ⌃ или ⌥."
            }
            for other in CaptureAction.allCases where other != action {
                if hotKey(for: other) == shortcut { return "Это сочетание уже назначено другому режиму снимка." }
            }
        }
        let prefix = "capture.\(action.rawValue)"
        defaults.set(shortcut?.keyCode ?? -1, forKey: "\(prefix).keyCode")
        defaults.set(Int(shortcut?.modifiers ?? 0), forKey: "\(prefix).modifiers")
        notify()
        return nil
    }

    func toolKey(for tool: DrawingTool) -> Int? {
        guard let index = DrawingTool.allCases.firstIndex(of: tool) else { return nil }
        let key = "tool.\(index)"
        if let code = defaults.object(forKey: key) as? Int { return code >= 0 ? code : nil }
        return [kVK_ANSI_1, kVK_ANSI_2, kVK_ANSI_3, kVK_ANSI_4,
                kVK_ANSI_5, kVK_ANSI_6, kVK_ANSI_7, kVK_ANSI_8][index]
    }

    func setToolKey(_ code: Int?, for tool: DrawingTool) -> String? {
        if let code {
            guard KeyboardKeys.isEditorKey(code) else { return "Для инструмента укажите букву или цифру без модификаторов." }
            for other in DrawingTool.allCases where other != tool {
                if toolKey(for: other) == code { return "Эта клавиша уже назначена другому инструменту." }
            }
        }
        guard let index = DrawingTool.allCases.firstIndex(of: tool) else { return "Неизвестный инструмент." }
        defaults.set(code ?? -1, forKey: "tool.\(index)")
        notify()
        return nil
    }

    func tool(for keyCode: Int) -> DrawingTool? {
        DrawingTool.allCases.first { toolKey(for: $0) == keyCode }
    }

    func restoreDefaults() {
        defaults.removeObject(forKey: "closeOnEscape")
        defaults.removeObject(forKey: "confirmUnsaved")
        defaults.removeObject(forKey: "includeCursor")
        defaults.removeObject(forKey: "historyLimitMB")
        for action in CaptureAction.allCases {
            defaults.removeObject(forKey: "capture.\(action.rawValue).keyCode")
            defaults.removeObject(forKey: "capture.\(action.rawValue).modifiers")
        }
        for index in DrawingTool.allCases.indices { defaults.removeObject(forKey: "tool.\(index)") }
        notify()
    }

    private func notify() { NotificationCenter.default.post(name: Self.changed, object: self) }
}
