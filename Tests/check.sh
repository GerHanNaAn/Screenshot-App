#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
test_dir="$(mktemp -d)"
trap 'rm -rf "$test_dir"' EXIT
python3 - "$test_dir/input.png" <<'PY'
from PIL import Image
import sys
image = Image.new('RGB', (64, 48))
for y in range(48):
    for x in range(64):
        image.putpixel((x, y), (x * 4, y * 5, (x * 3 + y * 2) % 256))
image.save(sys.argv[1])
PY
swiftc -O -framework AppKit Sources/ScreenshotDocument.swift Tests/DocumentCheck.swift -o "$test_dir/document-check"
"$test_dir/document-check" "$test_dir/input.png" "$test_dir"
python3 - "$test_dir" <<'PY'
from PIL import Image, ImageChops
from pathlib import Path
import sys
root = Path(sys.argv[1])
def image(name):
    return Image.open(root / (name + '.png')).convert('RGB')
source = image('input')
assert image('original').size == (64, 48)
assert ImageChops.difference(image('original'), source).getbbox() is None, 'pixels changed on export'
assert image('cropped').size == (20, 18)
assert ImageChops.difference(image('cropped'), source.crop((8, 6, 28, 24))).getbbox() is None
assert ImageChops.difference(image('restored'), source).getbbox() is None
assert ImageChops.difference(image('redone'), image('cropped')).getbbox() is None
assert ImageChops.difference(image('penUndone'), source).getbbox() is None
assert ImageChops.difference(image('penRedone'), image('pen')).getbbox() is None
assert ImageChops.difference(image('pen'), source).getbbox() is not None
assert image('mosaic').getpixel((40, 30)) == image('pen').getpixel((40, 30))
assert image('mosaic').getpixel((10, 10)) != image('pen').getpixel((10, 10))
print('OK: экспорт, обрезка, перо, мозаика, отмена и повтор')
PY
swiftc -O -framework AppKit -framework Carbon Sources/ScreenshotDocument.swift Sources/AppSettings.swift Tests/PreferencesCheck.swift -o "$test_dir/preferences-check"
"$test_dir/preferences-check"
swiftc -O -framework AppKit Sources/ScreenshotDocument.swift Tests/AnnotationStyleCheck.swift -o "$test_dir/annotation-style-check"
"$test_dir/annotation-style-check"
swiftc -O Sources/HistoryStore.swift Tests/HistoryCheck.swift -o "$test_dir/history-check"
"$test_dir/history-check"
