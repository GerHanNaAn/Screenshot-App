import AppKit
import Carbon

@main struct PreferencesCheck {
    static func main() {
        let suite = "com.german.joxilite.preferences-test.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suite) else { fatalError("No test defaults") }
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)

        assert(settings.closeOnEscape)
        assert(settings.confirmUnsaved)
        assert(settings.hotKey(for: .area) == KeyCombination(keyCode: kVK_ANSI_2,
                                                            modifiers: UInt32(cmdKey | shiftKey)))
        assert(settings.hotKey(for: .window) == KeyCombination(keyCode: kVK_ANSI_3,
                                                              modifiers: UInt32(controlKey | optionKey)))
        assert(settings.toolKey(for: .arrow) == kVK_ANSI_1)
        assert(settings.tool(for: kVK_ANSI_8) == .crop)

        let capture = KeyCombination(keyCode: kVK_ANSI_B, modifiers: UInt32(cmdKey | optionKey))
        assert(settings.setHotKey(capture, for: .window) == nil)
        assert(settings.hotKey(for: .window) == capture)
        assert(settings.setHotKey(capture, for: .screen) != nil)
        assert(settings.setHotKey(KeyCombination(keyCode: kVK_ANSI_C, modifiers: 0), for: .screen) != nil)
        assert(settings.setToolKey(kVK_ANSI_A, for: .arrow) == nil)
        assert(settings.setToolKey(kVK_ANSI_A, for: .rectangle) != nil)
        assert(settings.tool(for: kVK_ANSI_A) == .arrow)
        settings.closeOnEscape = false
        settings.confirmUnsaved = false

        let reloaded = AppSettings(defaults: defaults)
        assert(!reloaded.closeOnEscape && !reloaded.confirmUnsaved)
        assert(reloaded.hotKey(for: .window) == capture)
        assert(reloaded.toolKey(for: .arrow) == kVK_ANSI_A)
        reloaded.restoreDefaults()
        assert(reloaded.closeOnEscape && reloaded.confirmUnsaved)
        assert(reloaded.hotKey(for: .window) == KeyCombination(keyCode: kVK_ANSI_3,
                                                              modifiers: UInt32(controlKey | optionKey)))
        assert(reloaded.toolKey(for: .arrow) == kVK_ANSI_1)
        print("OK: настройки, сочетания и восстановление значений")
    }
}
