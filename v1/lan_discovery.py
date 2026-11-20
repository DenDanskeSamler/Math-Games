import socket
import time

from game_settings import SETTINGS

DISCOVERY_REQUEST = b"ARCADE_LAN_DISCOVERY_V1"
DISCOVERY_RESPONSE_PREFIX = b"ARCADE_LAN_SERVER_V1:"


def parse_discovery_response(payload: bytes, host: str) -> str | None:
    if not payload.startswith(DISCOVERY_RESPONSE_PREFIX):
        return None
    port_text = payload[len(DISCOVERY_RESPONSE_PREFIX) :]
    if not port_text.isdigit():
        return None
    port = int(port_text)
    if not 1 <= port <= 65535:
        return None
    return f"http://{host}:{port}"


def discover_server(
    timeout: float = SETTINGS.discovery_timeout_seconds,
    discovery_port: int = SETTINGS.discovery_port,
) -> str | None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as discovery_socket:
        discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        send_errors = []
        for address in ("255.255.255.255", "127.0.0.1"):
            try:
                discovery_socket.sendto(
                    DISCOVERY_REQUEST,
                    (address, discovery_port),
                )
            except OSError as error:
                send_errors.append(error)
        if len(send_errors) == 2:
            raise OSError("Could not send a LAN discovery request.") from send_errors[0]

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            discovery_socket.settimeout(remaining)
            try:
                payload, address = discovery_socket.recvfrom(256)
            except socket.timeout:
                return None
            server_url = parse_discovery_response(payload, address[0])
            if server_url:
                return server_url
