README

# ShadowBox

GitHub: https://github.com/kraksys/shadowbox

License: MIT https://github.com/kraksys/shadowbox/blob/main/LICENSE


# What is ShadowBox?
ShadowBox is a local-first, privacy-focused file-sharing and storage application. It allows you to organize files in secure, isolated Boxes and share them directly with peers on your local network (LAN) without relying on cloud providers or external internet access.
Built with a robust Text User Interface (TUI), ShadowBox runs entirely in your terminal, offering a lightweight, keyboard-driven experience for secure data management.

# Features
1. Secure Storage: Files are stored locally using AES-GCM encryption. Keys are derived using Argon2id and managed via a secure session manager with auto-lock capabilities.
2. Peer-to-Peer Sharing: Broadcast "Boxes" to your local network. No IP addresses required, just share a 4-letter code.
3. Smart Management: Automatic deduplication (SHA-256), metadata extraction, and file versioning (snapshots).
4. Full-Text Search: Instantly find files by name, description, or tags.
5. Modern TUI: A responsive terminal interface built with Textual, featuring mouse support and keyboard shortcuts, with a list of commands.

# Installation

## Prerequisites
- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) - Fast Python package installer and resolver
- An active Local Area Network (Wi-Fi or Ethernet) is required for sharing features

## Installing uv
If you don't have `uv` installed, install it using one of these methods:

**macOS and Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**With pip:**
```bash
pip install uv
```

## Setup Steps

1. Download or clone the repository:
```bash
git clone https://github.com/kraksys/shadowbox.git
cd shadowbox
```

2. Sync dependencies using `uv`:
```bash
uv sync
```

This will automatically:
- Create a virtual environment
- Install all required dependencies from `pyproject.toml`
- Set up the development environment

# Usage

## Running the TUI Application

To start the ShadowBox Text User Interface:

```bash
uv run python main.py
```

Or using the module path:
```bash
uv run python -m shadowbox.frontend.cli.app
```

The application will launch in your terminal with the interactive TUI.

Notes: if the uv commands does not work, try putting ```bash python -m ``` before any of the commands (it might be because your executable tools folder is not in your computers PATH).

## Keyboard Shortcuts (Cheat Sheet)
This cheat sheet is also provided in the software itself by pressing `CTRL + P` and clicking on the Keys bar with every key functionality (which is more than the sheet that is provided here). The interface is designed to be navigated quickly using the keyboard.

| Key   | Action        | Description                                                     |
|------:|---------------|-----------------------------------------------------------------|
| n     | New Box       | Create a new isolated storage container (Box).                  |
| a     | Add File      | Import a file from your system into the active Box.             |
| s     | Share Box     | Broadcast the current Box to the LAN (Host Mode).               |
| c     | Connect       | Connect to a peer's Box using a 4-letter code (Client Mode).    |
| d     | Delete        | Soft-delete the selected file or Box.                           |
| /     | Search        | Open the live fuzzy search bar.                                  |
| t     | Filter Tags   | Filter the current file list by a specific tag.                 |
| v     | Versions      | View and restore historical versions of a file.                |
| e     | Edit          | Edit file description or tags.                                  |
| g     | Download      | Export/Download the selected file to a local path.              |
| q     | Quit          | Safely stop all servers and exit.                               |

## How Sharing Works

The host can create a Box or use the default provided Box.
On an initial setup (with no shadowbox.db present in the pwd - the user will be prompted for a new one) 

- The Host selects a Box and presses `s` and choses to publicly or privately host the box.
- If the Host hosted a private box ShadowBox generates a random 4-letter code (e.g., `ABCD`) and starts a local TCP server.
- The service `_shadowboxabcd._tcp.local` is broadcast.
- The Client presses `c` or clicks the desired Box in the Public Box space and enters `ABCD`.
- The Client resolves the Host's IP automatically and establishes a direct, secure TCP stream to download files.
- If the Host choses to publicly host the box then everyone on the same network can access the box immediately.

# Importing Kaggle Datasets

ShadowBox includes a utility to import and test the WikiBooks dataset from Kaggle for testing and demonstration purposes.

## Downloading the Dataset

