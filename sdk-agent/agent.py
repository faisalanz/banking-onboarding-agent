"""
Eastern Bank Onboarding Agent - Anthropic SDK build (Architecture B).
Claude is the orchestration brain outside the org; every Salesforce touch is a
REST call. Run:  python agent.py
"""
import json

import anthropic
from dotenv import load_dotenv

load_dotenv()

import sf_tools  # noqa: E402  (needs env loaded first)

USAGE = {"input": 0, "output": 0, "calls": 0}

MODEL = "claude-sonnet-4-6"

TOOLS = [
    {"name": "get_recommendation",
     "description": "Map the 3 qualifying answers to a checking product.",
     "input_schema": {"type": "object", "properties": {
         "account_type": {"type": "string", "enum": ["free", "interest"]},
         "check_volume": {"type": "string", "enum": ["low", "high"]},
         "wire_need": {"type": "string", "enum": ["yes", "no"]}},
         "required": ["account_type", "check_volume", "wire_need"]}},
    {"name": "call_kyc",
     "description": "Run the required KYC compliance check for the applicant.",
     "input_schema": {"type": "object", "properties": {
         "first_name": {"type": "string"}, "last_name": {"type": "string"},
         "email": {"type": "string"}, "product_name": {"type": "string"}},
         "required": ["first_name", "last_name", "email", "product_name"]}},
    {"name": "create_contact",
     "description": "Create the applicant's Contact record in Salesforce.",
     "input_schema": {"type": "object", "properties": {
         "first_name": {"type": "string"}, "last_name": {"type": "string"},
         "email": {"type": "string"}},
         "required": ["first_name", "last_name", "email"]}},
    {"name": "create_case",
     "description": "Create the KYC decline Case linked to the Contact.",
     "input_schema": {"type": "object", "properties": {
         "contact_id": {"type": "string"}, "product_name": {"type": "string"},
         "kyc_result": {"type": "string"}, "decline_reason": {"type": "string"},
         "manual": {"type": "boolean"}},
         "required": ["contact_id", "product_name", "kyc_result", "decline_reason"]}},
    {"name": "send_email",
     "description": "Send an email to the applicant from Eastern Bank.",
     "input_schema": {"type": "object", "properties": {
         "to": {"type": "string"}, "subject": {"type": "string"},
         "body": {"type": "string"}},
         "required": ["to", "subject", "body"]}},
    {"name": "create_task",
     "description": "Log the outreach Task on the Case. Set email_ok=false if the email failed.",
     "input_schema": {"type": "object", "properties": {
         "case_id": {"type": "string"}, "email_ok": {"type": "boolean"}},
         "required": ["case_id"]}},
]

DISPATCH = {
    "get_recommendation": sf_tools.tool_get_recommendation,
    "call_kyc": sf_tools.tool_call_kyc,
    "create_contact": sf_tools.tool_create_contact,
    "create_case": sf_tools.tool_create_case,
    "send_email": sf_tools.tool_send_email,
    "create_task": sf_tools.tool_create_task,
}

SYSTEM = """You are an Eastern Bank onboarding agent and the single point of contact.
Ask the three qualifying questions one at a time (free vs interest; check volume
low/high; wires yes/no). If an answer is ambiguous, re-ask ONCE with the options;
if still unclear, use the safe default and say so explicitly. After you have all
three, call get_recommendation and present the product with a warm rationale. On
agreement, collect first/last name + email, read the email back to confirm, and
call call_kyc.

If the KYC result is Fail or Manual Review: call create_contact, then create_case
(manual=true only for Manual Review), then write a warm <150 word email to the
applicant explaining their application for the product was not approved due to the
decline reason. Offer exactly two options: call the bank, or upload documents
online. Do not include legalese or apologize excessively. Do not include a subject
line in the body. Sign off as "The Eastern Bank Team". Send it with send_email
(subject: "Next steps for your Eastern Bank application, <FirstName>"), then call
create_task (email_ok=false if send_email reported sent=false).

If the result is Service Unavailable: create_contact, create_case with
kyc_result="Service Unavailable", skip the email, and tell the customer the
application is received and under manual review.

Never fabricate a KYC result or a product you were not given. Never reveal the
KYC outcome to the customer - they are told only that the application was received
and an email with next steps is on the way (or that it is under manual review for
the service-unavailable path). End by thanking the customer."""


def run_turn(messages: list) -> anthropic.types.Message:
    """The orchestration loop: keep going while Claude wants tools."""
    client = anthropic.Anthropic()
    while True:
        resp = client.messages.create(model=MODEL, max_tokens=1024,
                                      system=SYSTEM, tools=TOOLS,
                                      messages=messages)

        USAGE["input"] += resp.usage.input_tokens
        USAGE["output"] += resp.usage.output_tokens
        USAGE["calls"] += 1
        print(f"  [usage] call {USAGE['calls']}: in={resp.usage.input_tokens} "
              f"out={resp.usage.output_tokens} | session total="
              f"{USAGE['input'] + USAGE['output']}")

        if resp.stop_reason != "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            return resp
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                print(f"  [tool] {block.name}({json.dumps(block.input)})")
                try:
                    out = DISPATCH[block.name](**block.input)
                except Exception as e:  # surface failures to the model, never crash
                    out = {"error": str(e)}
                print(f"  [tool] -> {json.dumps(out)}")
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(out)})
        messages.append({"role": "user", "content": results})


def main():
    print("Eastern Bank Onboarding Agent (Claude SDK build). Type 'quit' to exit.\n")
    messages: list = []
    while True:
        user = input("You: ").strip()
        if not user:
            continue
        if user.lower() in {"quit", "exit"}:
            print(f"\nSession: {USAGE['calls']} API calls, "
                  f"{USAGE['input']} input + {USAGE['output']} output = "
                  f"{USAGE['input'] + USAGE['output']} tokens")
            break
        messages.append({"role": "user", "content": user})
        resp = run_turn(messages)
        text = "".join(b.text for b in resp.content if b.type == "text")
        print(f"\nAgent: {text}\n")


if __name__ == "__main__":
    main()
