README

# ShadowBox

GitHub: https://github.com/kraksys/shadowbox

License: 


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
Prerequisites
Python 3.12 or higher.
An active Local Area Network (Wi-Fi or Ethernet) is required for sharing features.
Setup Steps

Install the zip file from the GitHub page and extract it anywhere you want (preferably easy to find). 
Now you need to install the dependencies:

Go into your terminal and cd to the shadowbox-main folder's directory. Once you're there, run `pip install -r requirement.txt.`


# Usage
To start the application, run the following command from the project's root (`shadowbox-main\shadowbox-main\src`):
`python -m shadowbox.frontend.cli.app`


Keyboard Shortcuts (Cheat Sheet)
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

How Sharing Works

The host can create a Box or use the default provided Box.

- The Host selects a Box and presses `s`.
- ShadowBox generates a random 4-letter code (e.g., `ABCD`) and starts a local TCP server.
- The service `_shadowboxabcd._tcp.local` is broadcast.
- The Client presses `c` or clicks the desired Box in the Public Box space and enters `ABCD`.
- The Client resolves the Host's IP automatically and establishes a direct, secure TCP stream to download files.

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








# Testing & Quality
The project includes a comprehensive test suite covering all modules.

To run the tests:
`pytest`
To view coverage reports:
`pytest --cov=shadowbox`


# Authors
Stavros Valsamis, Maxim Dmitrievich, Matthieu Klopp, Atanas Malinkov, Patrik Levak & Ahmed Al Kurwi.

Software Development Course (Fall/Winter 2025)

# Project status
Project finished, development stopped

