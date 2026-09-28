# Integrations and trust boundaries

## Accounting

HelloSama has its own database and credentials for staff/company employees. The company's primary login is verified by accounting on every login; HelloSama stores an unusable local password for that account. An opaque HMAC identity version detects central password changes without transferring a password hash. The company's active status is checked with a maximum 60-second cache; if a refresh fails, access fails closed.

The companion bridge implements POST-only `/hellosama-api/authenticate/`, `/companies/`, `/status/`, `/finance/` and `/file/`. Each server-to-server request has a timestamp, random nonce, body digest and HMAC-SHA256 signature. Used nonces are persisted briefly to reject replay. Keep the shared key in each app's private environment. Use HTTPS in production. Do not expose the existing broad ERP REST scaffold to client browsers.

Financial endpoints first resolve an active company portal profile and scope all object queries to its client. Only client-visible selling data is serialized. Costs, suppliers, internal notes and arbitrary ERP object serializers are excluded. Attachments are fetched through the scoped service and then the HelloSama user's financial permission is checked. Totals from the existing accounting helpers are labelled in USD; original line/schedule currencies are shown separately.

Automatic account creation uses a 60-second worker sync and immediate provisioning on first successful login. This avoids a slow external call during accounting client creation. If sync is down, the Operations heartbeat identifies it. First-time company provisioning is idempotent. Disabling a company blocks all its HelloSama users; an individual employee's access is managed in HelloSama.

## OpenAI

The backend calls the Responses API with GPT-6 Luna, public `web_search`, `store=false`, a maximum of two tool calls and a 1,500-token output bound. Context is limited to recent travel conversation text. The summary uses strict structured output and then goes through Django form validation and explicit user submission. No model output is treated as an application instruction or permission decision.

The reviewed price basis is $0.10 per million input tokens / $0.50 per million output tokens at normal context, long-context multipliers when applicable, and $0.01 per web search call. A $0.35 reservation covers the allowed call's full-context upper bound plus searches and a cache-write margin. Completed usage is reconciled conservatively, without cache discounts. Model changes are blocked until pricing/budget assumptions are reviewed. Provider pricing changes also require review. Application usage limits do not cover other applications using the same key.

Sources: [model capabilities](https://developers.openai.com/api/docs/models/gpt-6-luna), [pricing](https://developers.openai.com/api/docs/pricing), [web search](https://developers.openai.com/api/docs/guides/tools-web-search), [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## IONOS

SMTP: `smtp.ionos.com:587`, STARTTLS, authenticated with `info@hellosama.com` and its mailbox password. IMAP: `imap.ionos.com:993`, TLS. Receiving reads new INBOX messages without marking them read or deleting them. Sender headers are not trusted as proof of identity; messages are staged for staff review. On first connection or mailbox UID-validity reset, the worker starts from the latest existing UID and imports subsequent replies only.

The notification outbox is saved in the same database transaction as the business event. Each delivery has a unique key. Unexpected/unknown send outcomes are not automatically retried; a CEO can review provider records and authorize a retry through Operations. A failed notification never reverses an already-recorded approval.

Reference: [IONOS official mail server settings](https://www.ionos.com/help/email/general-topics/ionos-mail-server-details-for-imap-pop3-and-smtp/).

## Web push

VAPID keys are generated locally during private configuration setup. Private pages are never cached by the service worker. Push subscriptions are scoped to a signed-in user; validated browser-provider hostnames prevent arbitrary URL submission. Disabling a user/company or losing request access prevents a queued notification from being sent. Device pushes contain only a generic notification and authenticated portal link. Browser support, user consent and delivery vary by device.

## SMS

The outbox data model includes a future SMS channel, but sending is deliberately disabled and no portal credentials or guessed provider URLs are embedded. Add the documented sender endpoint/authentication/delivery reporting only after a valid provider guide is available. The HLR guide describes number lookups, not SMS sending.
