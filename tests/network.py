"""Executed on Docker's internal network, with production's resolver file."""
import socket
from pathlib import Path

assert 'nameserver 127.0.0.1' in Path('/etc/resolv.conf').read_text()
routes = Path('/proc/net/route').read_text().splitlines()[1:]
assert not any(line.split()[1] == '00000000' for line in routes), routes
for family, address, port in [(socket.AF_INET, '1.1.1.1', 443), (socket.AF_INET, '1.1.1.1', 25),
                              (socket.AF_INET, '1.1.1.1', 53), (socket.AF_INET6, '2606:4700:4700::1111', 443)]:
    with socket.socket(family, socket.SOCK_STREAM) as connection:
        connection.settimeout(1)
        assert connection.connect_ex((address, port)) != 0, f'unexpected egress to {address}:{port}'
try:
    socket.getaddrinfo('example.com', 443)
except socket.gaierror:
    pass
else:
    raise AssertionError('external DNS resolution succeeded')
print('PASS internal Docker network blocks external SMTP, HTTP, DNS and IPv6; resolver cannot escape through Docker DNS')
