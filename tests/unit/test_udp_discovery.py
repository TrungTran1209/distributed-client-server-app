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
        self.assertEqual(discovery._announcement_host("127.0.0.1"), "192.168.1.20")

    def test_wildcard_bind_announces_loopback_to_loopback_peer_even_with_vpn_route(self):
        discovery = DiscoveryServer(37021, bind_host="0.0.0.0", udp_port=0)
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(2)
        try:
            with patch.object(discovery, "_get_local_ip", return_value="172.16.0.2"):
                discovery.start()
                assert discovery._socket is not None
                _, bound_port = discovery._socket.getsockname()
                request_id = str(uuid.uuid4())
                client.sendto(
                    encode_datagram({"v": 1, "type": "discover", "request_id": request_id}),
                    ("127.0.0.1", bound_port),
                )
                response = decode_datagram(client.recvfrom(2048)[0])
                self.assertEqual(response["host"], "127.0.0.1")
        finally:
            client.close()
            discovery.stop()

    def test_wildcard_bind_uses_peer_routed_interface_for_lan_peer(self):
        discovery = DiscoveryServer(37021, bind_host="0.0.0.0", udp_port=0)
        with (
            patch.object(discovery, "_route_ip_for_peer", return_value="192.168.1.20") as mock_route,
            patch.object(discovery, "_get_local_ip", return_value="172.16.0.2"),
        ):
            self.assertEqual(discovery._announcement_host("192.168.1.55"), "192.168.1.20")
            mock_route.assert_called_once_with("192.168.1.55")

    def test_second_discovery_server_cannot_share_same_udp_port(self):
        first = DiscoveryServer(37021, bind_host="127.0.0.1", udp_port=0)
        first.start()
        try:
            assert first._socket is not None
            _, bound_port = first._socket.getsockname()
            second = DiscoveryServer(37022, bind_host="127.0.0.1", udp_port=bound_port)
            with self.assertRaises(OSError):
                second.start()
            second.stop()
        finally:
            first.stop()


if __name__ == "__main__":
    unittest.main()
