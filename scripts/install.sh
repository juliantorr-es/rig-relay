#!/usr/bin/env bash

# Rig Relay Installation Script
# This script installs uv if not present and then installs rig-relay using uv

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

ORIGINAL_PATH="${PATH}"

function error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

function info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

function success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

function warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

function find_command_in_path() {
    local cmd="$1"
    local path_value="$2"
    PATH="$path_value" command -v "$cmd" 2>/dev/null || true
}

function print_missing_path_instructions() {
    local executable_name="$1"
    local executable_path="$2"
    local bin_dir
    bin_dir=$(dirname "$executable_path")

    warning "Installation completed, and '$executable_name' was installed at: $executable_path"
    error "Your PATH does not include the folder that contains '$executable_name'."
    error "Add this directory to your shell profile, then restart your terminal:"
    error "  export PATH=\"$bin_dir:\$PATH\""
}

function check_platform() {
    local platform=$(uname -s)

    if [[ "$platform" == "Linux" ]]; then
        info "Detected Linux platform"
        PLATFORM="linux"
    elif [[ "$platform" == "Darwin" ]]; then
        info "Detected macOS platform"
        PLATFORM="macos"
    else
        error "Unsupported platform: $platform"
        error "This installation script currently only supports Linux and macOS"
        exit 1
    fi
}

function check_uv_installed() {
    if command -v uv >/dev/null 2>&1; then
        info "uv is already installed: $(uv --version)"
        UV_INSTALLED=true
    else
        info "uv is not installed"
        UV_INSTALLED=false
    fi
}

function install_uv() {
    info "Installing uv using the official Astral installer..."

    if ! command -v curl &> /dev/null; then
        error "curl is required to install uv. Please install curl first."
        exit 1
    fi

    if curl -LsSf https://astral.sh/uv/install.sh | sh; then
        success "uv installed successfully"

        export PATH="$HOME/.local/bin:$PATH"

        if ! command -v uv &> /dev/null; then
            warning "uv was installed but not found in PATH for this session"
            warning "You may need to restart your terminal or run:"
            warning "  export PATH=\"\$HOME/.cargo/bin:\$HOME/.local/bin:\$PATH\""
        fi
    else
        error "Failed to install uv"
        exit 1
    fi
}

function check_rig_relay_installed() {
    if [[ -n "$(find_command_in_path rig-relay "$ORIGINAL_PATH")" ]]; then
        info "rig-relay is already installed"
        RIG_RELAY_INSTALLED=true
        return
    fi

    local uv_bin_dir
    uv_bin_dir=$(uv tool dir --bin 2>/dev/null || true)
    if [[ -n "$uv_bin_dir" && -x "$uv_bin_dir/rig-relay" ]]; then
        info "rig-relay is already installed (off PATH) at $uv_bin_dir/rig-relay"
        RIG_RELAY_INSTALLED=true
        return
    fi

    RIG_RELAY_INSTALLED=false
}

function install_rig_relay() {
    info "Installing rig-relay from GitHub repository using uv..."
    uv tool install "git+https://github.com/juliantorr-es/rig-relay.git"

    success "Rig Relay installed successfully! (commands: rig-relay, rig-relay-acp)"
}

function update_rig_relay() {
    info "Updating rig-relay from GitHub repository using uv..."
    uv tool upgrade rig-relay

    success "Rig Relay updated successfully!"
}

function main() {
    echo
    echo "██████████████████░░"
    echo "██████████████████░░"
    echo "████  ██████  ████░░"
    echo "████    ██    ████░░"
    echo "████          ████░░"
    echo "████  ██  ██  ████░░"
    echo "██      ██      ██░░"
    echo "██████████████████░░"
    echo "██████████████████░░"
    echo
    echo "Starting Rig Relay installation..."
    echo

    check_platform

    check_uv_installed

    if [[ "$UV_INSTALLED" == "false" ]]; then
        install_uv
    fi

    check_rig_relay_installed

    if [[ "$RIG_RELAY_INSTALLED" == "false" ]]; then
        install_rig_relay
    else
        update_rig_relay
    fi

    if [[ -n "$(find_command_in_path rig-relay "$ORIGINAL_PATH")" ]]; then
        success "Installation completed successfully!"
        echo
        echo "You can now run Rig Relay with:"
        echo "  rig-relay"
        echo
        echo "Or for ACP mode:"
        echo "  rig-relay-acp"
    else
        local UV_BIN_DIR
        local RIG_RELAY_BIN_PATH=""
        UV_BIN_DIR=$(uv tool dir --bin 2>/dev/null || true)
        if [[ -n "$UV_BIN_DIR" && -x "$UV_BIN_DIR/rig-relay" ]]; then
            RIG_RELAY_BIN_PATH="$UV_BIN_DIR/rig-relay"
        fi

        if [[ -n "$RIG_RELAY_BIN_PATH" ]]; then
            print_missing_path_instructions "rig-relay" "$RIG_RELAY_BIN_PATH"
        else
            error "Installation completed but 'rig-relay' command not found"
            error "uv did not expose a 'rig-relay' executable in the expected tools directory."
            error "Please check your installation and PATH settings"
        fi
        exit 1
    fi
}

main
