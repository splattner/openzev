# Connecting an AI Assistant

OpenZEV can answer questions about your own data through an AI assistant —
Claude Code, Claude Desktop, Cursor, n8n, or any other client that speaks the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP). Instead of
clicking through the readiness cockpit, invoice detail, import logs and audit
log yourself, you ask in plain language: *"Is Q2 ready to bill for ZEV
Sonnenhof?"*, *"Why is this invoice higher than last quarter?"*, *"What went
wrong in yesterday's import?"*

The assistant sees exactly what your account can see in the API — nothing
more — and every question it asks OpenZEV is recorded in the audit log.

## Privacy note

Enabling this feature lets the signed-in user send OpenZEV data — participant
names, consumption figures, invoice amounts, audit history — to whichever LLM
provider the assistant uses, which is very likely a third party outside
Switzerland. Only enable it if that is acceptable for your community, and only
give a key to an assistant you trust with that data.

The MCP endpoint is **read-only** in this release: no tool can create,
change, approve, send or delete anything.

## Enabling it

An administrator must turn the feature on first — it is off by default:

1. Open **Platform → System Settings → Functions**.
2. Enable `mcp_server_enabled`.

While the flag is off, the MCP endpoint does not exist as far as any caller
can tell (`404`, whether or not they are signed in).

## Creating a key for the assistant

The assistant authenticates the same way a script does — see
[API Keys](16-api-keys.md) for the full picture. For an assistant:

1. Open **Account → API keys**.
2. Choose **New API key**.
3. Give it a name that says what it's for — `claude-code-mcp` beats `key 3`.
4. Tick **Read-only key**. Every tool in this release only reads, so a
   read-only key loses nothing and keeps the credential's blast radius small
   if it ever leaks.
5. Choose **Create key** and copy the value shown — it is not shown again.

Only `admin` and `zev_owner` accounts can use the MCP endpoint. A
participant's key is refused with `403`.

## Connecting a client

The endpoint is `https://<your-openzev-host>/api/v1/mcp/`, speaking MCP's
*Streamable HTTP* transport. Send the key as a bearer token.

### Claude Code

```bash
claude mcp add --transport http openzev \
  https://your-openzev.example.com/api/v1/mcp/ \
  --header "Authorization: Bearer ozv_3f9a1c04b7e2_kR8vN2pQ..."
```

### Generic MCP client configuration

Most desktop clients (Claude Desktop via a local HTTP-to-stdio bridge, Cursor,
…) take a JSON block naming the server:

```json
{
  "mcpServers": {
    "openzev": {
      "url": "https://your-openzev.example.com/api/v1/mcp/",
      "headers": {
        "Authorization": "Bearer ozv_3f9a1c04b7e2_kR8vN2pQ..."
      }
    }
  }
}
```

### n8n

Add an **MCP Client** node, set its **Endpoint** to
`https://your-openzev.example.com/api/v1/mcp/`, and set **Authentication** to
a header credential: `Authorization: Bearer ozv_3f9a1c04b7e2_kR8vN2pQ...`.

## What you can ask

Once connected, the assistant has ten tools. You do not need to know their
names — asking a normal question is enough — but knowing what exists helps
you phrase a better question:

| Tool | Answers |
| --- | --- |
| `list_zevs` | Which ZEVs can I see? (call this first to get a ZEV's id) |
| `list_participants` | Who is in this ZEV, since when, and which metering points are they assigned to? (names and dates only — no email, phone, address or IBAN) |
| `period_readiness` | Can this billing period be invoiced, and what is blocking it? |
| `find_invoices` | Which invoices match this participant / period / status? |
| `explain_invoice` | Break one invoice down into its line items, and compare it with the participant's previous invoice |
| `import_triage` | What happened in recent metering imports, and what went wrong? |
| `consumption_summary` | Aggregated consumption, production and self-consumption over a date range |
| `consumption_profile` | A participant's average day: how much they use in each hour, and how much of it comes from the ZEV's own solar |
| `data_gaps` | Which metering points are missing readings, and where? |
| `audit_query` | Who did what, and when? |

Example questions:

- "List the ZEVs I have access to."
- "Is the current period ready to bill for ZEV Sonnenhof?"
- "Who are the current participants of ZEV Sonnenhof, and which meters do they have?"
- "Find Anna Muster's invoices from this year."
- "Explain invoice OZV-00013 — why did it go up from last quarter?"
- "What errors came up in yesterday's metering import?"
- "How much energy did ZEV Sonnenhof self-consume in August, by day?"
- "When in the day does Anna Muster use the most electricity, and how much of that is covered by solar?"
- "Which metering points have gaps in the last 30 days?"
- "Who approved invoices for ZEV Sonnenhof last week?"

## Limits

- **Read-only.** No tool changes anything. A future release may add write
  tools (approving or sending invoices) with an explicit confirmation step.
- **No raw meter data.** Consumption is aggregated into daily or monthly
  buckets; the underlying 15-minute readings are not exposed through MCP.
- **Scoped to your account.** An assistant connected with a ZEV owner's key
  sees only that owner's ZEVs — the same tenant isolation that protects the
  REST API protects MCP, because MCP tools call the same REST endpoints
  internally.
- **Bearer-token clients only, for now.** The endpoint accepts a static API
  key, not an OAuth login. Connectors that only support OAuth (such as
  claude.ai's custom connectors) cannot connect yet.
- **Lists are capped.** A question that would return hundreds of rows comes
  back truncated with a note saying so — narrow the question (a shorter date
  range, a specific participant) rather than asking for everything at once.

## Revoking access

Revoke the key the same way you would revoke any other API key: **Account →
API keys → Revoke**. It takes effect on the assistant's next request. See
[Revoking a key](16-api-keys.md#revoking-a-key) for the full picture,
including how an administrator can revoke it on your behalf.

## Audit trail

Every tool call the assistant makes is recorded in the audit log as an
`mcp.tool.call` event, naming the tool, the arguments, the key that was used
(by its prefix), and the ZEV it concerned (when the question named one you can
see). The event details show source `mcp`. To see exactly what an assistant
looked at, filter the audit log by action type `mcp.tool.call` — or ask the
assistant itself, since `audit_query` can answer that question too.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `404` on the endpoint | `mcp_server_enabled` is off — ask an administrator to enable it. The endpoint answers `404` to everyone while the flag is off, so this is the first thing to check. |
| `401` | Missing, wrong, revoked or expired key. Same causes as any other API key — see [API Keys → Troubleshooting](16-api-keys.md#troubleshooting). |
| `403` | You are signed in as a participant, or your key's account role changed. Only `admin` and `zev_owner` can use MCP. |
| The assistant says a tool failed with "Permission denied" or "not found" | You (or the assistant) named a ZEV or invoice your account cannot see. This is the same scoping the REST API enforces — it is not a bug. |
| Answers feel stale | Ask the assistant to call the tool again — MCP calls always read live data, there is no caching layer of its own. |
