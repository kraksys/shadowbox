
"""
Discover a Zeroconf service of type _shadowbox._tcp.local., connect to the advertised
IP:port:

Commands:
  LIST             -> request a newline-separated list of available files (./shared_dir)
  GET <filename>   -> request the given filename

Usage:
  python zeroconf_client.py [LIST]
  python zeroconf_client.py GET <filename>

If no arguments given, defaults to LIST.
[still not finished]
"""

import sys
import socket
import time # not in use so far
import threading
from zeroconf import Zeroconf, ServiceBrowser, ServiceInfo

SERVICE_TYPE = "_shadowbox._tcp.local."
DISCOVER_TIMEOUT = 8.0  # seconds to wait for service discovery
READ_BUF = 4096

class ServiceFinder:
    def __init__(self, service_type=SERVICE_TYPE, timeout=DISCOVER_TIMEOUT):
        self.zeroconf = Zeroconf() # opens mDNS sockets
        self.service_type = service_type
        self.found_info = None
        self._found_event = threading.Event()
        self._timeout = timeout
        # Zeroconf will call _on_service_event when services are added/removed/updated
        self.browser = ServiceBrowser(self.zeroconf, self.service_type, handlers=[self._on_service_event])

    def _on_service_event(self, zeroconf, service_type, name, state_change=None):
        """
        Called by ServiceBrowser for added/removed/updated services.
        We attempt to resolve the service info and set it as found.
        """
        pass

