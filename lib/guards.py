"""Shared checks for tool inputs that reach git, SQLite, or the network.

``TK_ALLOW_PRIVATE_URLS=1`` lets ``public_url_error`` accept loopback, link-local,
and RFC1918 targets. Scheme must still be http or https.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def safe_git_token(value: str) -> bool:
    """Reject git arguments that look like options or contain whitespace."""
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("-"):
        return False
    return not any(char.isspace() for char in value)


def safe_git_path(value: str) -> bool:
    """Path passed to ``git -C``. Spaces stay; a leading ``-`` is an option."""
    return isinstance(value, str) and bool(value) and not value.startswith("-")


_TOOL_ENV_EXACT = {
    "PATH",
    "HOME",
    "PYTHONPATH",
    "TMPDIR",
    "TMP",
    "LANG",
    "USER",
    "LOGNAME",
    "SHELL",
    "GIT_EXEC_PATH",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_SSH_COMMAND",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_HOST",
    "GH_ENTERPRISE_TOKEN",
    "SSH_AUTH_SOCK",
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
    "no_proxy",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
}


def tool_subprocess_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Allowlisted environment for a tool subprocess.

    Cloud keys and other caller secrets are dropped. PATH, HOME, PYTHONPATH,
    locale, git identity, ``GH_*``, SSH, proxy, CA bundle, and ``TK_*`` variables
    are kept.
    ``overrides`` replace inherited values, including validated ``TK_ARG_*``.
    """
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if (
            key in _TOOL_ENV_EXACT
            or key.startswith("LC_")
            or key.startswith("GIT_CONFIG_")
            or key.startswith("GH_")
            or key.startswith("TK_")
        ):
            env[key] = value
    if overrides:
        env.update(overrides)
    return env


def sqlite_ro_uri(db_path: str) -> str:
    """Read-only SQLite URI with the path percent-encoded so ``?`` and ``#`` stay data."""
    quoted = urllib.parse.quote(str(Path(db_path).resolve()), safe="")
    return f"file:{quoted}?mode=ro"


def _blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def public_url_error(url: str) -> str | None:
    """Return an error string when ``url`` is not a public http(s) URL."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "url must be an absolute http or https URL"
    if os.environ.get("TK_ALLOW_PRIVATE_URLS") == "1":
        return None
    host = parsed.hostname
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as exc:
            return f"could not resolve host: {exc}"
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
    for address in addresses:
        if _blocked(address):
            return f"refusing non-public address {address}"
    return None


class UnsafeURL(ValueError):
    """Raised when a request URL or a redirect target fails ``public_url_error``."""


class _GuardRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        blocked = public_url_error(newurl)
        if blocked:
            raise UnsafeURL(blocked)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def checked_open(request: urllib.request.Request, timeout: float):
    """Open ``request`` and refuse a redirect onto a non-public URL.

    The initial URL is checked before the connection. Each redirect is checked
    before the client follows it, so a public URL cannot bounce to loopback.
    """
    blocked = public_url_error(request.full_url)
    if blocked:
        raise UnsafeURL(blocked)
    opener = urllib.request.build_opener(_GuardRedirect)
    try:
        response = opener.open(request, timeout=timeout)
    except UnsafeURL:
        raise
    except urllib.error.HTTPError:
        raise
    landed = public_url_error(response.geturl())
    if landed:
        response.close()
        raise UnsafeURL(landed)
    return response
