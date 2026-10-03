# Roles and Permissions

This guide explains accounts, access and the boundaries between communities
in OpenZEV.

## Accounts and Access

Every account has one **platform role**:

| Platform role | Scope | Typical User | Purpose |
| --- | --- | --- | --- |
| **Admin** | Global system | Platform operator, IT | Full access to all ZEVs, settings, accounts |
| **User** | What it has access to | Everyone else | Manages, views or takes part in communities |

A **User** account can do nothing on its own. What it may do comes from its
access to each community, described next. An account with no community yet
can sign in but sees nothing to manage.

### Access per community: managers and viewers

What an account may do in a community comes from its **relation to that
community**, not from one role for the whole platform. One account can have
different relations in different communities — for example manage one ZEV and
rent a flat in another, or be a tenant in two communities.

| Relation | What it allows in that community |
| --- | --- |
| **Manager** | Everything a ZEV owner can do: participants, metering, tariffs, invoices, settings, and giving others access |
| **Issuer** or **representative** | The same as a manager, while the role lasts |
| **Viewer** | Sees everything a manager sees and may download and export, but changes nothing |
| **Participant** | Own consumption, own invoices and annual statement |
| **Former participant** | Own invoices that were sent, after leaving the community |

Managers and viewers get their access from the community's managers (or an
admin) under **ZEV settings → People & access** — see
[People & access tab](02-zev-setup.md#people-and-access-tab). Whoever creates a ZEV is its manager.
The login of the community's **issuer** and of its **representative toward the
grid operator** manages it for as long as the role lasts — see
[People & access tab](02-zev-setup.md#people-and-access-tab); a landowner gets no access by that
role. Participants get theirs by being linked to a participant entry.

## Admin Role

**Admins** have unrestricted access to the entire system.

### Admin Capabilities

- **Account Management:** Create, edit, remove user accounts
- **Access:** Make other accounts admins, and give access to any community
- **System Settings:** regional date formats, VAT rate configuration, feature flags, and OAuth providers
- **Overview hub:** KPIs, multi-ZEV oversight, all invoices, the platform audit log, and system health
- **Accounts:** user management and platform-wide API keys
- **Templates:** PDF invoice/contract/statement templates and system-wide email defaults

### Platform Overview

Accessible via **Platform → Overview**:

- System health and status
- Account count and active users
- Total invoices generated
- Email delivery metrics
- Recent alerts and issues

![Admin dashboard](screenshots/10-admin-dashboard.png)

### Who Should Be Admin?

- Platform owner or operator
- IT/system administrator
- Finance/compliance officer (for audit access)

> **Important:** Give admin access sparingly. It grants unrestricted power.

## Managers (ZEV Owners)

A **manager** runs a community. The ZEV's owner is always a manager; other
managers — a property management company, a co-owner — get access under
**ZEV settings → People & access**.

### Manager Capabilities

**Per managed ZEV:**
- Manage participants (add, edit, view)
- Configure metering points
- Import metering data
- View data quality reports
- Configure tariffs
- Generate and approve invoices
- Send invoices to participants
- Track email delivery
- Customize email templates
- Configure ZEV settings (billing interval, VAT number, etc.)
- Turn participant invoice access on or off, and revoke a printed access link
- Give other people access as manager or viewer

**Restrictions:**
- Cannot access other ZEVs (unless they have access there too)
- Cannot access admin settings
- Cannot manage global user accounts
- Cannot view other ZEV's metering data or invoices

### ZEV Scope

A manager is **scoped** to the ZEVs it has access to:

- **Single ZEV:** the manager sees one community only
- **Multiple ZEVs:** the community switcher lists each one
- Each ZEV is isolated—data from one ZEV is not visible in another

### Who Should Be a Manager?

- Community president or board representative
- Energy manager for a specific community
- Finance officer responsible for invoicing
- Metering and tariff specialist

## Participant Role

**Participants** are community members with read-only access to their own data.

### Participant Capabilities

The participant sidebar shows **Dashboard**, **My invoices**, and **Annual statement**; own consumption charts and trends stay reachable through the direct `/metering/chart` route.

- **Dashboard:** View own energy consumption/production overview
- **My invoices:** View and download own invoices (read-only; shows invoices even before a PDF exists)
- **Annual statement:** View their own annual statement and tax overview
- **Metering Data:** Direct route to own consumption charts and trends
- **Account Profile:** Update personal information

### Participant Restrictions

- Cannot see other participants' data
- Cannot see metering data from other ZEVs
- Cannot modify tariffs, metering points, or settings
- Cannot generate or approve invoices
- Cannot access admin features

### Who Are Participants?

- Household members with metering points
- Small businesses with energy meters
- Anyone with meter(s) in a ZEV community

### Reaching a Participant Without an Account

Participants do not have to hold an account to see their own bill. If the ZEV
has [participant invoice access](02-zev-setup.md#participant-access-from-the-invoice)
switched on, the QR code printed on an invoice opens **that one invoice** — no
username, no password, no session.

This is not a role. Whoever holds the printed invoice can open the page, and the
page is limited to what that sheet of paper already shows: the total, whether it
is paid, the line items, the consumption figures and the charts printed on the
same insights page. It cannot reach another invoice, and it cannot change
anything.

From there, **Send me a sign-in link** emails a one-time link to the address on
file, which does start a normal participant session with the ordinary
participant scoping above. The requester never names the destination address —
the invoice identifies who they are — so there is no way to use it to find out
whether an address has an account.

A ZEV owner or admin can revoke any printed link; see
[Invoice Management → Participant access links](09-invoice-management.md#participant-access-links).

## Accounts Without a Community

An account that is neither a manager, a viewer nor a participant anywhere has
no access to any community's data. That is the case for an account created on
**Platform → Accounts** before it is given access, an account whose
participant link was removed, or a self-registered account that never set up
its ZEV. Give it access under **ZEV settings → People & access**, or link it to a
participant. An admin can impersonate it, as any other account that is not an
admin.

## Access Control Matrix

| Feature | Admin | Manager (ZEV Owner) | Viewer | Participant |
| --- | --- | --- | --- | --- |
| **Participants** | View all | Manage in the ZEV | View in the ZEV | View self |
| **Metering Points** | View all | Manage in the ZEV | View in the ZEV | View own meters |
| **Metering Data** | View all | Import and view in the ZEV | View in the ZEV | View own readings |
| **Tariffs** | View all | Create/edit in the ZEV | View, download the overview | View only |
| **Invoices** | View all | Create, approve, send in the ZEV | View, download PDFs | View own only |
| **Email Templates** | Manage defaults | Customize in the ZEV | View | — |
| **Settings** | Global settings | ZEV settings, give access | View | Account profile |
| **Admin Panel** | Full access | — | — | — |

> **Note:** An account without a community has no access in any column above.

## Managing Accounts

**Only Admins** manage accounts and platform roles. Managers give access to
their own community under **ZEV settings → People & access**.

### The Accounts list

![Admin accounts page](screenshots/11-admin-accounts.png)

**Platform → Accounts → Users** lists every account on the platform, one row
each:

- **Account** — name, username, email and the account's **platform role**.
- **Communities** — one chip per community the account belongs to, marked
  *Manager*, *Viewer*, *Participant* or *Former participant*. An account that belongs to several communities
  still has a single row. Click a chip to open that community's Participants
  page.
- **Security** — which second factors the account has (authenticator app,
  passkey), or *No two-factor*; whether it is still within its grace period or
  overdue, while two-factor authentication is required (see below); and when it
  last signed in, or *Never signed in*.

Use **Search**, **Platform role**, **Community** and **Two-factor** to narrow
the list — the community filter finds everyone who has access or takes part
there, and the two-factor filter narrows to accounts that still need to set it
up. The **Never signed in** stat at the top counts accounts nobody has ever
signed into — useful for spotting a stale invitation or an account that can be
cleaned up. **Accounts without a community** counts the accounts that still
need access or a participant link.

> **Platform role vs. community access.** The platform role (Admin or User)
> belongs to the *account*. Which communities an account belongs to, and how,
> is set in each community — under **ZEV settings → People & access** for managers and
> viewers, on the **Participants** page for participants — not here.

### Change an Account's Role

1. Go to **Platform → Accounts → Users**
2. Click **Edit** on the account
3. Change the **Platform role** between Admin and User (and name or email if needed)
4. Click **Save account**

Changes take effect immediately. You cannot change your own role.

### Create a New Account

Click **New account** on **Platform → Accounts → Users** for an account that is
not tied to any community — a second administrator, a service account, or any
account you want ready before it is needed. Enter a username, email, first and
last name, and the platform role, then click **Create account**.

There is no password field: OpenZEV generates one and shows it once, with a
**Copy password** button — share it with the account holder however you
normally would. They set their own password the first time they sign in.

To create an account **for a specific participant**, use the community's
Participants page instead — see below.

### Give a Participant an Account

Accounts are attached to participants from the community that the participant
belongs to:

1. Switch to the community and open **Participants**
2. On the participant's card, open **More**
3. Choose **Send onboarding link** or **Copy onboarding link** (creates the
   account and gives the participant a sign-in link), or — as an admin —
   **Link existing** to attach an existing account — any account except an
   admin's, also one that is already a participant in another community, so a
   person who rents in two communities keeps one login
4. To detach an account again, choose **Unlink** (the account itself stays as it is)

### Other Account Actions

Open **More** on an account row for:

- **Impersonate** — view the platform as that account sees it, in every
  community it belongs to (any active account except an admin).
- **Reset two-factor** — removes the account's passkeys, authenticator app and
  recovery codes, so someone locked out can sign in with their password again.
- **View activity** — opens the platform audit log filtered to this account's
  own actions.
- **Sign out everywhere** — ends every session the account holds, on every
  browser and device, so it has to sign in again. Use it when you suspect
  someone else has access. It is recorded in the audit log and is not offered
  on your own row (use **Sign out other devices** on your account page).
- **Deactivate** — the account can no longer sign in, and every session it
  holds ends immediately. Its data and history are kept, and you can
  **Activate** it again later. Not offered on your own row: OpenZEV refuses to
  let you deactivate yourself, since it would sign you out with no way back in
  except another administrator.
- **Delete** — only available for accounts that do not belong to a community.
  Unlink the account from its participant first; an owner's account cannot be
  deleted while it owns a community.

## Data Privacy and Scoping

OpenZEV enforces data boundaries:

### Participant Privacy

- Participants can **only** view their own consumption and invoices
- They cannot see other participants' data in the same ZEV
- API access is also scoped—a participant token can only fetch own data

### ZEV Isolation

- A manager of ZEV A **cannot** see ZEV B's data unless it has access there too
- Tariffs, metering points, and invoices are entirely isolated by ZEV
- Admins can view all ZEVs but typically delegate operations to managers

### Audit Trail

Security-relevant and billing-relevant user actions are logged:
- Who did what (action)
- When (timestamp)
- What changed (old → new values)

Audit logs are visible to **admins** (all events, **Platform → Overview →
Audit log**) and to **ZEV owners** for their own communities (scoped events,
**Setup → Settings → Audit log**).

## Best Practices

**Principle of Least Privilege:**
- Assign the minimum role needed for the job
- Participants should not be admins
- Limit admin accounts to platform operators

**Separate Roles:**
- Use different user accounts for different roles
- Don't share admin accounts between people
- Create audit trail by attributing actions to individuals

**Regular Reviews:**
- Periodically review who has access to what
- Remove access when people leave the organization
- Audit role assignments for compliance

**Account Security:**
- Users should use strong passwords
- Turn on two-factor authentication under **My Account → Security** (see below)
- Don't write passwords down

## Two-Factor Authentication

Every user can protect their account with a **passkey**, an **authenticator app**, or both. Set them
up under **My Account → Security → Two-Factor Authentication**.

![Account security tab](screenshots/16b-account-security.png)

### Passkeys (no password needed)

A passkey lets you sign in with your fingerprint, face or device PIN — no password. It is
phishing-resistant: it only works on the real OpenZEV address.

1. Click **Add a passkey**, give it a name (for example "MacBook Touch ID"), and confirm on your device
2. Add a second one on another device, so a lost phone does not lock you out
3. Save the **recovery codes** shown once when you add your first factor

To sign in, click **Sign in with a passkey** on the login page. The button only appears in browsers
that support passkeys.

### Authenticator app

1. Click **Set up two-factor authentication**, scan the QR code with your authenticator app
   (Google Authenticator, Aegis, 1Password, …) or type the key in by hand
2. Enter the 6-digit code the app shows to confirm
3. Save the ten **recovery codes** if you have no other factor yet — each works a single time

Afterwards, signing in with your password asks for the 6-digit code as a second step. Use
**Use a recovery code instead** if you don't have your phone. The same code is asked when you sign in
through an emailed invoice link or onboarding link. Signing in through an external identity provider
is unaffected unless the administrator requires the provider to assert a second factor.

> **Note:** Adding a passkey protects your password too. Signing in with your password (or an
> emailed link) then asks for a second step: a recovery code if you only have a passkey, or the
> 6-digit code if you also have an authenticator app. The login page offers **Sign in with a passkey
> instead** at that point. Keep your recovery codes somewhere safe — they are what gets you in with a
> password if you can't use your passkey.

### Requiring it for everyone (administrators)

Under **Platform → System Settings → Security**, tick **Require two-factor
authentication for every account** and set a grace period in days. Users see a reminder on their
account page and a set-up screen they can postpone until the grace period ends. The period counts from
the later of the account's creation and the day you last changed the policy, so switching it on never
locks anyone out immediately. While it is required, nobody can remove their last factor.

To see who has not enrolled yet, go to **Platform → Accounts → Users**: an account the policy names
gets a badge in the Security column — "2FA required · due `<date>`" during the grace period, "2FA
overdue" once it has passed — and the **Two-factor** filter narrows the list to exactly those
accounts. The "Needs two-factor" stat at the top of the page counts them.

Once the grace period ends, an account with no factor is also refused any change it tries to make
through the API, not only in the web app — so this is enforced, not just suggested. Reading data is
never affected, and neither is an API key: a key cannot complete the enrolment ceremony this policy
pushes someone toward, so it is a separate credential this policy does not reach. An account whose
day-to-day access is entirely through an API key it minted before the policy applied to it is
therefore not forced to enrol by this alone.

### Locked out?

On the second step of a password sign-in, enter one of your recovery codes. If you have lost your devices and your recovery codes, ask an
administrator: **Platform → Accounts → Users → More → Reset two-factor** removes every passkey, the authenticator app
and all recovery codes for that user, and is recorded in the audit log. An administrator can never see
or recover your secrets, and cannot set up a factor on your behalf.

The server needs an encryption key (`MFA_ENCRYPTION_KEYS`) before authenticator apps can be enrolled
or a requirement can be set, and the passkey domain settings (`WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN`)
must match the address users open OpenZEV on. See `backend/.env.example` and the Helm chart README.

## Email Address and Sessions

### Changing your email address

Your email address is what you sign in with and where sign-in links are sent, so changing
it takes a few extra steps. Under **My Account → Profile → Email address**:

1. Click **Change email**, enter the new address and your **current password**
2. Open the confirmation link OpenZEV sends to the **new** address (valid for 24 hours)
3. Sign in again with the new address — the change signs you out everywhere

The old address is emailed afterwards, so a change you did not make does not go unnoticed. The
link works once, and stops working if your password or address changes before you use it.

Accounts that have no password — participants, who sign in with emailed links, and accounts that
only use an external identity provider — cannot do this themselves. For participants the address is
maintained by the community owner on the participant record; an administrator can change any
account's address under **Platform → Accounts → Edit**.

### Signing out other devices

Under **My Account → Security → Sessions**, **Sign out other devices** ends every session except the
one you are using. Do it if you lost a device or suspect someone else has access. There is no list
of individual devices — the action always covers all of them.

OpenZEV also emails you whenever how your account is secured changes — a passkey or authenticator
app added or removed, recovery codes regenerated, your password changed, or an administrator
resetting your two-factor authentication or signing you out everywhere. It always goes to your own
address, says what happened and when, and cannot be turned off — think of it as a smoke detector for
your account. If one of these arrives and you did not do it, change your password and check with
your administrator.

Sessions on other devices also end automatically when you:

- change your password (you stay signed in on the device you used),
- confirm an email change, or
- have your two-factor authentication reset by an administrator, or your account deactivated.

**Logout** in the user menu signs the account out on every device, including
the one you are using — you will have to sign back in everywhere. API keys are separate
credentials and stay valid — see [API keys](16-api-keys.md).

## Multi-ZEV Setups

If operating multiple communities:

**Admin perspective:**
- Can oversee all ZEVs
- Can give managers and viewers access to specific communities
- Can monitor cross-ZEV metrics and KPIs

**Manager, viewer and participant perspective:**
- The community switcher (sidebar top) lists every community your account
  relates to, with your relation (Manager, Viewer, Participant, Former
  participant) under each name
- The navigation follows the selected community: management pages for a
  manager or viewer, your dashboard and invoices for a participant, only your
  invoices for a former participant
- Each ZEV has isolated data
- With only one community there is nothing to switch, and the switcher is
  hidden

## Troubleshooting

### "Cannot access [feature]" (permission error)

Ask an admin to check your account's **Platform role** and communities under
**Platform → Accounts → Users**. If the role is wrong, they can change it there.

### "Cannot see other ZEVs"

**Expected behavior:** you see the communities you manage, view or take part
in — nothing else.

**If you need access:** ask a manager of that ZEV (or an admin) to give you
access under **ZEV settings → People & access**.

### "User cannot login"

**Possible causes:**
- The onboarding link was never used, has expired, or was revoked
- User account deactivated
- Password forgotten — there is no self-service password reset

**Fix:**
1. Check the account under **Platform → Accounts → Users**: is it active, and
   has it ever signed in?
2. **Participant:** the community owner sends or copies the onboarding link
   again from the participant's card (**More**). It signs them in, and they
   choose a new password.
3. **Owner or admin who forgot their password:** someone with server access
   sets a new one on the command line (the user then signs in with it):

   ```bash
   docker compose exec backend python manage.py changepassword <username>
   ```

   The username is shown in the **Account** column of the accounts list.
4. **Locked out by two-factor:** see [Locked out?](#locked-out)

## Next Steps

- **User management:** Admin controls at **Platform → Accounts**
- **ZEV settings:** [ZEV Setup and Configuration](02-zev-setup.md)
- **Participant management:** [Managing Participants](03-participant-management.md)
