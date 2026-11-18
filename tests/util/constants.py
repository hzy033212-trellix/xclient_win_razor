"""Constants shared by the tests.

Filesystem paths are centralized in ``paths.json`` at the repo root and loaded
by ``tests/util/paths.py``; RAZOR_PUBLIC is re-exported here for
the modules that import them from ``tests.util.constants``.
"""
from tests.util.paths import RAZOR_PUBLIC  # noqa: F401

# Using the Trellix Artifactory instance (https://artifactory.trellix.com/) for IPv4 testing.
# Test-NetConnection -ComputerName 10.40.6.239 -Port 80
IPV4_TARGET = "10.40.6.239"

# Using ipv6.google.com for IPv6 testing
IPV6_TARGET = "2607:f8b0:4002:c11::71"
