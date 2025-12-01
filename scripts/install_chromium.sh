#!/bin/bash
# Install proper Chromium (non-snap) for browser automation

set -e

echo "============================================"
echo "Chromium Installation Helper"
echo "============================================"
echo ""
echo "⚠️  WARNING: Snap Chromium has issues:"
echo "  - Ignores --user-data-dir"
echo "  - Blocks extensions with SingletonLock"
echo "  - Causes profile conflicts"
echo ""
echo "This script installs NON-SNAP Chromium"
echo ""

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo "❌ Cannot detect OS"
    exit 1
fi

echo "Detected OS: $OS"
echo ""

case $OS in
    ubuntu|debian|pop)
        echo "Installing Chromium from official repositories..."
        echo ""

        # Remove snap version if present
        if snap list chromium 2>/dev/null; then
            echo "⚠️  Removing snap Chromium..."
            sudo snap remove chromium
        fi

        # Install from apt
        sudo apt update
        sudo apt install -y chromium-browser chromium-chromedriver

        BINARY="/usr/bin/chromium-browser"
        ;;

    arch|manjaro)
        echo "Installing Chromium from official repositories..."
        echo ""

        sudo pacman -S --noconfirm chromium

        BINARY="/usr/bin/chromium"
        ;;

    fedora|rhel|centos)
        echo "Installing Chromium from official repositories..."
        echo ""

        sudo dnf install -y chromium

        BINARY="/usr/bin/chromium-browser"
        ;;

    *)
        echo "❌ Unsupported OS: $OS"
        echo ""
        echo "Manual installation:"
        echo "  1. Install Chromium from your package manager (NOT snap)"
        echo "  2. Set MCP_BROWSER_BINARY=/path/to/chromium"
        echo ""
        exit 1
        ;;
esac

echo ""
echo "✅ Installation complete!"
echo ""
echo "Chromium binary: $BINARY"

# Verify
if [ -f "$BINARY" ]; then
    VERSION=$("$BINARY" --version 2>/dev/null || echo "unknown")
    echo "Version: $VERSION"
    echo ""
    echo "✅ Ready to use!"
    echo ""
    echo "Export to use:"
    echo "  export MCP_BROWSER_BINARY=$BINARY"
    echo ""
    echo "Or add to ~/.bashrc:"
    echo "  echo 'export MCP_BROWSER_BINARY=$BINARY' >> ~/.bashrc"
else
    echo "❌ Binary not found at $BINARY"
    echo "Please check installation manually"
    exit 1
fi

echo ""
echo "Test with:"
echo "  python3 tests/test_extension.py"
