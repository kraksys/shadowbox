"""
Discover a Zeroconf service of type _shadowbox._tcp.local., connect to the advertised
IP:port:

Commands:
  LIST             -> request a newline-separated list of available files (./shared_dir)
  GET <filename>   -> request the given filename
  PUT <local_path> [remote_name] -> upload a local file to the server
  DELETE <filename> -> delete remote file

Usage:
  python client.py [LIST]
  python client.py GET <filename>
  python client.py PUT <local_path> [remote_name]
  python client.py DELETE <filename>
  python client.py BOX <box_name>   -> select the active box for the current session
  python client.py LIST_BOXES       -> list available boxes for the user
  python client.py SHARE_BOX <box_name> <username> [perm] -> share a box
  python client.py LIST_AVAILABLE_USERS -> list users available for sharing
  python client.py LIST_SHARED_BOXES  -> list boxes that have been shared with you

If no arguments given, defaults to LIST.
[still not finished]
"""
import os
import sys
import socket
import time  # not in use so far
import threading
from zeroconf import Zeroconf, ServiceBrowser, ServiceInfo

SERVICE_TYPE = "_shadowbox._tcp.local."
DISCOVER_TIMEOUT = 8.0  # seconds to wait for service discovery
READ_BUF = 4096


class ServiceFinder:
    def __init__(self, service_type=SERVICE_TYPE, timeout=DISCOVER_TIMEOUT):
        self.zeroconf = Zeroconf()  # opens mDNS sockets
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
                        k = k.decode(encoding="utf-8")  # we can change errors="replace" later
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
        s.settimeout(timeout)  # 10s might be too much

        # send request
        if not request_line.endswith("\n"):
            request_line = request_line + "\n"
        s.sendall(request_line.encode())

        if recv_file:
            if not out_path:
                raise ValueError("out_path required when recv_file=True")
            print(f"Receiving file to {out_path} ...")
            with open(out_path, "wb") as f: # this automatically creates a file, but it can't create a directory
                while True:
                    try:
                        chunk = s.recv(
                            8192)  # we can lower to 1024 or READ_BUF (it's TCP so it doesn't matter that much)
                        if not chunk:
                            break
                        if chunk.startswith(b"ERROR: File not found:"):
                            return {"status": "error", "error": f"File not found: {out_path}"}
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
                    parts.append(chunk.decode())  # utf-8
                except Exception:
                    parts.append(str(chunk))
            data = "".join(parts)
            return {"status": "ok", "text": data}


def cmd_list(ip, port):
    res = connect_and_request(ip, port, "LIST")
    if res["status"] == "ok":
        print(res["text"])
    else:
        print("Error:", res)


def cmd_get(ip, port, filename, out_path=None):
    if out_path is None:
        out_path = filename
    res = connect_and_request(ip, port, f"GET {filename}", recv_file=True, out_path=out_path)
    if res["status"] == "ok":
        pass
    else:
        # TODO: find a better way to handle this error
        os.remove(out_path)  # !!! This can delete an existing file, but it'd be a corrupted one so it's fine
    print(res)


