import socket
import threading
import struct
import time

# Constants
MAGIC_NUMBER = 0xabcddcba  # Unique identifier for packet validation
OFFER_MSG_TYPE = 0x2  # Message type for "server offer"
REQUEST_MSG_TYPE = 0x3  # Message type for "client request"
PAYLOAD_MSG_TYPE = 0x4  # Message type for "data payload"
BROADCAST_PORT = 13117  # Port for broadcasting
BUFFER_SIZE = 4096  # Data chunk size for transfers


class Server:
    def __init__(self):
        self.udp_socket = None
        self.tcp_socket = None
        self.server_ip = None
        self.tcp_port = None
        self.udp_port = None

    def get_broadcast_ip(self):
        """
        Automatically determine the broadcast IP address for the current network.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))  # Connect to a public DNS server to obtain the local IP
        local_ip = s.getsockname()[0]
        s.close()

        # Calculate the broadcast address using the local network IP
        ip_parts = local_ip.split('.')
        broadcast_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.255"  # Assumes /24 subnet mask
        return broadcast_ip

    def send_server_offers(self, udp_port, tcp_port):
        """
        Continuously broadcast messages indicating server availability.
        Args:
            udp_port (int): The UDP port used for client communication.
            tcp_port (int): The TCP port used for client communication.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as udp_socket:
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

            broadcast_ip = self.get_broadcast_ip()  # Automatically determine the broadcast IP
            while True:
                try:
                    message = struct.pack('!IBHH', MAGIC_NUMBER, OFFER_MSG_TYPE, udp_port, tcp_port)
                    udp_socket.sendto(message, (broadcast_ip, BROADCAST_PORT))
                    print(f"[Server] Broadcasting availability on UDP Port {udp_port}, TCP Port {tcp_port}")
                    time.sleep(1)
                except Exception as e:
                    print(f"[Server] Error while broadcasting offer: {e}")

    def handle_tcp_request(self, client_socket):
        """
        Handle a single TCP connection, transferring data in chunks.
        Args:
            client_socket (socket): The client’s socket for the connection.
        """
        try:
            request = client_socket.recv(BUFFER_SIZE).decode().strip()
            file_size = int(request)
            print(f"[Server] Received TCP request for {file_size} bytes.")

            total_sent = 0
            while total_sent < file_size:
                chunk = b"0" * min(BUFFER_SIZE, file_size - total_sent)
                client_socket.sendall(chunk)
                total_sent += len(chunk)

            print(f"[Server] Successfully sent {file_size} bytes via TCP.")
        except Exception as e:
            print(f"[Server] TCP connection error: {e}")
        finally:
            client_socket.close()

    def handle_udp_request(self, udp_socket, client_address, file_size):
        """
        Handle a UDP request, sending data in multiple segments.
        Args:
            udp_socket (socket): The UDP socket used for communication.
            client_address (tuple): Client’s address (IP, port).
            file_size (int): The total size of the requested data.
        """
        total_segments = file_size // BUFFER_SIZE + (1 if file_size % BUFFER_SIZE != 0 else 0)
        try:
            for i in range(total_segments):
                # Prepare and send each data segment
                segment = struct.pack('!IBQQ', MAGIC_NUMBER, PAYLOAD_MSG_TYPE, total_segments, i + 1) + b"X" * BUFFER_SIZE
                udp_socket.sendto(segment, client_address)
                time.sleep(0.001)  # Simulate network delay between packets
            print(f"[Server] Sent {total_segments} UDP segments to {client_address}.")
        except Exception as e:
            print(f"[Server] Error in UDP communication: {e}")

    def initialize_server(self):
        """
        Initialize the server to broadcast availability, listen for client requests, and process connections.
        """
        print("[Server] Initializing...")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:

            tcp_socket.bind(("", 0))
            udp_socket.bind(("", 0))

            self.server_ip = socket.gethostbyname(socket.gethostname())
            self.tcp_port = tcp_socket.getsockname()[1]
            self.udp_port = udp_socket.getsockname()[1]

            print(f"[Server] Server initialized, listening on IP {self.server_ip}")
            print(f"[Server] TCP connection open on port {self.tcp_port}.")
            print(f"[Server] UDP connection open on port {self.udp_port}.")

            threading.Thread(target=self.send_server_offers, args=(self.udp_port, self.tcp_port), daemon=True).start()

            tcp_socket.listen(5)
            while True:
                client_conn, _ = tcp_socket.accept()
                threading.Thread(target=self.handle_tcp_request, args=(client_conn,), daemon=True).start()

                data, client_address = udp_socket.recvfrom(BUFFER_SIZE)
                try:
                    magic_number, msg_type, file_size = struct.unpack('!IBQ', data)
                    if magic_number == MAGIC_NUMBER and msg_type == REQUEST_MSG_TYPE:
                        threading.Thread(target=self.handle_udp_request, args=(udp_socket, client_address, file_size),
                                         daemon=True).start()
                except Exception as e:
                    print(f"[Server] Invalid UDP request from {client_address}: {e}")


if __name__ == "__main__":
    server = Server()
    server.initialize_server()
