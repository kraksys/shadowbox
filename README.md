README

# ShadowBox

GitHub: https://github.com/kraksys/shadowbox
License: 


# What is ShadowBox
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

Go into your terminal and cd to the shadowbox-main folder's directory. Once you're there, run pip install -r requirement.txt.


# Usage
To start the application, run the following command from the project's root (shadowbox-main\shadowbox-main\src):
python -m shadowbox.frontend.cli.app


Keyboard Shortcuts (Cheat Sheet)
This cheat sheet is also provided in the software itself by pressing CTRL + P and clicking on the Keys bar with every key functionality (which is more than the sheet that is provided here). The interface is designed to be navigated quickly using the keyboard. 

Key	Action	Description
n	New Box	Create a new isolated storage container (Box).
a	Add File	Import a file from your system into the active Box.
s	Share Box	Broadcast the current Box to the LAN (Host Mode).
c	Connect	Connect to a peer's Box using a 4-letter code (Client Mode).
d	Delete	Soft-delete the selected file or Box.
/	Search	Open the live fuzzy search bar.
t	Filter Tags	Filter the current file list by a specific tag.
v	Versions	View and restore historical versions of a file.
e	Edit	Edit file description or tags.
        enter	Download	Export/Download the selected file to a local path.
q	Quit	Safely stop all servers and exit.

How Sharing Works

The host can create a Box or use the default provided Box.
The Host then selects a Box and presses s.
ShadowBox generates a random 4-letter code (e.g., ABCD) and starts a local TCP server.
The service _shadowboxabcd._tcp.local is broadcast.
The Client presses c or clicks on the desired box in the Public Box space and enters ABCD.
The Client resolves the Host's IP automatically and establishes a direct, secure TCP stream to download files.

# Visuals:

<img width="862" height="457" alt="image" src="https://github.com/user-attachments/assets/9725fe56-cdd4-454a-9891-b8eb2b7bd228" />
<img width="1728" height="917" alt="image" src="https://github.com/user-attachments/assets/ca887953-db96-4d44-92e9-ca0e8bee98ce" />
<img width="1730" height="923" alt="image" src="https://github.com/user-attachments/assets/d5265787-c4a1-4caf-9df9-a9c31d5bb9f6" />
<img width="1700" height="920" alt="image" src="https://github.com/user-attachments/assets/9ba27914-af01-43ef-a05b-9dd64ada9bd5" />
<img width="866" height="452" alt="image" src="https://github.com/user-attachments/assets/270977cc-e585-42ae-9875-181b59a1f8cf" />
<img width="1724" height="919" alt="image" src="https://github.com/user-attachments/assets/c1f77dd6-43da-42a7-a6e8-6656e24dea70" />
<img width="1736" height="926" alt="image" src="https://github.com/user-attachments/assets/24908249-76fb-4d90-b457-478e526b61ac" />
<img width="1730" height="919" alt="image" src="https://github.com/user-attachments/assets/23996680-42c4-4c7e-be9a-3f32f4a9cf8a" />







# Testing & Quality
The project includes a comprehensive test suite covering all modules.

To run the tests:
pytest
To view coverage reports:
pytest --cov=shadowbox


# Authors
Stavros Valsamis, Maxim Dmitrievich, Matthieu Klopp, Atanas Malinkov, Patrik Levak & Ahmed Al Kurwi.
Software Development Course (Fall/Winter 2025)

# Project status
Project finished, development stopped
