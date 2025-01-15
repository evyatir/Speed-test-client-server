import socket
import threading
import struct
import time
import queue

# Constants
MAGIC_COOKIE = 0xabcddcba
MESSAGE_TYPE_OFFER = 0x2
MESSAGE_TYPE_REQUEST = 0x3
MESSAGE_TYPE_PAYLOAD = 0x4
MESSAGE_TYPE_ACK = 0x5
BROADCAST_PORT = 13117
BUFFER_SIZE = 1024

# Global queue for UDP requests
udp_request_queue = queue.Queue()


def get_broadcast_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    local_ip = s.getsockname()[0]
    s.close()
    ip_parts = local_ip.split('.')
    return f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.255"


def broadcast_offers(udp_port, tcp_port):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as udp_socket:
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        broadcast_ip = get_broadcast_ip()

        while True:
            try:
                message = struct.pack('!IBHH', MAGIC_COOKIE, MESSAGE_TYPE_OFFER, udp_port, tcp_port)
                udp_socket.sendto(message, (broadcast_ip, BROADCAST_PORT))
                time.sleep(1)
            except Exception as e:
                print(f"[Server] Broadcast error: {e}")


def handle_udp_transfer(udp_socket, client_address, file_size):
    try:
        # Send acknowledgment first
        ack_message = struct.pack('!IB', MAGIC_COOKIE, MESSAGE_TYPE_ACK)
        udp_socket.sendto(ack_message, client_address)

        total_segments = (file_size + BUFFER_SIZE - 1) // BUFFER_SIZE
        segment_data = b"X" * BUFFER_SIZE

        for segment in range(total_segments):
            remaining = min(BUFFER_SIZE, file_size - segment * BUFFER_SIZE)
            header = struct.pack('!IBQQ', MAGIC_COOKIE, MESSAGE_TYPE_PAYLOAD, total_segments, segment)
            packet = header + segment_data[:remaining]

            # Send each packet 3 times to improve reliability
            for _ in range(3):
                udp_socket.sendto(packet, client_address)
                time.sleep(0.001)  # Small delay between retries

        print(f"[Server] Completed UDP transfer to {client_address}")

    except Exception as e:
        print(f"[Server] UDP transfer error to {client_address}: {e}")


def process_udp_requests():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        while True:
            try:
                request = udp_request_queue.get()
                if request:
                    client_address, file_size = request
                    handle_udp_transfer(udp_socket, client_address, file_size)
            except Exception as e:
                print(f"[Server] Error processing UDP request: {e}")


def handle_udp_requests(udp_socket):
    while True:
        try:
            data, client_address = udp_socket.recvfrom(BUFFER_SIZE)
            if len(data) >= 13:  # Minimum packet size
                magic_cookie, message_type, file_size = struct.unpack('!IBQ', data[:13])

                if magic_cookie == MAGIC_COOKIE and message_type == MESSAGE_TYPE_REQUEST:
                    print(f"[Server] New UDP request from {client_address}")
                    udp_request_queue.put((client_address, file_size))

        except Exception as e:
            print(f"[Server] Error receiving UDP request: {e}")


def handle_tcp_connection(client_socket):
    try:
        request = client_socket.recv(BUFFER_SIZE).decode().strip()
        file_size = int(request)

        total_sent = 0
        while total_sent < file_size:
            chunk = b"0" * min(BUFFER_SIZE, file_size - total_sent)
            client_socket.sendall(chunk)
            total_sent += len(chunk)

    except Exception as e:
        print(f"[Server] TCP error: {e}")
    finally:
        client_socket.close()


def start_server():
    print("[Server] Starting...")

    # Initialize sockets
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Set socket options
    tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Bind sockets
    tcp_socket.bind(("", 0))
    udp_socket.bind(("", 0))

    tcp_port = tcp_socket.getsockname()[1]
    udp_port = udp_socket.getsockname()[1]

    print(f"[Server] TCP port: {tcp_port}")
    print(f"[Server] UDP port: {udp_port}")

    # Start threads
    threading.Thread(target=broadcast_offers, args=(udp_port, tcp_port), daemon=True).start()
    threading.Thread(target=handle_udp_requests, args=(udp_socket,), daemon=True).start()
    threading.Thread(target=process_udp_requests, daemon=True).start()

    # Handle TCP connections
    tcp_socket.listen(5)
    while True:
        try:
            client_conn, _ = tcp_socket.accept()
            threading.Thread(target=handle_tcp_connection, args=(client_conn,), daemon=True).start()
        except Exception as e:
            print(f"[Server] TCP accept error: {e}")


if __name__ == "__main__":
    start_server()