def cmd_put(ip, port, local_path, remote_name=None, timeout=60):
    """
    Upload a local file to the server.
    Protocol:
      Client -> "PUT <remote_name> <size>\n"
      Server -> "READY\n"  (or "ERROR: ...\n")
      Client -> exactly <size> bytes
      Server -> final textual reply
    """
    if not os.path.exists(local_path) or not os.path.isfile(local_path):
        print("Local file not found:", local_path)
        return {"status": "error", "error": "local file not found"}

    if remote_name is None:
        # This is like in get we can give a different name of the file saved on the client side,
        # but it saves the file with the given remote name on the server side
        remote_name = os.path.basename(local_path)

    size = os.path.getsize(local_path)

    print(f"Uploading {local_path} -> {ip}:{port} as {remote_name} ({size} bytes)")
    with socket.create_connection((ip, port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(f"PUT {remote_name} {size}\n".encode())

        # wait for READY or ERROR line (single-line response)
        resp = b""
        while not resp.endswith(b"\n"):
            chunk = s.recv(1024)
            if not chunk:
                raise IOError("no response from server")
            resp += chunk
        resp_text = resp.decode().strip()
        if resp_text.upper().startswith("ERROR"):
            print("Server error:", resp_text)
            return {"status": "error", "error": resp_text}

        if not resp_text.upper().startswith("READY"):  # just in case we mess up smth on the server side
            print("Unexpected server response:", resp_text)
            return {"status": "error", "error": resp_text}

        # send file bytes
        with open(local_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                s.sendall(chunk)

        # read final reply (text) until socket closes or timeout
        final = b""
        while True:
            try:
                chunk = s.recv(1024)
            except socket.timeout:
                break
            if not chunk:
                break
            final += chunk

        final_text = final.decode(errors="ignore").strip()
        print("Server reply:", final_text)
        return {"status": "ok", "reply": final_text}


def cmd_delete(ip, port, filename, timeout=30):
    res = connect_and_request(ip, port, f"DELETE {filename}", timeout=timeout)
    if res["status"] == "ok":
        print(res["text"])
        # In case we want to delete the file on the client side too.
        #os.remove(filename)
    else:
        print("Error:", res)
    return res


def cmd_list_boxes(ip, port):
    """Sends the LIST_BOXES command to the server."""
    res = connect_and_request(ip, port, "LIST_BOXES")
    print(res.get("text", res.get("error")).strip())


def cmd_share_box(ip, port, args):
    """Sends the SHARE_BOX command to the server."""
    if len(args) < 2:
        print("Usage: client.py SHARE_BOX <box_name> <username> [permission]")
        return

    box_name, share_with_user = args[0], args[1]
    permission = args[2] if len(args) > 2 else "read"

    request_line = f"SHARE_BOX {box_name} {share_with_user} {permission}"
    res = connect_and_request(ip, port, request_line)
    print(res.get("text", res.get("error")).strip())


def cmd_list_available_users(ip, port):
    """Sends the LIST_AVAILABLE_USERS command to the server."""
    res = connect_and_request(ip, port, "LIST_AVAILABLE_USERS")
    print(res.get("text", res.get("error")).strip())

def cmd_list_shared_boxes(ip, port):
    """Sends the LIST_SHARED_BOXES command to the server."""
    res = connect_and_request(ip, port, "LIST_SHARED_BOXES")
    print(res.get("text", res.get("error")).strip())

def cmd_box(ip, port, namespaced_box):
    """Sends the BOX command to select a box using the 'owner/box_name' format."""
    res = connect_and_request(ip, port, f"BOX {namespaced_box}")
    print(res.get("text", res.get("error")).strip())

def main(argv):
    if len(argv) <= 1:
        cmd = "LIST"
        args = []
    else:
        cmd = argv[1].upper()
        args = argv[2:]

    finder = ServiceFinder()
    try:
        print(f"Searching for Zeroconf services of type {SERVICE_TYPE} (timeout {DISCOVER_TIMEOUT}s)...")
        info = finder.wait_for_service()
        if not info:
            print("No service found within timeout.")
            return 2

        print("Found service:")
        print("  name:", info["name"])
        print("  ip:", info["ip"])
        print("  port:", info["port"])
        print("  properties:", info["properties"])

        ip = info["ip"]
        port = info["port"]

        if cmd == "LIST":
            cmd_list(ip, port)
        elif cmd == "GET":
            if not args:
                print("GET requires a filename: python zeroconf_client.py GET <filename>")
                return 1
            filename = args[0]
            out = args[1] if len(args) >= 2 else None
            cmd_get(ip, port, filename, out_path=out)
        elif cmd == "PUT":
            if not args:
                print("PUT requires a local path: python zeroconf_client.py PUT <local_path> [remote_name]")
                return 1
            local_path = args[0]
            remote_name = args[1] if len(args) >= 2 else None
            cmd_put(ip, port, local_path, remote_name)
        elif cmd == "DELETE":
            if not args:
                print("DELETE requires a filename: python zeroconf_client.py DELETE <filename>")
                return 1
            filename = args[0]
            cmd_delete(ip, port, filename)
        elif cmd == "LIST_BOXES":
            cmd_list_boxes(ip, port)
        elif cmd == "SHARE_BOX":
            cmd_share_box(ip, port, args)
        elif cmd == "LIST_AVAILABLE_USERS":
            cmd_list_available_users(ip, port)
        elif cmd == "LIST_SHARED_BOXES":
            cmd_list_shared_boxes(ip, port)
        elif cmd == "BOX":
            if not args:
                print("Usage: python client.py BOX <owner_username/box_name>")
                print("Example (your own box): python client.py BOX myuser/mybox")
                print("Example (shared box): python client.py BOX otheruser/sharedbox")
                return 1
            namespaced_box = args[0]
            cmd_box(ip, port, namespaced_box)
        else:
            print("Unknown command:", cmd)
            return 1

    finally:
        finder.close()

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
