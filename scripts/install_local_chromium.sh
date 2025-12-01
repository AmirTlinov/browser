#!/bin/bash
# Download and install Chromium locally in the project
# No system-wide installation required - fully portable

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$PROJECT_ROOT/vendor"
CHROMIUM_DIR="$VENDOR_DIR/chromium"

echo "============================================"
echo "Local Chromium Installation"
echo "============================================"
echo ""
echo "Installing Chromium to: $CHROMIUM_DIR"
echo ""

# Detect architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64)
        ARCH_NAME="Linux_x64"
        ;;
    aarch64|arm64)
        ARCH_NAME="Linux_ARM"
        ;;
    *)
        echo "❌ Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

echo "Detected architecture: $ARCH ($ARCH_NAME)"
echo ""

# Create directories
mkdir -p "$VENDOR_DIR"

# Download latest stable Chromium snapshot
echo "Downloading Chromium for $ARCH_NAME..."
echo ""

# Use chromium snapshots - get latest stable version
# We'll download from commondatastorage.googleapis.com
CHROMIUM_URL="https://download-chromium.appspot.com/dl/Linux_x64?type=snapshots"

# Alternative: use a known stable version
# For now, let's use playwright's chromium download approach
# We'll download a recent stable build

# Check if we have wget or curl
if command -v wget &> /dev/null; then
    DOWNLOADER="wget -O"
elif command -v curl &> /dev/null; then
    DOWNLOADER="curl -L -o"
else
    echo "❌ Neither wget nor curl found. Please install one of them."
    exit 1
fi

# Download using playwright's chromium build (known stable version)
# Revision 1140 corresponds to Chromium ~131
REVISION="1140"
CHROMIUM_ZIP_URL="https://playwright.azureedge.net/builds/chromium/${REVISION}/chromium-linux.zip"

TEMP_ZIP="$VENDOR_DIR/chromium.zip"

echo "Downloading from: $CHROMIUM_ZIP_URL"
$DOWNLOADER "$TEMP_ZIP" "$CHROMIUM_ZIP_URL"

echo ""
echo "Extracting Chromium..."

# Remove old installation if exists
if [ -d "$CHROMIUM_DIR" ]; then
    rm -rf "$CHROMIUM_DIR"
fi

# Extract
unzip -q "$TEMP_ZIP" -d "$VENDOR_DIR"

# Rename to chromium (playwright extracts to 'chrome-linux')
if [ -d "$VENDOR_DIR/chrome-linux" ]; then
    mv "$VENDOR_DIR/chrome-linux" "$CHROMIUM_DIR"
elif [ -d "$VENDOR_DIR/chromium-linux" ]; then
    mv "$VENDOR_DIR/chromium-linux" "$CHROMIUM_DIR"
fi

# Clean up
rm "$TEMP_ZIP"

# Make executable
chmod +x "$CHROMIUM_DIR/chrome"

# Verify
CHROMIUM_BINARY="$CHROMIUM_DIR/chrome"
if [ -f "$CHROMIUM_BINARY" ]; then
    VERSION=$("$CHROMIUM_BINARY" --version 2>/dev/null || echo "unknown")
    SIZE=$(du -sh "$CHROMIUM_DIR" | cut -f1)

    echo ""
    echo "✅ Installation complete!"
    echo ""
    echo "Location: $CHROMIUM_BINARY"
    echo "Version: $VERSION"
    echo "Size: $SIZE"
    echo ""
    echo "✅ This Chromium will be used automatically by MCP server"
    echo "   No configuration needed - it's detected as the first choice"
    echo ""
else
    echo "❌ Installation failed - binary not found"
    exit 1
fi

echo "Test with:"
echo "  python3 tests/demo_visible.py --auto"
echo ""
