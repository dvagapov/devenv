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
  docker
  colima
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

## Start Colima if not already running (2 CPUs, 4 GB RAM, 60 GB disk)
if command -v colima >/dev/null 2>&1; then
  if ! colima status >/dev/null 2>&1; then
    echo "Starting Colima VM (4 CPU, 8 GB RAM, 60 GB disk)..."
    colima start --cpu 4 --memory 8 --disk 60 --arch aarch64 --vm-type vz --network-address
    echo "Colima started."
  else
    echo "Colima is already running."
  fi
fi

echo
echo "Installed/updated tools: ${formulae[*]}"
echo "Verify with: tofu -version && kubectl version --client && helm version && k3d version"
