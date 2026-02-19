#!/usr/bin/env bash

set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is intended for macOS only."
  exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This script is optimized for Apple Silicon (arm64)."
  echo "Detected architecture: $(uname -m)"
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew not found. Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || true)"

echo "Updating Homebrew..."
brew update

formulae=(
  opentofu
  kubectl
  helm
  k3d
  argocd
  jq
  yq
  k9s
  kubectx
)

for formula in "${formulae[@]}"; do
  if brew list --formula "$formula" >/dev/null 2>&1; then
    echo "Upgrading $formula..."
    brew upgrade "$formula" || true
  else
    echo "Installing $formula..."
    brew install "$formula"
  fi
done

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI not found. Installing Docker Desktop cask..."
  brew install --cask docker
  echo "Please open Docker Desktop once and wait until engine is running."
fi

echo
echo "Installed/updated tools: ${formulae[*]}"
echo "Verify with: tofu -version && kubectl version --client && helm version && k3d version"
