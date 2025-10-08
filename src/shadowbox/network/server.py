"""
LAN file-sharing server:
- Advertises itself with Zeroconf (_shadowbox._tcp.local.)
- Serves a simple line-oriented protocol:
    LIST             -> sends a newline-separated list of filenames, then closes
    GET <filename>   -> streams that file's bytes, then closes

server.py [shared_dir] [port]

Default shared_dir = ./shared_dir
Default port = 60000
"""

import os
import socket
import threading
import time
import sys
from zeroconf import Zeroconf, ServiceInfo

SERVICE_TYPE = "_shadowbox._tcp.local."

def get_local_ip():
    """A trick to get the current IP using a UDP socket."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()
