# Qarm admin from a private GitHub Codespace

The Admin UI is local-only by default. Qarm adds an opt-in remote login for HTTPS forwarded URLs ending in `.app.github.dev`. **Keep the forwarded port Private** (GitHub must authenticate access separately).

## Enable

Set `QARM_ADMIN_PASSWORD` to a unique secret of 12+ characters **in the running server environment**. Do not save it in Git, commit it, paste it into chat, or put it in a URL. Run the updated server with that environment variable; open `https://<your-private-forwarded-host>/admin` and sign in with browser HTTP Basic credentials:

- Username: `qarm`
- Password: the value of `QARM_ADMIN_PASSWORD`

A Codespaces port URL must use HTTPS, and API writes require a same-origin browser request. Without the variable, the existing local-only protection stays active. Do not make a forwarded port Public; do not rely on this password alone for Internet exposure.

## Important caveats

- Remote admin access is not the proposed two-message 'owner mode' for chat/model preferences; that feature still requires separate integration.
- Do not enable this for a public multi-user deployment. Basic Auth is a minimal private-development login, not a full account/session/2FA system.
- Requires restart of the server process to pick up the new code and environment.
- Run `uv run --no-sync pytest -q tests/api/test_qarm_remote_admin.py` before relying on the feature. These tests are supplied but have not been executed in the user's Codespace.
- If Codespaces or another reverse proxy rewrites the forwarded Host/HTTPS headers, access will fail closed, rather than bypass protection.
