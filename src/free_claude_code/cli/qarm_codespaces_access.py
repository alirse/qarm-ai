"""Safe, opt-in-by-environment owner login for GitHub Codespaces.

Codespaces forwards a private port to an HTTPS *.app.github.dev URL. The
application MUST still require its own password, including when someone
accidentally changes the port to Public. This bootstrap runs in the fcc-server
CLI only; regular/local FCC and import-only callers are unchanged.
"""

import os
import re
import secrets
import stat
import sys
from pathlib import Path

_CODESPACE_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\Z")
_PASSWORD_LENGTH_MIN = 20


def _codespaces_enabled() -> bool:
    return os.environ.get("CODESPACES", "").lower() == "true"


def owner_password_file() -> Path:
    """Store owner secrets outside GitHub checkouts, in the Codespace home."""
    return Path.home() / ".config" / "qarm" / "codespaces-owner-password"


def _read_saved_password(path: Path) -> str:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Qarm owner password path is not a regular file")
    if metadata.st_mode & 0o077:
        raise ValueError("Qarm owner password file must not allow group/other access")
    secret = path.read_text(encoding="utf-8").strip()
    if len(secret) < _PASSWORD_LENGTH_MIN:
        raise ValueError("Qarm saved owner password is too short")
    return secret


def _get_or_create_owner_password(path: Path) -> str:
    directory = path.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_info = directory.lstat()
    if not stat.S_ISDIR(directory_info.st_mode) or directory_info.st_mode & 0o077:
        raise ValueError("Qarm owner secret directory must be private (0700)")

    try:
        return _read_saved_password(path)
    except FileNotFoundError:
        pass

    secret = secrets.token_urlsafe(36)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        # A concurrent Codespaces process may have won creation.
        return _read_saved_password(path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(secret + "\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return secret


def prepare_codespaces_owner_login(port: int) -> str | None:
    """Set strict owner-login env vars only when running in Codespaces.

    Existing explicit operator settings win; neither is written to the repo.
    The secret persists in the Codespace home across ordinary restarts.
    """
    if not _codespaces_enabled():
        return None
    name = os.environ.get("CODESPACE_NAME", "")
    if not _CODESPACE_NAME.fullmatch(name):
        raise ValueError("Cannot identify this GitHub Codespace safely")
    if not 1 <= port <= 65535:
        raise ValueError("Invalid Qarm forwarded port")

    discovered_origin = f"https://{name}-{port}.app.github.dev"
    configured_origin = os.environ.get("QARM_ADMIN_PUBLIC_ORIGIN") or discovered_origin

    # Validate a manually supplied origin instead of silently weakening access.
    from free_claude_code.api.qarm_admin_session import _origin_allowed

    if not _origin_allowed(configured_origin):
        raise ValueError("Configured Qarm Codespaces origin must be an HTTPS app.github.dev host")

    existing_password = os.environ.get("QARM_ADMIN_PASSWORD")
    if existing_password is not None and existing_password != "":
        if len(existing_password) < _PASSWORD_LENGTH_MIN:
            raise ValueError("Configured Qarm owner password must be at least 20 characters")
    else:
        secret = _get_or_create_owner_password(owner_password_file())
        os.environ["QARM_ADMIN_PASSWORD"] = secret

    os.environ["QARM_ADMIN_PUBLIC_ORIGIN"] = configured_origin
    return f"{configured_origin}/admin/login"


def main() -> None:
    """Deliberate password reveal from the Codespaces private terminal only."""
    if not _codespaces_enabled() or not sys.stdout.isatty():
        raise SystemExit("Run this command manually in your own Codespaces terminal.")
    path = owner_password_file()
    try:
        secret = _read_saved_password(path)
    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"No usable auto-generated Qarm password ({type(exc).__name__}). "
            "If you explicitly supplied QARM_ADMIN_PASSWORD, use that instead."
        ) from None
    print("Qarm owner password (PRIVATE — never paste into a chat or GitHub):")
    print(secret)


if __name__ == "__main__":
    main()
