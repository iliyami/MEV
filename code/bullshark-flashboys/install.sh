echo 'export PATH=$PATH:~/.local/bin' >> ~/.bashrc

set -e

echo "[INFO] Detecting OS..."
OS="$(uname -s)"

if [ "$OS" = "Darwin" ]; then
	echo "[INFO] Detected macOS. Using Homebrew for dependencies."
	# Check for Homebrew
	if ! command -v brew >/dev/null 2>&1; then
		echo "[INFO] Homebrew not found. Installing Homebrew..."
		/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
		eval "$($(brew --prefix)/bin/brew shellenv)"
	fi
	brew update
	brew install cmake clang tmux wget
	# Install Rust
	if ! command -v rustup >/dev/null 2>&1; then
		echo "[INFO] Installing Rust..."
		curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
		source $HOME/.cargo/env
	fi
	rustup default stable
	# Install pip for python3
	if ! command -v pip3 >/dev/null 2>&1; then
		echo "[INFO] Installing pip3..."
		wget https://bootstrap.pypa.io/get-pip.py
		python3 get-pip.py --user
		rm -f get-pip.py
	fi
	# Add ~/.local/bin to PATH in .zshrc if not present
	if ! grep -q 'export PATH=.*\.local/bin' ~/.zshrc 2>/dev/null; then
		echo 'export PATH="$PATH:$HOME/.local/bin"' >> ~/.zshrc
		echo "[INFO] Added ~/.local/bin to PATH in ~/.zshrc"
	fi
elif [ "$OS" = "Linux" ]; then
	echo "[INFO] Detected Linux. Using apt-get for dependencies."
	sudo apt-get update
	sudo apt-get -y upgrade
	sudo apt-get -y autoremove
	sudo apt-get -y install build-essential cmake clang tmux wget python3-full python3-pip pipx
	# Install Rust
	if ! command -v rustup >/dev/null 2>&1; then
		echo "[INFO] Installing Rust..."
		curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
		source $HOME/.cargo/env
	fi
	rustup default stable
	# Handle pip installation for externally managed environments
	if ! command -v pip3 >/dev/null 2>&1; then
		echo "[INFO] Installing pip3..."
		# Try pipx first (recommended for externally managed environments)
		if command -v pipx >/dev/null 2>&1; then
			echo "[INFO] Using pipx for Python package management (recommended for externally managed environments)"
			pipx ensurepath
		else
			# Fallback: Try manual pip installation with proper handling
			wget https://bootstrap.pypa.io/get-pip.py
			if python3 get-pip.py --user 2>/dev/null; then
				echo "[INFO] pip3 installed successfully"
			else
				echo "[WARNING] Standard pip installation failed (externally managed environment)"
				echo "[INFO] Trying with --break-system-packages flag..."
				python3 get-pip.py --user --break-system-packages || {
					echo "[ERROR] Failed to install pip. Please install Python packages using:"
					echo "  - System packages: sudo apt install python3-<package>"
					echo "  - Virtual environments: python3 -m venv myenv && source myenv/bin/activate"
					echo "  - pipx for applications: pipx install <package>"
				}
			fi
			rm -f get-pip.py
		fi
	fi
	# Add ~/.local/bin to PATH in .bashrc if not present
	if ! grep -q 'export PATH=.*\.local/bin' ~/.bashrc 2>/dev/null; then
		echo 'export PATH="$PATH:$HOME/.local/bin"' >> ~/.bashrc
		echo "[INFO] Added ~/.local/bin to PATH in ~/.bashrc"
	fi
else
	echo "[ERROR] Unsupported OS: $OS"
	exit 1
fi

echo "[INFO] Dependency installation complete. Please restart your shell or source your shell config file."