import socket
import struct
import threading
import time


# ANSI color codes for output formatting
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


# Constants for communication
MAGIC_NUMBER = 0xabcddcba  # Identifier for valid packets
OFFER_MSG_TYPE = 0x2  # Message type for server offers
REQUEST_MSG_TYPE = 0x3  # Message type for client requests
PAYLOAD_MSG_TYPE = 0x4  # Message type for data payload
BROADCAST_PORT = 13117  # UDP broadcast port
BUFFER_SIZE = 4096  # Size of data chunks

# List to store connection statistics
connection_stats = []


class Client:
    def __init__(self):
        self.server_ip = None
        self.udp_port = None
        self.tcp_port = None
        self.file_size = None
        self.tcp_connections = None
        self.udp_connections = None

    def gather_input(self):
        """
        Collect and validate user input for file size and number of connections.
        Ensures all inputs are positive integers.
        Returns:
            tuple: file_size (int), tcp_connections (int), udp_connections (int)
        """
        while True:
            try:
                self.file_size = int(input(f"{Colors.OKCYAN}Enter file size (bytes): {Colors.ENDC}"))
                if self.file_size <= 0:
                    raise ValueError("File size must be positive.")
                break
            except ValueError as e:
                print(f"{Colors.WARNING}Invalid input: {e}. Try again.{Colors.ENDC}")

        while True:
            try:
                self.tcp_connections = int(input(f"{Colors.OKCYAN}Enter number of TCP connections: {Colors.ENDC}"))
                if self.tcp_connections < 0:
                    raise ValueError("TCP connections must be non-negative.")
                break
            except ValueError as e:
                print(f"{Colors.WARNING}Invalid input: {e}. Try again.{Colors.ENDC}")

        while True:
            try:
                self.udp_connections = int(input(f"{Colors.OKCYAN}Enter number of UDP connections: {Colors.ENDC}"))
                if self.udp_connections < 0:
                    raise ValueError("UDP connections must be non-negative.")
                break
            except ValueError as e:
                print(f"{Colors.WARNING}Invalid input: {e}. Try again.{Colors.ENDC}")

    def listen_for_server(self):
        """
        Listen for server broadcast offers over UDP.
        Returns:
            tuple: server_ip (str), udp_port (int), tcp_port (int)
        """
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as udp_socket:
            # Set the socket to allow broadcast
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp_socket.bind(('', BROADCAST_PORT))  # Bind to the broadcast port

            print(f"{Colors.OKBLUE}[Client] Awaiting server offers...{Colors.ENDC}")
            while True:
                try:
                    # Receive and unpack offer data
                    data, addr = udp_socket.recvfrom(BUFFER_SIZE)
                    magic_number, message_type, udp_port, tcp_port = struct.unpack('!IBHH', data[:10])
                    if magic_number == MAGIC_NUMBER and message_type == OFFER_MSG_TYPE:
                        print(
                            f"{Colors.OKGREEN}[Client] Offer received from {addr[0]}: UDP Port {udp_port}, TCP Port {tcp_port}{Colors.ENDC}")
                        return addr[0], udp_port, tcp_port
                except Exception as e:
                    print(f"{Colors.WARNING}[Client] Error while receiving offer: {e}{Colors.ENDC}")

    def initiate_tcp_transfer(self, server_ip, tcp_port, file_size, transfer_id):
        """
        Perform a single TCP transfer.
        Args:
            server_ip (str): Server IP address.
            tcp_port (int): Server TCP port.
            file_size (int): Requested file size.
            transfer_id (int): Transfer identifier for logging.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
                tcp_socket.connect((server_ip, tcp_port))
                tcp_socket.sendall(f"{file_size}\n".encode())

                start_time = time.time()
                total_received = 0

                # Receive data in chunks
                while total_received < file_size:
                    data = tcp_socket.recv(min(BUFFER_SIZE, file_size - total_received))
                    if not data:
                        break
                    total_received += len(data)

                elapsed_time = time.time() - start_time
                try:
                    speed = (total_received * 8) / elapsed_time  # Convert to bits/second
                except ZeroDivisionError:
                    speed = (total_received * 8) / 0.0099
                connection_stats.append({"type": "TCP", "file_size": file_size, "speed": speed})
                print(
                    f"{Colors.OKGREEN}TCP transfer #{transfer_id} completed, total time: {elapsed_time:.2f} seconds, total "
                    f"speed: {speed:.2f} bits/second{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.FAIL}[Client] TCP transfer #{transfer_id} failed: {e}{Colors.ENDC}")

    def initiate_udp_transfer(self, server_ip, udp_port, file_size, transfer_id):
        """
        Perform a single UDP transfer.
        Args:
            server_ip (str): Server IP address.
            udp_port (int): Server UDP port.
            file_size (int): Requested file size.
            transfer_id (int): Transfer identifier for logging.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
                udp_socket.settimeout(1)
                request_message = struct.pack('!IBQ', MAGIC_NUMBER, REQUEST_MSG_TYPE, file_size)
                udp_socket.sendto(request_message, (server_ip, udp_port))

                total_segments = file_size // BUFFER_SIZE + (1 if file_size % BUFFER_SIZE != 0 else 0)
                received_segments = set()
                start_time = time.time()

                # Receive data packets
                while True:
                    try:
                        data, _ = udp_socket.recvfrom(BUFFER_SIZE + 21)
                        magic_number, message_type, total_segments, current_segment = struct.unpack('!IBQQ', data[:21])
                        if magic_number == MAGIC_NUMBER and message_type == PAYLOAD_MSG_TYPE:
                            received_segments.add(current_segment)
                    except socket.timeout:
                        break

                elapsed_time = time.time() - start_time
                success_rate = (len(received_segments) / total_segments) * 100
                speed = (len(received_segments) * BUFFER_SIZE * 8) / elapsed_time  # Convert to bits/second
                connection_stats.append({"type": "UDP", "file_size": file_size, "speed": speed})
                print(
                    f"{Colors.OKGREEN}UDP transfer #{transfer_id} completed, total time: {elapsed_time:.2f} seconds, total speed: {speed:.2f} bits/second,\
                     percentage of packets received successfully: {success_rate:.2f}%{Colors.ENDC}")

        except Exception as e:
            print(f"{Colors.FAIL}[Client] UDP transfer #{transfer_id} failed: {e}{Colors.ENDC}")

    def run_speed_test(self, server_ip, tcp_port, udp_port, file_size, tcp_connections, udp_connections):
        """
        Perform multiple TCP and UDP transfers as part of the speed test.
        Args:
            server_ip (str): Server IP address.
            tcp_port (int): Server TCP port.
            udp_port (int): Server UDP port.
            file_size (int): Requested file size for each transfer.
            tcp_connections (int): Number of TCP connections.
            udp_connections (int): Number of UDP connections.
        """
        threads = []

        # Start TCP threads
        for i in range(tcp_connections):
            thread = threading.Thread(target=self.initiate_tcp_transfer, args=(server_ip, tcp_port, file_size, i + 1))
            threads.append(thread)
            thread.start()

        # Start UDP threads
        for i in range(udp_connections):
            thread = threading.Thread(target=self.initiate_udp_transfer, args=(server_ip, udp_port, file_size, i + 1))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        print(f"{Colors.OKBLUE}[Client] All transfers complete. Waiting for new offers...{Colors.ENDC}")
        print(f"{Colors.OKCYAN}Collected Statistics: {connection_stats}{Colors.ENDC}")


if __name__ == "__main__":
    client = Client()
    client.gather_input()
    server_ip, udp_port, tcp_port = client.listen_for_server()
    client.run_speed_test(server_ip, tcp_port, udp_port, client.file_size, client.tcp_connections, client.udp_connections)
