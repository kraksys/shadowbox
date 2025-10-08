"""
LAN file-sharing server:
- Advertises itself with Zeroconf (_shadowbox._tcp.local.)
- Serves a simple line-oriented protocol:
    LIST             -> sends a newline-separated list of filenames, then closes
    GET <filename>   -> streams that file's bytes, then closes

server.py [shared_dir] [port]

Default shared_dir = ./shared_dir
Default port = 9999
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

def handle_client(conn, addr, shared_dir):
    """Handle a single client connection."""
    print(f"[+] Connection from {addr}")
    conn.settimeout(10.0) # The idea is to open a new connection for every action so 10s is enough
    try:
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(1024)
            if not chunk:
                break
            data += chunk
        line = data.decode().strip()
        print(f"Received command: {line} from {addr}")

        if line.upper() == "LIST":
            files = os.listdir(shared_dir)
            response = "\n".join(files) + "\n"
            conn.sendall(response.encode())
            print(f"Sent file list ({len(files)} entries)")
        elif line.upper().startswith("GET "):
            _, filename = line.split(" ", 1)
            filepath = os.path.join(shared_dir, filename)
            if not os.path.isfile(filepath):
                msg = f"ERROR: File not found: {filename}\n"
                conn.sendall(msg.encode())
                print(f"File not found: {filename}")
            else:
                with open(filepath, "rb") as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        conn.sendall(chunk)
                print(f"Sent file: {filename}")
        else:
            msg = "ERROR: Unknown command\n"
            conn.sendall(msg.encode())

    except socket.timeout:
        print(f"Timeout from {addr}")
    except Exception as e:
        print(f"Error handling {addr}: {e}")
    finally:
        conn.close()
        print(f"[-] Disconnected {addr}")

def start_tcp_server(shared_dir, port):
    """Start a simple threaded TCP server."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", port))
    s.listen(5)
    print(f"TCP server listening on port {port}, serving '{shared_dir}'")
    while True:
        conn, addr = s.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr, shared_dir), daemon=True)
        t.start()


# Zeroconf advertisement
def advertise_service(name, port):
    """Advertise this server using Zeroconf."""
    zeroconf = Zeroconf()
    local_ip = get_local_ip()
    local_ip_bytes = socket.inet_aton(local_ip)
    props = {"name": name, "version": "1.0"}

    info = ServiceInfo(
        SERVICE_TYPE,
        f"{name}.{SERVICE_TYPE}",
        addresses=[local_ip_bytes],
        port=port,
        properties=props,
        server=f"{socket.gethostname()}.local.",
    )
    zeroconf.register_service(info)
    print(f"Zeroconf service registered: {name} @ {local_ip}:{port}")
    return zeroconf, info


# Main entry point
def main():
    shared_dir = sys.argv[1] if len(sys.argv) > 1 else "./shared_dir"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9999
    name = f"FileServer-{socket.gethostname()}"

    if not os.path.exists(shared_dir):
        # This will make a new empty dir if we give it a non-existent one
        # We may need to remove this, because it can cause us issues in the future
        os.makedirs(shared_dir)

    zeroconf, info = advertise_service(name, port)

    try:
        start_tcp_server(shared_dir, port)
    except KeyboardInterrupt: # we can trigger this only while the server is starting
        print("\nShutting down...")
    finally:
        print("Unregistering Zeroconf service...")
        zeroconf.unregister_service(info)
        zeroconf.close()


if __name__ == "__main__":
    main()
