"""Pure validation shared by Qarm CLI bootstrap and owner sessions."""

from urllib.parse import urlsplit


def codespaces_origin_allowed(origin: str) -> bool:
    try:
        url = urlsplit(origin)
        return (
            url.scheme == "https"
            and bool(url.hostname)
            and url.hostname.endswith((".app.github.dev", ".onrender.com"))
            and url.username is None
            and url.password is None
            and url.port is None
            and not url.path
            and not url.query
            and not url.fragment
        )
    except ValueError:
        return False
