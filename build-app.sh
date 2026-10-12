#!/bin/sh
# Build Breeze.app into ~/Applications.
# The app is native Swift; the air conditioner protocol runs in the Python helper from this
# folder, which the app starts on launch and stops on quit. Rebuild after moving the folder.
set -eu

PROJECT="$(cd "$(dirname "$0")" && pwd)"
UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
  echo "uv is not installed. Install it first: https://docs.astral.sh/uv/" >&2
  exit 1
fi

APP="$HOME/Applications/Breeze.app"
BUILD="$PROJECT/build"
mkdir -p "$BUILD"

echo "Checking the helper..."
(cd "$PROJECT" && "$UV" sync --quiet && "$UV" run --quiet python -c "import server") || {
  echo "The helper does not start. Fix the error above first." >&2
  exit 1
}

echo "Compiling..."
xcrun swiftc -O -parse-as-library -target arm64-apple-macos15.0 \
  -o "$BUILD/Breeze" "$PROJECT"/mac/*.swift \
  -framework AppKit -framework SwiftUI -framework Carbon

echo "Drawing icon..."
rm -rf "$BUILD/Breeze.iconset"
xcrun swift "$PROJECT/tools/make-icon.swift" "$BUILD/Breeze.iconset"
iconutil -c icns "$BUILD/Breeze.iconset" -o "$BUILD/Breeze.icns"

# Quit the installed app (it stops its helper), and any helper left on the port.
pkill -x Breeze 2>/dev/null || true
pkill -f "breeze.py serve --port 8767" 2>/dev/null || true
sleep 1

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BUILD/Breeze" "$APP/Contents/MacOS/Breeze"
cp "$BUILD/Breeze.icns" "$APP/Contents/Resources/Breeze.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Breeze</string>
  <key>CFBundleDisplayName</key><string>Breeze</string>
  <key>CFBundleIdentifier</key><string>com.abiodun.breeze</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Breeze</string>
  <key>CFBundleIconFile</key><string>Breeze</string>
  <key>LSMinimumSystemVersion</key><string>15.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
  <key>NSHumanReadableCopyright</key><string>Remote for Midea air conditioners</string>
  <key>CFBundleURLTypes</key>
  <array><dict>
    <key>CFBundleURLName</key><string>com.abiodun.breeze</string>
    <key>CFBundleURLSchemes</key><array><string>breeze</string></array>
  </dict></array>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST
# plutil escapes the paths, so a folder name with & or < cannot break the plist.
plutil -insert BreezeProjectPath -string "$PROJECT" "$APP/Contents/Info.plist"
plutil -insert BreezeUVPath -string "$UV" "$APP/Contents/Info.plist"

codesign --force --deep -s - "$APP" >/dev/null
echo "Built $APP"
