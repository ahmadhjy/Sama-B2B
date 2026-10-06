# Client updates — 5 October 2026

Reviewed the Sama Tours written notes, images and Tailwind references in their Saturday-to-Sunday order. Voice notes and the final two unrelated Monday HTML attachments are excluded, as requested.

## Reference order and implementation

1. Saturday login reference and portal icons: navy/cobalt login layout and static travel-agency/corporate/organisation service identities. The 6 October correction replaces the original placeholder symbols with the client's supplied emblems. Existing authentication and roles are retained.
2. Company-owner account screen: explicit company login username label, account-code suggestions and matching company-name preview. Accounting remains authoritative for new company names and shared logins.
3. Passport date/nationality note: day/month/year expiry selectors and country selection, preserving existing nationality values.
4. [Profile](https://play.tailwindcss.com/gQ4i0HdCGc): grouped contact, travel-document and notification sections.
5. [Owner dashboard](https://play.tailwindcss.com/KNaGycUxKj): direct personal-request access, team count and distinct company/personal request navigation.
6. Flight suggestions and preview notes, then [trip planner](https://play.tailwindcss.com/YX5rObFsIB): separate saved trip drafts, close/restore, editable reviews, batch submission, supporting files and quick chat prompts. At most two sourced flight/hotel preference cards; the server requires matching search citations. AI replies stay brief and never ask for a budget.
7. [Submitted request](https://play.tailwindcss.com/ydOdQ7djnJ): visible progress, summary PDF and trip editing before quotation.
8. [Quotation conversation](https://play.tailwindcss.com/IL0vtch7iS): quotation access inside the conversation and quick message prompts, retaining versioned quotes and attachments.
9. [Approval progress](https://play.tailwindcss.com/yfRUkyZ9UP) and written quick-approval example: focused approval review, current-version/expiry checks, visible approval state and rate-limited pending-approver reminders.
10. [Requests hub](https://play.tailwindcss.com/4vbov2dmzV): status, service, departure-date and text filters; requester and booking-reference search; current quotation amount; filter-preserving pagination.
11. [Accounting](https://play.tailwindcss.com/VMhjto4Kvq): ledger search/date filters, provider running balances, filtered statement PDF and spreadsheet-safe CSV exports.
12. [Team](https://play.tailwindcss.com/8xP5M2SQ3d): search, role filters, role totals and profile completion indicators alongside existing account management.
13. [Owner travel overview](https://play.tailwindcss.com/SQEUGRSIgs): confirmed-trip date overview, requester contacts, PDF download and posting an update to selected active trip conversations.
14. [Conversation history](https://play.tailwindcss.com/MGDhZ49dUZ): personal request/conversation split view, recent-history selection, search-all link and permission-filtered conversation PDF exports.

## Integration boundaries

The references contain example data and capabilities that need separate provider integrations. No sample balances, flight inventory, GPS positions, GDS hold timers or automatic ticket issuance are presented as real. AI source cards represent published information and preferences for Sama to verify. The overview uses confirmed portal requests and recorded dates. The existing all-approver workflow remains required before Sama books.

Travel updates use existing portal conversations and the existing notification delivery system. This release does not activate SMS/email credentials or add WhatsApp dispatch. Separate travel-agency/organisation authentication products are not introduced by the login's service labels.

## Completion review — 6 October 2026

All eleven linked Tailwind pages above were reopened and read in chronological order. The Saturday 4:55 PM profile image and Sunday 3:41 PM planner image were also inspected. **Reviewed does not mean every mockup feature has been implemented.** The delivered screens adapt the references to the existing portal; they are not exact reproductions. Do not describe this as 100% completion of every element in the mockups.

The company-owner clarification is implemented: **Company name** is shown separately, and **Login user name** remains the accounting client code. Known connected companies show their saved name as the code is entered. A new company's name is confirmed by Accounting during creation/connection; this form does not provide a live lookup of all Accounting clients or let an administrator rename an Accounting client.

Specific differences and outstanding capabilities:

- **Profile:** password changes use the existing separate Change password page. The Saturday image's inline new-password/confirmation fields are not part of profile completion. Passport expiry uses three selectors instead of the mockup's single date field.
- **Owner dashboard:** personal requests, team count and navigation are available. The reference's account-balance/credit-standing tile, embedded user-permission list and recent-invoice cards are not reproduced on the dashboard; financial records and people remain on their respective pages.
- **Planner:** draft tabs, editable reviews and batch submission are available. Closing/restoring individual drafts replaces the mockup's bulk Clear inactive drafts control. Suggestions are capped at two cited preference cards, not four live flight schedules plus three priced hotel choices. There is no live package-pricing calculator, radio-button package selection or reservation. Files are submitted through the individual request form, not the batch review.
- **Submitted request:** the user opens the normal request conversation after submission; submitted and draft trips are not combined into the mockup's single tab strip. No response-time promise, agent-online indicator or GDS seat-locking claim is made. Trip editing is restricted once a quotation exists.
- **Quotation:** existing versioned quotations, approval controls, PDF downloads and uploaded booking documents are retained. The mockup's separately priced flight/hotel offer cards and payment-method selector are not implemented. No saved-card payment processing, guaranteed-seat countdown, automatic ticket issuance or automatic invoice creation is added.
- **Approval:** a focused review page replaces the proposed modal. All designated approvers must approve the current quotation before Sama books. The pending reminder queues configured notification channels; it is not an automated WhatsApp dispatch or proof of delivery.
- **Requests hub:** service, status, text and departure-date filters are implemented. The reference's GDS sync/hold badges, department/carrier breakdown, preset date ranges and aggregate table value are not reproduced.
- **Accounting:** statement/invoice/receipt views, date filters and exports are available. Excel-compatible CSV is provided instead of a native XLSX file. Credit limits, available credit, Net-30 facility cards and quarter/year presets from the mockup are not added.
- **People & access:** existing roles, approver permissions, search and profile-completion status remain authoritative. Seat quotas, configurable spending thresholds, a policy-settings editor and advance passport-expiry warnings are not implemented. A complete profile is not represented as independently verified identity.
- **Travel overview:** confirmed requests and recorded dates identify the requester and party size. Live GPS, hotel room tracking, flight operational status, individual passenger manifests and emergency-dispatch service are not implemented. Bulk updates post to selected active trip conversations.
- **History:** the split view lists the latest 40 personal requests with a link to search all. It does not reproduce the mockup's All/Active/Completed tabs or an automatic ticketing timeline. Conversation exports follow existing access rules; no new permanent-retention or compliance guarantee is introduced.

Voice notes and the two unrelated Monday HTML files remain excluded by the user's instruction. No production deployment or live provider delivery is confirmed by this review.

For this correction, 29 company-account and client-workflow tests passed locally. The client emblems and company-name/code matching were checked in the local preview with fictional data. No model or accounting-bridge change is included in this correction.

## Release and verification

This release adds migration `portal.0005`: an archived flag for drafts and a service category for requests. Existing requests default to **Travel request**; existing records are preserved. No accounting-application migration or bridge reinstall is needed for these changes.

In the PythonAnywhere Bash console, run:

```bash
bash /home/Samatours2026/HelloSama/deploy/update.sh
```

The existing updater pulls the release, applies migrations, collects static files and reloads the configured HelloSama WSGI app. It preserves `.env` and stops on tracked local edits. Keep the established database backup routine before production updates.

Automated regression coverage includes cross-company access, private/internal export filtering, draft ownership, atomic batch submission, duplicate submissions, pending-approval rules, trip edit restrictions, date handling and sourced AI preference cards. The existing CI runs against PostgreSQL 12 and 16. Local preview data is fictional and lives only in an ignored test database; real notification delivery and paid AI calls are not part of local testing.

Country names come from the ISO 3166-1 data distributed by Debian `iso-codes`, via `pycountry` 26.2.16 (LGPL-2.1-or-later). Source: <https://github.com/pycountry/pycountry>. The application has no new runtime dependency on that package.
