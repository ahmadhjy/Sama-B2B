# Using HelloSama

## Access and people

Creating/enabling a client portal account in accounting gives that company a linked HelloSama account. The existing account number and password are used centrally. Passwords are never displayed or stored in readable form. First and last name, email, mobile with country code, passport number/expiry and nationality must be complete for company users. A passport copy is optional by default; enable `REQUIRE_PASSPORT_COPY` if the business requires it.

Company administrators create team users with first name, last name and password. Login IDs are generated automatically and displayed after creation. Optional details can be filled by the administrator or completed by the user at first sign-in. Share initial credentials through your approved private channel. Users can change individual passwords. The primary company password remains managed by accounting.

Roles:

- Company administrator: manages company users, oversees company requests, and sees financial records.
- Sales/requester: creates requests and follows their own conversations.
- Company accountant: sees company financial records. Request access comes only from ownership of a request or an assigned approval.
- Sama CEO: oversees all companies, requests, approvals and financial records; manages staff, reassigns work and reviews email.
- Sama salesperson: sees minimal unassigned queue summaries, claims a request and works only on assigned requests.
- Sama accounting: sees financial records; no general sales conversation access.

**Can approve quotations** is a separate checkbox on company users. The HR person or sales manager can use whichever base role fits their day-to-day access, with the checkbox enabled. Their job title alone does not grant approval. The main company administrator starts as an approver. All active designated approvers are required by default, including a requester who is also an approver; set `ALLOW_SELF_APPROVAL=False` to exclude the requester if that is the company's policy.

## From conversation to confirmed booking

1. Plan a trip with the assistant, or fill in the form directly. Drafts are private and are not in the sales queue.
2. Generate the editable summary. Check the route, dates, travellers, budget and preferences.
3. Submit the request. It receives a reference and enters Pending.
4. A Sama salesperson takes over. Their name appears in the conversation and the status changes to In progress.
5. Discuss details and attach files. Status updates appear as system boxes in the conversation. Messages are retained.
6. Sama prepares a quotation, including price/currency, details, inclusions, exclusions, terms and validity. The client can download its branded PDF.
7. The requester or company administrator submits that version for approval. The displayed approver list is saved against that version.
8. Each required person approves or rejects inside the portal. Progress is visible to relevant participants. A rejection requires a reason.
9. Only all approvals together produce Approved. Sama starts booking and later enters a supplier booking reference to confirm it.
10. Confirmed journeys can be closed; history remains available.

Quote revisions always create a new version and need fresh approvals. Expired quotes cannot start booking. A disabled or replaced approver never silently disappears: pending quotations must be revised/cancelled before removing that person's approval access. A user cannot record someone else's approval. Neither receiving an SMS/push nor opening a link counts as approval.

## Files and privacy

Both sides can attach PDF, JPG or PNG files, up to five files per message and 10 MB per file. These defaults intentionally exclude executable files and Office macros. Passport numbers, private traveller details and file contents are encrypted at rest by the application. Downloads require current permissions; there is no public uploads URL.

Mark traveller/passport attachments as private. Approvers do not automatically receive passport access. Sama internal notes are visible only to the current assignee and CEO. After reassignment, the previous salesperson loses request/file access.

## Notifications and correspondence

In-portal notifications are always available. Email and push require configuration and device permission. New requests notify the business mailbox; quotations and approval decisions notify participants. SMS is postponed. Device pushes contain a generic update message and a portal link rather than passport or payment information.

The CEO reviews new incoming mailbox replies before adding them to conversations. This avoids trusting a forged From address. The recorded conversation message identifies the email sender and staff reviewer. This first release deliberately uses reviewed incoming replies instead of automatic email impersonation. Attachments can be reviewed in IONOS and uploaded through the request interface.

Delivery status is visible in Operations. Uncertain delivery outcomes need a provider check before retrying, so an interrupted connection does not automatically create duplicate messages. Opt-in pushes are supported where the browser/device allows; on iPhone/iPad use the Home Screen app. In-portal notifications remain available even if device delivery fails.

## AI limits

The assistant uses public travel information and source links. It cannot reserve seats, guarantee prices, approve a quote or submit a request. Passport fields, attachments and financial records are not supplied to it. Known personal identifiers in typed chat are redacted before an API call; users should still keep all sensitive information in private profile/document fields.

The monthly allowance is shared across the entire application and capped at $20. The app reserves a conservative maximum per API call and reconciles completed calls from usage data. Timed-out calls retain their reservation because billing may have occurred. When the allowance is unavailable or a provider is down, the request form continues to work.

## Business defaults to review during live testing

- Passport copy optional; number, expiry, nationality, email and mobile mandatory for company profiles.
- Requesters who are designated approvers may approve their own request unless disabled in configuration.
- All company approvers must approve each version; no majority rule or automatic bypass.
- PDF/JPG/PNG only, 10 MB per file, five per message.
- No automatic document/history deletion until the retention policy is agreed.
- Email/push active only when configured; SMS postponed.
