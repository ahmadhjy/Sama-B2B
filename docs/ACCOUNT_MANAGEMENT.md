# Administrator account management

Sign in as a Sama administrator and open **People & access**.

- **Change password** sets a new password with confirmation. Existing passwords are never displayed. For the main company owner, this updates the shared Accounting login through the signed bridge. For individual users it changes their HelloSama password. Existing sessions are invalidated (the administrator keeps their own current session when resetting their own password).
- **Delete account** asks you to type the exact login ID. It removes HelloSama access and hides the account from People & access. Conversations, requests and approval history remain. This is an access removal, not a personal-data erasure. Accounting client records, financial records and the Accounting login remain unchanged. Other company users retain access. Accounting sync cannot restore a removed owner automatically.
- You cannot delete yourself, a user with pending approvals, or a salesperson with unfinished assigned requests. Resolve that work first.
- Password changes and removals are recorded in the audit log without passwords.

## Deploy this update

Run the HelloSama update script to pull the change and apply its new user-field migration:

```bash
bash /home/Samatours2026/HelloSama/deploy/update.sh
```

Update the existing Accounting bridge to support shared-owner password resets:

```bash
/home/Samatours2026/HelloSama/.venv/bin/python /home/Samatours2026/HelloSama/deploy/install_accounting_bridge.py /home/Samatours2026/Sama-Acc
```

Reload the Accounting web app, then reload HelloSama. This bridge update adds no Accounting migration. Do not run the Accounting update script for this installation: it can discard the locally installed bridge registration. Keep the shared secret unchanged.

Test password changes using a controlled individual user and company owner. Verify the old password fails and the replacement works in both portals for the owner. Test deletion on a spare account; deletion deliberately retains historical data and cannot be undone from this screen.
