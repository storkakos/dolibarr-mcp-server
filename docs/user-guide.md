# User guide: the Dolibarr assistant

The **Dolibarr assistant** lets you ask questions about Dolibarr in a chat, in plain language:
"Which invoices of North Customer Ltd are unpaid?", "Show me the open orders", "Which products do
we sell?". It looks the answers up in Dolibarr for you.

This guide shows you how to log in, connect the assistant to your Dolibarr account once, and ask
good questions. It takes about five minutes.

> The screenshots come from a test system with made-up customers. Your company's addresses, names
> and button labels may differ slightly. Your administrator tells you the address of the chat.

## Contents

1. [What the assistant can and cannot do](#1-what-the-assistant-can-and-cannot-do)
2. [Log in to the chat](#2-log-in-to-the-chat)
3. [Connect to Dolibarr (once)](#3-connect-to-dolibarr-once)
4. [Ask questions](#4-ask-questions)
5. [Your connection](#5-your-connection)
6. [Privacy](#6-privacy)
7. [Questions and problems](#7-questions-and-problems)

## 1. What the assistant can and cannot do

**It can:**

- find and read third parties (customers, prospects, suppliers)
- list and read customer invoices, for example the unpaid ones
- list proposals, customer orders, products and services
- tell you which Dolibarr account it is using and which rights that account has
- read other Dolibarr data through Dolibarr's REST API, if you have the rights for it

**It cannot:**

- **change anything in Dolibarr.** It only reads. It cannot create, change, validate, pay or delete
  anything. Do that in Dolibarr as usual.
- **see more than you.** It works with your own Dolibarr account and your own Dolibarr rights. What
  you cannot open in Dolibarr, the assistant cannot read either. It does not even offer the lookups
  you have no right for: without the right to read invoices, it has no invoice lookup.

The assistant is an AI. It is usually right, but it can misread or summarise wrongly. Before you
act on an answer, for example send a reminder to a customer, open the record in Dolibarr and check.

## 2. Log in to the chat

Open the chat address your administrator gave you, for example `https://chat.example.com`, and
click **Sign in with Keycloak** (your company may call this button differently, for example after
its login portal).

![Chat login page with "Sign in with Keycloak"](images/user-guide/01-librechat-login.png)

Log in with your usual company account. If you are already logged in elsewhere in the company, this
page may be skipped.

![Company login page: username or email, password](images/user-guide/02-keycloak-login.png)

You are now in the chat. New chats normally start with the **Dolibarr assistant** already selected
(at the top) and with **Dolibarr** switched on (the small **Dolibarr** chip in the input field):

![Chat start page with "Dolibarr assistant" selected and the Dolibarr chip in the input field](images/user-guide/03-librechat-home.png)

## 3. Connect to Dolibarr (once)

The first time, the chat needs your permission to read Dolibarr for you. You give it once; after
that it works in the background.

**1. Start the connection.** Either ask the assistant a question, and it shows a **Sign-in**
button right in the chat:

![Chat: "Requires Authentication in dolibarr" with a Sign-in button](images/quick-start/09-librechat-sign-in-in-chat.png)

or click the **MCP Settings** icon in the left bar and then the **Connect** icon (the plug) next to
**Dolibarr**:

![MCP Servers panel: Dolibarr with an orange dot and the Connect icon](images/quick-start/04-librechat-mcp-servers.png)

The chat shows the Dolibarr address. Click **Continue with OAuth**:

![Dialog "Connect dolibarr" with the Continue with OAuth button](images/quick-start/05-librechat-connect-dialog.png)

**2. Log in to Dolibarr.** A new browser tab opens with Dolibarr's login page. Log in as you do
every day (with your company account: **Use OpenID to login**). If you are still logged in from
step 2, you do not need to type your password again.

**3. Allow the connection.** Dolibarr asks whether the chat may access Dolibarr on your behalf.
Check three things:

- the **User**: your own name and login
- **Returns to**: your company's chat address
- the list of rights: these are your own Dolibarr rights, and the chat gets exactly these

Then click **Allow**. The tab closes by itself.

![Dolibarr page "Allow access?": application, return address, resource, your user, your rights, Allow and Deny](images/quick-start/06-restoauth-consent.png)

> **Only click Allow if you started the connection yourself, just now.** If you got this page
> through a link from someone else, click **Deny** and tell your administrator.

**4. Done.** The dot next to **Dolibarr** turns green. If you had asked a question in step 1, ask
it again.

![MCP Servers panel: Dolibarr with a green dot](images/quick-start/07-librechat-connected.png)

## 4. Ask questions

Start a **new chat** for each topic (the pencil icon at the top left). Make sure **Dolibarr
assistant** is selected at the top and the **Dolibarr** chip is in the input field.

![Model menu with "Dolibarr assistant"](images/user-guide/04-model-menu.png)

If you use another model, switch Dolibarr on yourself: click **+** in the input field, type
`Dolibarr` in the search field and pick **Dolibarr** under **MCP Servers**.

![The + menu of the input field, searched for Dolibarr, with Dolibarr under MCP Servers](images/user-guide/05-plus-menu-mcp-servers.png)

### Examples

**Find customers:**

![Question "Which customers can I see?" and the answer with North Customer Ltd](images/user-guide/06-customers.png)

**Unpaid invoices:**

![Question "Which invoices are unpaid? Answer with a short table." and a table with the invoice](images/user-guide/07-unpaid-invoices.png)

**Products and services:**

![Question "Which products and services do we sell?" with a list of two products](images/user-guide/08-products.png)

Above each answer you see which Dolibarr lookup the assistant used, for example **Ran
list_invoices in dolibarr**. Click the arrow on the right to see exactly what it asked Dolibarr and
what came back.

More questions that work well:

| You want | Ask |
|---|---|
| One customer | "Show me the details of North Customer Ltd." |
| Invoices by status | "Which invoices are unpaid?", "Which invoices were paid?" |
| One invoice | "What is in invoice `IN<YYMM>-0001`, and is it paid?", with your invoice's real reference |
| Proposals and orders | "Which proposals are open?", "Show me the latest orders." |
| Products | "Which services do we sell, and at what price?" |
| Check the account | "Who am I in Dolibarr, and what may I read?" |

For other questions the assistant can also look up Dolibarr's other data (for example contacts or
projects), if you have the rights for it. If an answer looks incomplete, ask more precisely or check
in Dolibarr.

### Tips

- **Name the customer or the reference** when you mean one record, for example an invoice like
  `IN<YYMM>-0001` (`<YYMM>` is the invoice's year and month). It is faster and more exact than
  describing it.
- **Say what you want back:** "as a table", "only the totals", "the five newest".
- **Ask follow-up questions** in the same chat: "And which of these are older than 30 days?"
- **Large lists are cut off.** The assistant reads at most a fixed number of rows per lookup (50 by
  default). Narrow the question ("only unpaid", "only this customer") if you need everything.

### It does not change anything

If you ask it to change something, it tells you that it cannot:

![Question asking to mark an invoice as paid: the assistant finds the invoice, says its tools only read, and that you mark it as paid in Dolibarr](images/user-guide/09-read-only.png)

### What you have no right for

If your Dolibarr account may not read something, the assistant cannot read it either. For a user
without the right to read invoices, it has no invoice lookup at all and says so:

![A user without the invoice right asks for unpaid invoices; the assistant answers that it has no access to invoice data because the user has no right to read invoices](images/user-guide/10-no-invoice-right.png)

Ask your administrator if you need the right.

## 5. Your connection

- **How long it lasts.** The connection ends after 90 days, or after 30 days without use. You then
  connect again as in [section 3](#3-connect-to-dolibarr-once).
- **If your Dolibarr rights change**, the assistant follows within a minute, because it always asks
  Dolibarr with your account. If your Dolibarr account is disabled, all your connections end at
  once.
- **To disconnect** in the chat: **MCP Settings** icon → **Revoke** (the red icon next to
  **Dolibarr**).
- **To disconnect** in Dolibarr: open your own user card (click your name at the top right, then
  **Card** in the menu that opens), then the tab **Connected applications**. It lists every
  application connected to your account, since when, and how long the connection stays valid
  without use. Click **End connection**.

![Dolibarr user card, tab Connected applications: LibreChat MCP Client with the End connection button](images/user-guide/11-dolibarr-connected-applications.png)

Dolibarr confirms with **Connection ended**, and the application disappears from the list. The chat
loses its access; to use the assistant again, connect again as in
[section 3](#3-connect-to-dolibarr-once).

![Tab Connected applications after ending the connection: "Connection ended" and no connected applications](images/user-guide/12-connection-ended.png)

## 6. Privacy

- The chat never sees your Dolibarr password. Dolibarr gives it a token for your account instead,
  which you can withdraw at any time (section 5). The assistant uses it only to read.
- Every lookup the assistant makes in Dolibarr is recorded with your login, the time and what was
  looked up. The token itself is never recorded.
- Your questions and the data Dolibarr returns are sent to the AI model your company has set up for
  the chat. Ask your administrator if you are unsure which data may be used there.

## 7. Questions and problems

| Problem | What to do |
|---|---|
| The assistant answers without looking anything up, or says it has no access to Dolibarr | Check that the **Dolibarr** chip is in the input field (section 4), then ask again in a new chat. |
| The chat keeps showing **Sign-in** or the dot next to **Dolibarr** stays orange | Connect again (section 3). If it keeps happening, tell your administrator. |
| The **Allow access?** page has only a **Deny** button and says your user may not connect applications (see below) | Your Dolibarr account lacks the right to connect the assistant. Click **Deny** and ask your administrator. |
| Dolibarr shows **another person's name** on the **Allow access?** page | Click **Deny**. Your browser is still logged into Dolibarr as someone else: log out of Dolibarr, then connect again. |
| The Dolibarr login with your company account fails | Your Dolibarr user may be missing or disabled. Tell your administrator. |
| The assistant says it cannot read invoices, orders or something else | Your Dolibarr account has no right for it (section 4, "What you have no right for"). |
| No results for a customer you know exists | Check the spelling. If it is right, your Dolibarr account may not see that customer, for example because you are not its sales representative; check in Dolibarr. |
| The answer seems wrong | Open the record in Dolibarr and check. Click the arrow next to **Ran ... in dolibarr** to see what Dolibarr actually returned. |
| Logging in to the chat fails several times in a row | Wait five minutes and try again: the chat blocks repeated logins for a short time. |

Without the right to connect applications, the **Allow access?** page looks like this:

![Dolibarr page "Allow access?" with the message that the user may not connect applications and only a Deny button](images/user-guide/13-consent-without-right.png)

For anything else, contact your Dolibarr administrator.
