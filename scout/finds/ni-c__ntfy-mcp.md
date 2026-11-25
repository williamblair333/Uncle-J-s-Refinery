# ni-c/ntfy-mcp

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/ni-c/ntfy-mcp
- Stars: 1 (gh, 2026-11-25)
- Licence: MIT
- Last commit: 2026-11-19
- Source: discovered · Messaging gateways and notifications (covered)

MCP server for ntfy: publish notifications, read cached messages, manage users and topic access

## Take

Uncle J's notifications go out through Telegram scripts (session-notify, stack-alerts-send, healthcheck-notify), which depend on Telegram's servers, and no agent can call them as an MCP tool to publish, update or read back a notification.

It's a stdio MCP server for ntfy that can point at a self-hosted ntfy server, so agent push alerts keep working on the LAN with no vendor in the loop. NTFY_TOPICS keeps the topic names out of the model's context. NTFY_ALLOW_TOOLS=essential cuts it to six tools, and update_message turns a progress report into one notification that changes in place. That suits the accuracy and token-cost goals better than the other ntfy servers here, and ntf-ai is mostly an iOS app.

Risk: It needs Node 24 or later and is published through npm, so pin a locally installed copy rather than running it through npx -y on each launch. iOS phone push also goes through the upstream ntfy relay, so fully offline delivery is realistic only for Android, the web app or the desktop.

Scores: tokens 4/5, accuracy 4/5, creativity 3/5, offline 4/5
