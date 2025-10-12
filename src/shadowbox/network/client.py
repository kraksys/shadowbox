
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
        Works with IPv4 and IPv6.
        """
        pass
        # We only care when a service is added (or updated) and we haven't already resolved one.
        if self._found_event.is_set():
            return

        try:
            info = zeroconf.get_service_info(service_type, name, timeout=2000)  # 2s blocking resolve
            if info:
                # prefer IPv4 if present; fall back to first address
                ip = None
                if info.addresses:
                    # detect IPv4 vs IPv6 by length of packed address
                    for packed in info.addresses:
                        if len(packed) == 4:  # IPv4
                            # Convert an IP address from 32-bit packed binary format to string format
                            ip = socket.inet_ntoa(packed)
                            break
                    if ip is None:
                        # take the first address (likely IPv6) and convert
                        try:
                            ip = socket.inet_ntop(socket.AF_INET6, info.addresses[0])
                        except Exception:
                            ip = None

                port = info.port
                props = {}
                for k, v in (info.properties or {}).items():
                    # keys are bytes in many zeroconf versions; decode if necessary
                    if isinstance(k, bytes):
                        k = k.decode(encoding="utf-8") # we can change errors="replace" later
                    if isinstance(v, bytes):
                        try:
                            v = v.decode(encoding="utf-8")
                        except Exception:
                            # keep raw bytes if cannot decode
                            pass
                    props[k] = v

                if ip:
                    self.found_info = {
                        "name": name,
                        "ip": ip,
                        "port": port,
                        "properties": props
                    }
                    self._found_event.set()
        except Exception as e:
            # ignore transient resolution errors
            # like dropped or delayed mDNS packets
            print(f"Transient resolution error: {e}")
            pass

    def wait_for_service(self):
        got = self._found_event.wait(self._timeout)
        if not got:
            return None
        return self.found_info

    def close(self):
        try:
            self.zeroconf.close()
        except Exception:
            pass


def connect_and_request(ip, port, request_line, recv_file=False, out_path=None, timeout=10):
    """
    Connect to ip:port, send a single request_line (ending with '\n'), and either:
      - if recv_file==False: read until the remote closes or a blank line and print text
      - if recv_file==True: stream bytes to out_path until remote closes
    """
    print(f"Connecting to {ip}:{port} ...")
    with socket.create_connection((ip, port), timeout=timeout) as s:
        s.settimeout(timeout) # 10s might be too much

        # send request
        if not request_line.endswith("\n"):
            request_line = request_line + "\n"
        s.sendall(request_line.encode())

        if recv_file:
            if not out_path:
                raise ValueError("out_path required when recv_file=True")
            print(f"Receiving file to {out_path} ...")
            with open(out_path, "wb") as f:
                while True:
                    try:
                        chunk = s.recv(8192) # we can lower to 1024 or READ_BUF (it's TCP so it doesn't matter that much)
                        if not chunk:
                            break
                        f.write(chunk)
                    except socket.timeout:
                        print("Socket timeout while receiving.")
                        break
            print("File receive complete.")
            return {"status": "ok", "saved_to": out_path}
        else:
            # read textual response until socket closes (or timeout)
            parts = []
            while True:
                try:
                    chunk = s.recv(READ_BUF)
                except socket.timeout:
                    # treat timeout as end of response
                    break
                if not chunk:
                    break
                try:
                    parts.append(chunk.decode()) # utf-8
                except Exception:
                    parts.append(str(chunk))
            data = "".join(parts)
            return {"status": "ok", "text": data}


def main(argv):
    if len(argv) <= 1:
        cmd = "LIST"
        args = []
    else:
        cmd = argv[1].upper()
        args = argv[2:] # after python server.py GET

    finder = ServiceFinder()
    try:
        print(f"Searching for Zeroconf services of type {SERVICE_TYPE} (timeout {DISCOVER_TIMEOUT}s)...")
        info = finder.wait_for_service()
        if not info:
            print("No service found within timeout.")
            return 420

        print("Found service:")
        print("  name:", info["name"])
        print("  ip:", info["ip"])
        print("  port:", info["port"])
        print("  properties:", info["properties"])

        if cmd == "LIST":
            res = connect_and_request(info["ip"], info["port"], "LIST")
            if res["status"] == "ok":
                print("Server response (LIST):")
                print(res["text"])
            else:
                print("Error:", res)
        elif cmd == "GET":
            if not args:
                print("GET requires a filename: python client.py GET <filename>")
                return 69
            filename = args[0]
            # We assume server will stream file bytes directly in response to "GET <filename>\n".
            out_path = filename  # save with same name locally
            res = connect_and_request(info["ip"], info["port"], f"GET {filename}", recv_file=True, out_path=out_path)
            print(res)
        else:
            print("Unknown command:", cmd)
            return 69

    finally:
        finder.close()

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
