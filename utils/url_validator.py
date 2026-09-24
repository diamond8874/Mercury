"""
URL Validation and SSRF Defense Utility for Mercury.

Provides robust validation of user-supplied or custom base URLs for LLM providers
to protect against Server-Side Request Forgery (SSRF), DNS rebinding, and cloud
metadata access.
"""

import ipaddress
import socket
import urllib.parse
from typing import Tuple, Optional

# Cloud metadata addresses to strictly reject
CLOUD_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),  # AWS ECS metadata
}

# Standard allowed ports for remote LLM API providers
ALLOWED_REMOTE_PORTS = {443}

# Local dev ports permitted ONLY when is_debug=True and host is localhost/127.0.0.1
ALLOWED_LOCAL_DEBUG_PORTS = {11434, 8000, 8080, 5000}


NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")

def is_ip_disallowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_loopback: bool = False) -> Tuple[bool, str]:
    """
    Checks if an IP address belongs to dangerous or private ranges.
    Returns (is_disallowed, reason).
    """
    # If IPv6 NAT64 (RFC 6052) or IPv4-mapped, extract and check embedded IPv4
    if ip.version == 6:
        if ip in NAT64_PREFIX or getattr(ip, "ipv4_mapped", None):
            embedded_ipv4 = ipaddress.IPv4Address(ip.packed[12:])
            return is_ip_disallowed(embedded_ipv4, allow_loopback=allow_loopback)

    # Cloud metadata check
    if ip in CLOUD_METADATA_IPS:
        return True, f"Access to cloud metadata IP {ip} is strictly forbidden."

    # Link-local check (IPv4 169.254.0.0/16, IPv6 fe80::/10)
    if ip.is_link_local:
        return True, f"Link-local IP address {ip} is forbidden."

    # Multicast check
    if ip.is_multicast:
        return True, f"Multicast IP address {ip} is forbidden."

    # Loopback check
    if ip.is_loopback:
        if allow_loopback:
            return False, ""
        return True, f"Loopback address {ip} is forbidden in production."

    # Private network check (10/8, 172.16/12, 192.168/16, fc00::/7)
    if ip.is_private:
        return True, f"Private network address {ip} is forbidden."

    # Reserved / unspecified (0.0.0.0, etc.)
    if ip.is_reserved or ip.is_unspecified:
        return True, f"Reserved or unspecified address {ip} is forbidden."

    return False, ""


def validate_base_url(url: Optional[str], is_debug: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Validates a custom base_url for LLM API calls against SSRF vulnerabilities.

    Rules:
    1. Must parse to a valid URL with scheme and netloc/hostname.
    2. Scheme must be 'https'.
       - Exception: 'http' is permitted ONLY if is_debug is True and the host resolves to localhost/127.0.0.1.
    3. Port must be 443 for remote hosts.
       - Exception: Dev ports (e.g. 11434 for Ollama) permitted only if is_debug is True and host is localhost.
    4. Hostname must resolve to a valid IP.
    5. Resolved IP is validated against private, link-local, cloud metadata, multicast, and loopback ranges.

    Returns:
        (True, None) if safe.
        (False, reason_str) if unsafe.
    """
    if not url or not str(url).strip():
        return False, "Base URL cannot be empty."

    raw_url = str(url).strip()

    try:
        parsed = urllib.parse.urlparse(raw_url)
    except Exception as e:
        return False, f"Invalid URL format: {str(e)}"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"Invalid scheme '{scheme}'. Only https (or http for local dev) is supported."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL must include a valid hostname."

    port = parsed.port
    is_local_host = hostname.lower() in ("localhost", "127.0.0.1", "::1")

    # Scheme check
    if scheme == "http":
        if not (is_debug and is_local_host):
            return False, "Insecure HTTP scheme is forbidden. Only https (or http for localhost in debug) is supported."

    # Port check
    if port is not None:
        if is_local_host and is_debug:
            if port not in ALLOWED_REMOTE_PORTS and port not in ALLOWED_LOCAL_DEBUG_PORTS:
                return False, f"Port {port} is not permitted for local debug endpoints."
        else:
            if port not in ALLOWED_REMOTE_PORTS:
                return False, f"Port {port} is not permitted. Only standard HTTPS (443) is allowed."

    # Resolve hostname to IP addresses to prevent DNS-based SSRF
    try:
        addr_info = socket.getaddrinfo(hostname, None)
        resolved_ips = {item[4][0] for item in addr_info}
    except socket.gaierror as e:
        return False, f"Failed to resolve hostname '{hostname}': {str(e)}"
    except Exception as e:
        return False, f"Error resolving hostname '{hostname}': {str(e)}"

    if not resolved_ips:
        return False, f"No IP address found for hostname '{hostname}'."

    # Validate each resolved IP address
    allow_loopback = (is_debug and is_local_host)

    for ip_str in resolved_ips:
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Invalid resolved IP address: {ip_str}"

        disallowed, reason = is_ip_disallowed(ip_obj, allow_loopback=allow_loopback)
        if disallowed:
            return False, f"Hostname '{hostname}' resolved to disallowed IP {ip_str}: {reason}"

    return True, None
