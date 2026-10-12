"""Start Qarm on the free Render instance with required private credentials."""

import os
from urllib.parse import urlsplit

from free_claude_code.cli.commands import serve


def main():
    origin = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    url = urlsplit(origin)
    if not (
        url.scheme == "https"
        and url.hostname
        and url.hostname.endswith(".onrender.com")
        and not url.path
        and not url.query
        and not url.fragment
        and url.port is None
        and url.username is None
        and url.password is None
    ):
        raise SystemExit("A valid Render HTTPS address is required")
    password = os.environ.get("QARM_ADMIN_PASSWORD", "")
    if len(password) < 20 or not os.environ.get("GROQ_API_KEY"):
        raise SystemExit(
            "Configure the existing Groq key and a private owner password in Render secrets"
        )
    os.environ.update(
        {
            "QARM_ADMIN_PUBLIC_ORIGIN": origin,
            "HOST": "0.0.0.0",
            "PORT": os.environ.get("PORT", "10000"),
            "MODEL": "groq/openai/gpt-oss-120b",
            "PROXY_AUTH_ENABLED": "true",
            "ANTHROPIC_AUTH_TOKEN": os.environ.get("ANTHROPIC_AUTH_TOKEN") or password,
            "FCC_OPEN_BROWSER": "false",
        }
    )
    serve()


if __name__ == "__main__":
    main()