1. Visit the [WikiBooks Dataset on Kaggle](https://www.kaggle.com/datasets/dhruvildave/wikibooks-dataset)
2. Download `wikibooks.zip` (approx. 1.8 GB)
3. Place the downloaded file in the `kaggle/` directory of your ShadowBox installation

## Running the Import Script

Import WikiBooks data into ShadowBox using the following command:

```bash
uv run python scripts/import_kaggle_datasets.py kaggle/wikibooks.zip --limit 50 --username yourname
```

### Available Options:

```bash
uv run python scripts/import_kaggle_datasets.py <dataset_path> [options]

Options:
  --db DB_PATH           Path to ShadowBox database (default: shadowbox.db)
  --storage-root PATH    Storage directory (default: storage)
  --lang LANG           Language table to import (default: en)
  --username USER       Owner of imported box (default: datasets)
  --box-name NAME       Box name (default: wikibooks-<lang>)
  --batch-size N        Default batch size (default: 100)
  --limit N             Maximum entries to import
```

### Example: Import 100 English WikiBooks entries

```bash
uv run python scripts/import_kaggle_datasets.py kaggle/wikibooks.zip \
  --lang en \
  --limit 100 \
  --username my-datasets \
  --box-name wikibooks-demo
```
PLEASE NOTE: 
If you do not submit the username flag, then the default datasets flag will not be visible when you run the application in its default user behavior (as it takes the username from your local system). 

Therefore, it's recommended to run the command with the username flag to properly evaluate the results. 

The script will:
1. Extract the SQLite database from the zip file
2. Create a box named `wikibooks-demo` (or your specified name)
3. Import the specified number of WikiBooks entries as text files
4. Tag all files with `wikibooks` and the language code

# Testing & Quality

The project includes a comprehensive test suite covering all modules.

## Running Tests

Run the full test suite:
```bash
uv run pytest
```

Run tests with coverage report:
```bash
uv run pytest --cov=shadowbox
```

Run tests with detailed coverage HTML report:
```bash
uv run pytest --cov=shadowbox --cov-report=html
```

View the HTML coverage report by opening `htmlcov/index.html` in your browser.

## Running Specific Tests

Run tests for a specific module:
```bash
uv run pytest tests/unit/test_filesystem.py
```

Run tests matching a pattern:
```bash
uv run pytest -k "test_encryption"
```

Run with verbose output:
```bash
uv run pytest -v
```

# Running with Docker

ShadowBox can be run in a Docker container for isolated deployment.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed on your system

## Using Docker Directly

1. Build the Docker image from the project root:
```bash
docker build -t shadowbox:latest -f docker/Dockerfile .
```

2. Run the container with host networking (required for LAN discovery):
```bash
docker run -it --rm \
  --network host \
  -v $(pwd)/docker/shdwbx/data:/shdwbx/data \
  -e TERM=xterm-256color \
  -e COLORTERM=truecolor \
  shadowbox:latest
```

### Docker Run Options Explained:

- `-it`: Interactive mode with TTY (required for TUI)
- `--rm`: Remove container after exit
- `--network host`: Use host networking for mDNS/Zeroconf discovery
- `-v`: Mount volume for persistent data storage
- `-e TERM`: Set terminal type for proper rendering
- `-e COLORTERM`: Enable true color support

## Data Persistence

Data is persisted in the `docker/shdwbx/data` directory on your host machine. This includes:
- SQLite database (`shadowbox.db`)
- File storage
- Encryption keys

To backup your data, simply copy the `docker/shdwbx/data` directory.

## Network Requirements

The container uses `network_mode: "host"` to enable:
- Zeroconf/mDNS service discovery on the LAN
- Direct peer-to-peer connections
- Port 9999 for file sharing

### Notes 

- Host networking is required for LAN features to work properly. Without it, service discovery and peer connections will fail.

- The usage of a color terminal emulator (such as xterm) is recommended to properly run the application. Specifically when running from an IDE terminal, terminal emulation has to be enabled (e.g. within PyCharm)

# Visuals:
(blurred out the IP address)
<img width="1277" height="760" alt="image" src="https://github.com/user-attachments/assets/3ad2f27b-c3a6-410a-87e9-54e4b5b983b8" />
<img width="2554" height="1524" alt="image" src="https://github.com/user-attachments/assets/9e553e89-d839-44e8-84f1-358ad6232699" />
<img width="2559" height="1520" alt="image" src="https://github.com/user-attachments/assets/9f5e4dfa-b236-4bdd-b038-c6b20b5edc53" />
<img width="2559" height="1520" alt="image" src="https://github.com/user-attachments/assets/b4c4bc91-e227-496a-9aad-a91b8bc7a56e" />
<img width="2559" height="1520" alt="image" src="https://github.com/user-attachments/assets/1ec1723e-efd7-40f8-8493-ac82a6c6c565" />
<img width="2554" height="1519" alt="image" src="https://github.com/user-attachments/assets/f14c20e6-2e26-4264-bee8-b2af673458ff" />
<img width="2559" height="1521" alt="image" src="https://github.com/user-attachments/assets/c73eac7d-044b-4281-b05f-1f1394744ef4" />
<img width="1279" height="761" alt="image" src="https://github.com/user-attachments/assets/d8241838-4980-4b01-ab45-d2c502843944" />
<img width="1279" height="761" alt="image" src="https://github.com/user-attachments/assets/776615ea-dbff-43a0-88d4-0051a294e55c" />
<img width="1280" height="764" alt="image" src="https://github.com/user-attachments/assets/bf2a1c07-736a-4d27-ad76-cd8fa4e0a376" />
<img width="2557" height="1520" alt="Screenshot 2025-12-13 233958" src="https://github.com/user-attachments/assets/5ee47612-8d2d-45c8-8306-b335268246df" />
<img width="2559" height="1519" alt="Screenshot 2025-12-13 234038" src="https://github.com/user-attachments/assets/72be3d13-944c-4dd5-82a3-2b4015aa793e" />
<img width="2559" height="1518" alt="Screenshot 2025-12-13 234133" src="https://github.com/user-attachments/assets/b095fdd5-9bbb-47eb-9625-daf5457315d6" />

# Architecture

For detailed technical documentation, see the state machine diagrams in the `docs/` directory:
- [Network State Machine](docs/NetworkStateMachineDiagram.png) - Server/client protocol flows
- [Frontend State Machine](docs/FrontendStateMachineDiagram.png) - TUI application states
- [Encryption State Machine](docs/EncryptionStateMachineDiagram.png) - Cryptographic key lifecycle

# Authors
Stavros Valsamis, Maxim Dmitrievich, Matthieu Klopp, Atanas Malinkov, Patrik Levak & Ahmed Al Kurwi.

Software Development Course (Fall/Winter 2025)




