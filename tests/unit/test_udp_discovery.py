import socket
import unittest
import uuid
from unittest.mock import patch

from collab.common.udp_protocol import decode_datagram, encode_datagram
from collab.server.discovery import DiscoveryServer


class DiscoveryTests(unittest.TestCase):
    def test_start_binds_before_return_and_announces_server_address(self):
        discovery = DiscoveryServer(
            37021, bind_host="127.0.0.1", udp_port=0,
        )
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(2)
        try:
            discovery.start()
            self.assertIsNotNone(discovery._socket)
            bound_host, bound_port = discovery._socket.getsockname()
            request_id = str(uuid.uuid4())
            client.sendto(
                encode_datagram({"v": 1, "type": "discover", "request_id": request_id}),
                (bound_host, bound_port),
            )
            response = decode_datagram(client.recvfrom(2048)[0])
            self.assertEqual(response["host"], "127.0.0.1")
            self.assertEqual(response["tcp_port"], 37021)
        finally:
            client.close()
            discovery.stop()
        self.assertFalse(discovery._thread.is_alive())

    def test_wildcard_bind_fallback_uses_local_interface_not_client_ip(self):
        discovery = DiscoveryServer(37021, bind_host="0.0.0.0", udp_port=0)
        with patch.object(discovery, "_get_local_ip", return_value="192.168.1.10"):
            self.assertEqual(discovery._announcement_host(), "192.168.1.10")

    def test_explicit_advertise_host_takes_precedence(self):
        discovery = DiscoveryServer(
            37021, bind_host="0.0.0.0", udp_port=0, advertise_host="192.168.1.20"
        )
        self.assertEqual(discovery._announcement_host(), "192.168.1.20")


if __name__ == "__main__":
    unittest.main()
