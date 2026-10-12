# Qarm development notes

## Root cause
Browser OAuth in the current upstream project uses a localhost callback listener. From a browser on a different computer, localhost points to that computer instead of GitHub Codespaces. This matches publicly documented Codex remote-login reports.

Recommended method: a device-code flow. It requires enabling that sign-in method in ChatGPT Security settings. The backend already supports it; this branch makes the device option obvious in the UI, with a recovery button if browser login is pending.

## Separate issues
Selecting the default NVIDIA model without its API key results in a 503; ChatGPT sign-in does not magically configure NVIDIA. After ChatGPT connected-account status is confirmed, select an actually available model before sending a test prompt.

## Verification
Updated Playwright scenarios must be executed in the project's Codespace. Source changes here are committed to GitHub but are not verified on the user's running host yet.

## Roadmap
1. Test device-code login through Codespaces.
2. Verify one successful read-only coding interaction.
3. Harden the remote admin prototype before broader access.
4. Add customizable owner profile and model selection without removing existing models.
5. Develop a mobile-friendly conversation UI.
6. Evaluate search, image, and video capabilities provider by provider.
7. Replace development-only hosting after comparing real free usage, storage, and uptime guarantees.

## Hosting limitation
GitHub Codespaces is a development environment and will suspend. Its default idle timeout is 30 minutes, and its maximum active lifetime is 12 hours. It consumes included compute and storage allowance. An always-on assistant will need a different verified hosting arrangement.

## References
- https://github.com/openai/codex/issues/6403
- https://developers.openai.com/codex/auth#login-on-headless-devices
- https://docs.github.com/en/codespaces/about-codespaces/understanding-the-codespace-lifecycle
