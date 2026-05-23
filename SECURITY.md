# Security Policy

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report privately to: **williamblair333@gmail.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional)

You'll receive an acknowledgement within 48 hours. Fixes are prioritised based
on severity. We'll coordinate a disclosure timeline with you before publishing.

## Scope

This project runs as a personal AI assistant stack on a private machine.
Security-relevant components:

- `scripts/telegram-gateway-poll.sh` — Telegram bot polling and message handling
- `scripts/lib/tg_security.py` — Input sanitisation, rate limiting, injection detection
- `install.sh` / `install-reliability.sh` — System-level installation scripts
- `.env` — Credential storage (never committed; covered by `.gitignore`)

## Known Security Model

- The bot only responds to a single authorised `TELEGRAM_CHAT_ID`
- All user input is sanitised via `tg_security.py` before reaching Claude
- Rate limiting is enforced per chat (20 messages/hour by default)
- Credentials are stored in `.env`, excluded from git via `.gitignore`

## Supported Versions

Only the latest commit on `main` is supported.
