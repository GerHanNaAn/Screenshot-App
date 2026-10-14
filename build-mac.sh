#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
app_dir="$HOME/Applications/JoxiLite.app"
mkdir -p "$app_dir/Contents/MacOS" "$app_dir/Contents/Resources"
swiftc -O -framework AppKit -framework Carbon -framework ScreenCaptureKit Sources/*.swift -o "$app_dir/Contents/MacOS/JoxiLite"
cp Resources/JoxiLite.icns "$app_dir/Contents/Resources/JoxiLite.icns"
cat > "$app_dir/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>JoxiLite</string>
<key>CFBundleDisplayName</key><string>JoxiLite</string>
<key>CFBundleIdentifier</key><string>com.german.joxilite</string>
<key>CFBundleExecutable</key><string>JoxiLite</string>
<key>CFBundleIconFile</key><string>JoxiLite</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSMinimumSystemVersion</key><string>12.0</string>
<key>CFBundleVersion</key><string>5</string>
<key>CFBundleShortVersionString</key><string>3.1</string>
<key>LSUIElement</key><true/>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --sign - "$app_dir"
printf 'Готово: %s\n' "$app_dir"
