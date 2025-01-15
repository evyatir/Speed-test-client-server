import socket
import struct
import threading
import time
from threading import Semaphore

# Define a semaphore to limit concurrent TCP connections
max_connections = 10
semaphore = Semaphore(max_connections)


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
MAGIC_COOKIE = 0xabcddcba
MESSAGE_TYPE_OFFER = 0x2
MESSAGE_TYPE_REQUEST = 0x3
MESSAGE_TYPE_PAYLOAD = 0x4
BROADCAST_PORT = 13117
BUFFER_SIZE = 1024

connection_stats = []


def startup():
    """
    Collect and validate user input for file size and number of connections.
    """
    while True:
        try:
            file_size = int(input(f"{Colors.OKCYAN}Enter file size (bytes): {Colors.ENDC}"))
            if file_size <= 0:
                raise ValueError("File size must be positive.")
            break
        except ValueError as e:
            print(f"{Colors.WARNING}Invalid input: {e}. Try again.{Colors.ENDC}")

    while True:
        try:
            tcp_connections = int(input(f"{Colors.OKCYAN}Enter number of TCP connections: {Colors.ENDC}"))
            if tcp_connections < 0:
                raise ValueError("TCP connections must be non-negative.")
            break
        except ValueError as e:
            print(f"{Colors.WARNING}Invalid input: {e}. Try again.{Colors.ENDC}")

    while True:
        try:
            udp_connections = int(input(f"{Colors.OKCYAN}Enter number of UDP connections: {Colors.ENDC}"))
            if udp_connections < 0:
                raise ValueError("UDP connections must be non-negative.")
            break
        except ValueError as e:
            print(f"{Colors.WARNING}Invalid input: {e}. Try again.{Colors.ENDC}")

    return file_size, tcp_connections, udp_connections


def listen_for_offers():
    """
    Listen for server broadcast offers over UDP.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as udp_socket:
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_socket.bind(('', BROADCAST_PORT))

        print(f"{Colors.OKBLUE}[Client] Listening for server offers...{Colors.ENDC}")
        while True:
            try:
                data, addr = udp_socket.recvfrom(BUFFER_SIZE)
                magic_cookie, message_type, udp_port, tcp_port = struct.unpack('!IBHH', data[:10])
                if magic_cookie == MAGIC_COOKIE and message_type == MESSAGE_TYPE_OFFER:
                    print(
                        f"{Colors.OKGREEN}[Client] Received offer from {addr[0]}: UDP Port {udp_port}, TCP Port {tcp_port}{Colors.ENDC}")
                    return addr[0], udp_port, tcp_port
            except Exception as e:
                print(f"{Colors.WARNING}[Client] Error receiving offer: {e}{Colors.ENDC}")


def tcp_transfer(server_ip, tcp_port, file_size, transfer_id):
    """
    Perform a single TCP transfer with retry and timeout handling.
    """
    retries = 3
    with semaphore:
        for attempt in range(retries):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
                    tcp_socket.settimeout(5)
                    tcp_socket.connect((server_ip, tcp_port))
                    tcp_socket.sendall(f"{file_size}\n".encode())

                    start_time = time.time()
                    total_received = 0

                    while total_received < file_size:
                        data = tcp_socket.recv(min(BUFFER_SIZE, file_size - total_received))
                        if not data:
                            break
                        total_received += len(data)

                    elapsed_time = time.time() - start_time
                    speed = (total_received * 8) / (elapsed_time if elapsed_time > 0 else 0.001)
                    connection_stats.append({"type": "TCP", "file_size": file_size, "speed": speed})
                    print(
                        f"{Colors.OKGREEN}TCP transfer #{transfer_id} finished, total time: {elapsed_time:.2f} seconds, speed: {speed:.2f} bits/second{Colors.ENDC}")
                    break

            except Exception as e:
                if attempt == retries - 1:
                    print(
                        f"{Colors.FAIL}[Client] TCP transfer #{transfer_id} failed after {retries} attempts: {e}{Colors.ENDC}")
                else:
                    print(
                        f"{Colors.WARNING}[Client] Retrying TCP transfer #{transfer_id}... (attempt {attempt + 1}){Colors.ENDC}")


def udp_transfer(server_ip, udp_port, file_size, transfer_id):
    """
    Perform a single UDP transfer with improved error handling and packet tracking.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.settimeout(5)  # Increased timeout

            # Send request with file size
            request_message = struct.pack('!IBQ', MAGIC_COOKIE, MESSAGE_TYPE_REQUEST, file_size)
            udp_socket.sendto(request_message, (server_ip, udp_port))

            start_time = time.time()
            total_received = 0
            received_segments = set()
            expected_segments = (file_size + BUFFER_SIZE - 1) // BUFFER_SIZE

            # Wait for initial response or timeout
            try:
                initial_data, _ = udp_socket.recvfrom(BUFFER_SIZE + 21)
                if not initial_data:
                    raise Exception("No initial response from server")
            except socket.timeout:
                raise Exception("Server did not respond to initial request")

            # Main receive loop
            while total_received < file_size and time.time() - start_time < 30:  # 30 second total timeout
                try:
                    data, _ = udp_socket.recvfrom(BUFFER_SIZE + 21)
                    if len(data) < 21:  # Check for minimum packet size
                        continue

                    magic_cookie, message_type, total_segments, current_segment = struct.unpack('!IBQQ', data[:21])

                    if magic_cookie != MAGIC_COOKIE or message_type != MESSAGE_TYPE_PAYLOAD:
                        continue

                    if current_segment not in received_segments:
                        received_segments.add(current_segment)
                        payload_size = len(data[21:])
                        total_received += payload_size

                    # Progress update every 10% or when completed
                    progress = (len(received_segments) / expected_segments) * 100
                    if progress % 10 == 0 or progress == 100:
                        print(
                            f"{Colors.OKBLUE}[Client] UDP transfer #{transfer_id} progress: {progress:.1f}%{Colors.ENDC}")

                except socket.timeout:
                    # Retry request if we haven't received anything for a while
                    udp_socket.sendto(request_message, (server_ip, udp_port))
                    continue

            elapsed_time = time.time() - start_time
            if elapsed_time == 0:
                elapsed_time = 0.001

            speed = (total_received * 8) / elapsed_time
            success_rate = (len(received_segments) / expected_segments) * 100

            connection_stats.append({
                "type": "UDP",
                "file_size": file_size,
                "speed": speed,
                "success_rate": success_rate
            })

            print(f"{Colors.OKGREEN}UDP transfer #{transfer_id} completed:")
            print(f"Success rate: {success_rate:.1f}%")
            print(f"Speed: {speed:.2f} bits/second")
            print(f"Time: {elapsed_time:.2f} seconds{Colors.ENDC}")

    except Exception as e:
        print(f"{Colors.FAIL}[Client] Error in UDP transfer #{transfer_id}: {e}{Colors.ENDC}")


