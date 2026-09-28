# Corporate Portal demonstration

Open http://127.0.0.1:8765/login/ and use the private `.demo-access.txt` file in the project folder for the shared local demo password. These accounts sign in directly, without creating anything in accounting. Never deploy the local demo database or credentials.

## Accounts to try

- `demo.ceo`: Sama administrator, with all three companies and all requests.
- `demo.sales`: Maya Salem, with her assigned requests and the unassigned queue.
- `demo.sales2`: Omar Nassar, with a different set of assigned requests.
- `demo.finance`: Sama accounting role; financial records require the accounting connection.
- `demo.owner`: Cedar & Co. administrator, company-wide requests, people and permissions.
- `demo.requester`: Rami Khoury, the company's salesperson/requester.
- `demo.approver`: Karim Mansour, an accountant with quotation approval permission.
- `demo.manager`: Yara Azar, a requester/sales-manager example with approval permission.
- `demo.accountant`: Lea Saab, accounting access without approval permission.
- `demo.horizon.owner`, `demo.horizon.sales`, `demo.horizon.hr`: Horizon Consulting's administrator, requester and HR approver.
- `demo.atlas.owner`, `demo.atlas.sales`, `demo.atlas.finance`: Atlas Medical's administrator, requester and finance approver.

All company profiles are complete with fictional values. These are local demonstration records, not financial accounts in Sama Accounting.

## Suggested screenshots

1. **Login:** Corporate Portal Login, Sama branding and the sign-in form.
2. **Overview as `demo.owner`:** populated company dashboard and recent requests.
3. **Bangkok team retreat, `HS-DEMO-0101`:** conversation, attached brief, quotation and partial approvals. Use `demo.approver` or `demo.manager` to see approval actions.
4. **Dubai partnership meetings, `HS-DEMO-0102`:** confirmed booking and completed approval trail.
5. **Paris technology conference, `HS-DEMO-0104`:** revised quotation with its earlier version preserved.
6. **People & access as `demo.owner`:** company roles and independent approval permissions.
7. **Request queue as `demo.sales`:** enquiries ready for a salesperson to take over.
8. **Plan a new trip as `demo.owner` or `demo.requester`:** prefilled assistant conversation beside an editable request summary.
9. **Overview as `demo.ceo`:** visibility across three fictional companies.

The showcase adds 18 requests covering every status, six sample attachments and four planning conversations. Earlier local demo and testing records are preserved.

Sample assistant messages, amounts and booking references are fictional, not live research or reservations. Sending a new assistant message uses the configured OpenAI integration. The showcase command makes no external API calls or notifications. Notification setup is postponed.

## Re-create missing examples locally

```powershell
.\.venv\Scripts\python manage.py seed_showcase
```

This requires local development with accounting, email and mailbox connections disabled. It reuses the private demo password, adds missing examples, and preserves existing requests and decisions. Re-running does not duplicate the showcase. It is not part of production deployment.
