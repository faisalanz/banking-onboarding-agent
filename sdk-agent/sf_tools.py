"""
Eastern Bank SDK agent - tool implementations.
Every Salesforce touch is a REST call with OAuth 2.0 client credentials.
Mirrors the FDE brief (Architecture B) with three production fixes learned
from the Agentforce build:
  1. Contacts are created WITH AccountId (FSC rejects private contacts)
  2. Case Product_Applied_For__c is a Lookup -> we resolve the Product2 Id
  3. Email goes through Salesforce's emailSimple action (org-wide address),
     so no separate EMAIL_URL service is needed.
"""
import os
import time
import datetime
import urllib.parse

import requests

SF_DOMAIN = os.environ["SF_DOMAIN"].rstrip("/")  # https://yourorg.my.salesforce.com
KYC_URL = os.environ["KYC_URL"].rstrip("/")      # https://eastern-kyc-mock-....herokuapp.com
API = "v60.0"

# ---- OAuth 2.0 client credentials flow, with simple token caching ----
_token_cache = {"token": None, "expires_at": 0.0}

def sf_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    r = requests.post(f"{SF_DOMAIN}/services/oauth2/token", data={
        "grant_type": "client_credentials",
        "client_id": os.environ["SF_CLIENT_ID"],
        "client_secret": os.environ["SF_CLIENT_SECRET"],
    }, timeout=15)
    
    if not r.ok:
        raise RuntimeError(f"SF token error {r.status_code}: {r.text}")
    _token_cache["token"] = r.json()["access_token"]

    _token_cache["expires_at"] = time.time() + 25 * 60  # refresh before typical 30m expiry
    return _token_cache["token"]

def sf_headers() -> dict:
    return {"Authorization": f"Bearer {sf_token()}", "Content-Type": "application/json"}

def soql(query: str) -> list:
    r = requests.get(f"{SF_DOMAIN}/services/data/{API}/query",
                     headers=sf_headers(),
                     params={"q": query}, timeout=15)
    r.raise_for_status()
    return r.json()["records"]

# ---- Cached org lookups (Eastern Bank account, product ids) ----
_lookups: dict = {}

def eastern_bank_account_id() -> str:
    if "account" not in _lookups:
        recs = soql("SELECT Id FROM Account WHERE Name = 'Eastern Bank' LIMIT 1")
        if not recs:
            raise RuntimeError("No 'Eastern Bank' Account found in the org")
        _lookups["account"] = recs[0]["Id"]
    return _lookups["account"]

def product_id_for(product_name: str):
    key = f"product:{product_name}"
    if key not in _lookups:
        safe = product_name.replace("'", r"\'")
        recs = soql(f"SELECT Id FROM Product2 WHERE Name = '{safe}' LIMIT 1")
        _lookups[key] = recs[0]["Id"] if recs else None
    return _lookups[key]

# ---- Decision logic (explicit for determinism; matches Apex ProductAdvisor) ----
def recommend(account_type: str, check_volume: str, wire_need: str) -> str:
    a, c, w = account_type.lower(), check_volume.lower(), wire_need.lower()
    if a == "interest":
        return "Premium Interest Checking"
    if a == "free" and c == "low" and w == "no":
        return "Free Basic Checking"
    if a == "free" and c == "low" and w == "yes":
        return "Free Premium Checking"
    return "Free Basic Checking"  # safe default for ambiguous combos

# ---- Tool implementations ----
def tool_get_recommendation(account_type, check_volume, wire_need):
    return {"productName": recommend(account_type, check_volume, wire_need)}

def tool_call_kyc(first_name, last_name, email, product_name):
    try:
        r = requests.post(f"{KYC_URL}/v1/verify",
                          json={"firstName": first_name, "lastName": last_name,
                                "email": email, "product": product_name},
                          timeout=15)
        if r.status_code >= 500:
            raise RuntimeError(f"KYC {r.status_code}")
        return r.json()  # {result, declineCode, declineReason}
    except Exception as e:
        # graceful degradation - never fabricate a result
        return {"result": "Service Unavailable", "declineCode": "SVC_DOWN",
                "declineReason": str(e)}

def tool_create_contact(first_name, last_name, email):
    body = {"FirstName": first_name, "LastName": last_name, "Email": email,
            "AccountId": eastern_bank_account_id()}  # FSC: no private contacts
    r = requests.post(f"{SF_DOMAIN}/services/data/{API}/sobjects/Contact",
                      headers=sf_headers(), json=body, timeout=15)
    r.raise_for_status()
    return {"contactId": r.json()["id"]}

def tool_create_case(contact_id, product_name, kyc_result, decline_reason, manual=False):
    body = {
        "Subject": "Account opening - KYC decline", "Status": "New", "Origin": "Web",
        "ContactId": contact_id, "Priority": "High" if manual else "Medium",
        "KYC_Decline_Reason__c": decline_reason, "KYC_Result__c": kyc_result,
        "Application_Date__c": datetime.date.today().isoformat(),
        "Application_Source__c": "Claude SDK Agent", "Doc_Upload_Sent__c": True,
    }
    pid = product_id_for(product_name)
    if pid:
        body["Product_Applied_For__c"] = pid  # Lookup field wants an Id
    r = requests.post(f"{SF_DOMAIN}/services/data/{API}/sobjects/Case",
                      headers=sf_headers(), json=body, timeout=15)
    r.raise_for_status()
    case_id = r.json()["id"]
    _notify_csr(case_id, decline_reason)  # demo parity: Marcus's bell rings here too
    return {"caseId": case_id}

def _notify_csr(case_id: str, decline_reason: str):
    """Best-effort custom notification to the CSR. Skipped if env vars unset."""
    notif_type = os.environ.get("SF_NOTIF_TYPE_ID")
    csr_user = os.environ.get("SF_CSR_USER_ID")
    if not notif_type or not csr_user:
        return
    try:
        requests.post(
            f"{SF_DOMAIN}/services/data/{API}/actions/standard/customNotificationAction",
            headers=sf_headers(),
            json={"inputs": [{
                "customNotifTypeId": notif_type,
                "recipientIds": [csr_user],
                "title": "KYC Decline - new application case (SDK agent)",
                "body": f"Application declined ({decline_reason}). Case created - please review.",
                "targetId": case_id,
            }]},
            timeout=15,
        )
    except Exception:
        pass  # notification is cosmetic; never fail the application over it

def tool_send_email(to, subject, body):
    """Send via Salesforce emailSimple so the verified org-wide address is the sender."""
    inputs = {"emailAddresses": to, "emailSubject": subject, "emailBody": body}
    sender = os.environ.get("EB_FROM_ADDRESS")
    if sender:
        inputs["senderType"] = "OrgWideEmailAddress"
        inputs["senderAddress"] = sender
    try:
        r = requests.post(
            f"{SF_DOMAIN}/services/data/{API}/actions/standard/emailSimple",
            headers=sf_headers(), json={"inputs": [inputs]}, timeout=15)
        ok = r.ok and all(item.get("isSuccess") for item in r.json())
        return {"sent": bool(ok)}
    except Exception:
        return {"sent": False}

def tool_create_task(case_id, email_ok=True):
    subj = "Automated outreach sent" if email_ok else "Outreach attempted (email failed)"
    r = requests.post(f"{SF_DOMAIN}/services/data/{API}/sobjects/Task",
                      headers=sf_headers(),
                      json={"WhatId": case_id, "Subject": subj, "Status": "Completed",
                            "ActivityDate": datetime.date.today().isoformat()},
                      timeout=15)
    r.raise_for_status()
    return {"taskId": r.json()["id"]}