def speed_test(server_ip, tcp_port, udp_port, file_size, tcp_connections, udp_connections):
    """
    Perform multiple TCP and UDP transfers as part of the speed test.
    """
    threads = []

    # Start TCP threads
    for i in range(tcp_connections):
        thread = threading.Thread(target=tcp_transfer, args=(server_ip, tcp_port, file_size, i + 1))
        threads.append(thread)
        thread.start()

    # Start UDP threads
    for i in range(udp_connections):
        thread = threading.Thread(target=udp_transfer, args=(server_ip, udp_port, file_size, i + 1))
        threads.append(thread)
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Calculate and display statistics
    tcp_stats = [stat for stat in connection_stats if stat["type"] == "TCP"]
    udp_stats = [stat for stat in connection_stats if stat["type"] == "UDP"]

    if tcp_stats:
        avg_tcp_speed = sum(stat["speed"] for stat in tcp_stats) / len(tcp_stats)
        print(f"\n{Colors.OKBLUE}Average TCP Speed: {avg_tcp_speed:.2f} bits/second{Colors.ENDC}")

    if udp_stats:
        avg_udp_speed = sum(stat["speed"] for stat in udp_stats) / len(udp_stats)
        avg_success_rate = sum(stat["success_rate"] for stat in udp_stats) / len(udp_stats)
        print(f"{Colors.OKBLUE}Average UDP Speed: {avg_udp_speed:.2f} bits/second")
        print(f"Average UDP Success Rate: {avg_success_rate:.1f}%{Colors.ENDC}")

    print(f"\n{Colors.OKBLUE}[Client] All transfers complete. Listening for new offers...{Colors.ENDC}")


if __name__ == "__main__":
    while True:
        file_size, tcp_connections, udp_connections = startup()
        server_ip, udp_port, tcp_port = listen_for_offers()
        speed_test(server_ip, tcp_port, udp_port, file_size, tcp_connections, udp_connections)


