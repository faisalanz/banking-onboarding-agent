# Eastern Bank Onboarding Agent — Anthropic SDK build (Architecture B)

Claude is the orchestration brain outside the org. Same Orchestrator decomposition
as the Agentforce build, but the tool loop, state, and prompts are yours. Every
Salesforce touch is a REST call authenticated with OAuth 2.0 client credentials.

## What's different from the FDE brief's listing

- Model updated to `claude-sonnet-4-6` (current as of June 2026)
- `tool_create_contact` sets `AccountId` (Eastern Bank) — FSC rejects private contacts
- `tool_create_case` resolves the Product2 **Id** for the `Product_Applied_For__c` lookup
- Email is sent through Salesforce's `emailSimple` REST action using your verified
  org-wide address — no separate EMAIL_URL service required
- Marcus's custom notification fires from `create_case` (optional, env-driven) so the
  console-alert demo beat works identically in both builds
- SOQL lookups are cached; OAuth token is cached and refreshed

## One-time setup: Connected App (client credentials)

1. Setup → App Manager → **New Connected App** (if your org shows "External Client
   Apps", either create one there with the same options or use the dropdown to
   create a legacy Connected App)
2. Enable OAuth Settings:
   - Callback URL: `https://login.salesforce.com/services/oauth2/callback` (unused, required field)
   - OAuth Scopes: **Manage user data via APIs (api)**
   - Check **Enable Client Credentials Flow** (uncheck "Require PKCE" if it blocks saving)
3. Save → **Continue** → it takes a few minutes to propagate
4. **Manage Consumer Details** → copy Consumer Key (`SF_CLIENT_ID`) and Consumer
   Secret (`SF_CLIENT_SECRET`)
5. Back on the app → **Manage** → **Edit Policies** →
   - Permitted Users: "Admin approved users are pre-authorized" is fine
   - **Client Credentials Flow → Run As**: pick your admin user (demo shortcut:
     inherits full access, so none of the agent-user permission battles apply.
     For production you'd use a least-privilege integration user — that asymmetry
     is literally the Governance row of the brief's §7 comparison table.)
6. `SF_DOMAIN` = Setup → My Domain → your `https://...my.salesforce.com` URL

## Run it

```bash
cd eastern-sdk-agent
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your values
python agent.py
```

Smoke test the auth alone before chatting:

```bash
curl -X POST "$SF_DOMAIN/services/oauth2/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=$SF_CLIENT_ID" -d "client_secret=$SF_CLIENT_SECRET"
# expect an access_token JSON; an error here means Connected App config, not code
```

## Demo runbook (same as §8)

Run `python agent.py`, then: "I want to open a checking account" → free →
"some" (expect the re-ask) → "just a few" → yes wires → expect Free Premium
Checking → agree → Sarah Lee + an inbox you control. The terminal prints every
tool call and result as it happens — that running trace IS the demo for this
build: the audience literally watches the orchestration loop think.

Resilience path: `curl -X POST <KYC_URL>/admin/mode/error`, re-run, and watch
`call_kyc` return Service Unavailable and the agent take the graceful path
(case created, no email, "under manual review"). Reset: `/admin/mode/fail`.

## Talking points vs the Agentforce build (brief §7)

- The decision logic here is ~10 lines of plain Python — unit-testable in CI
  with zero org dependency
- All governance is opt-in: the Run As user IS the security model
- Every turn re-sends full conversation state — that's the ~9.5k vs ~1.8k token
  trade in the brief's table
- Portability: point SF_DOMAIN at any org, or swap Salesforce for any CRM with
  a REST API, without touching the reasoning
