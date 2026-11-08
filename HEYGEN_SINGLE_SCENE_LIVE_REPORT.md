# HeyGen Single-Scene Live Test Report (Scene 1)

**Execution Date:** 2026-10-07  
**Authorization Scope:** Exactly 1 Paid Submission Attempt for `scene_1` (Arabic `ar-SA`)  
**Status:** Pre-Flight Halted — Account API Wallet Balance Insufficient ($0.00 USD)

---

### Executive Summary

Following the user's notification of HeyGen wallet funding, a strict pre-flight read-only check was executed in accordance with **Section 1 of the Authorization Protocol**:
> *"Confirm: remaining_balance > 0 OR remaining_quota > 0. If the account is still unfunded: STOP. Do not submit generation."*

The read-only account query was dispatched to `GET https://api.heygen.com/v3/users/me` and `GET https://api.heygen.com/v2/user/remaining_quota` using the configured API credentials.

**Findings:**
1. Authentication was successful (`HTTP 200`).
2. Target account: `alimostafaalimahmoud@gmail.com`
3. Billing Type: `wallet`
4. **`wallet.remaining_balance`**: **`$0.00 USD`**
5. **`remaining_quota`**: **`0`**
6. Brody avatar (`469ba809c9f6441ba74a580058d41c4b`): Verified available.
7. Arabic audio CDN asset: Verified accessible (HTTP 200, 50,112 bytes).
8. `scene_1.job.json`: Verified `job_id == null` (no in-flight job exists).

Because the API balance remains `$0.00 USD` and quota is `0`, the generation process was **IMMEDIATELY HALTED** prior to submitting `POST /v2/video/generate`. Zero video generation calls were dispatched.

---

### Comparison of Attempts

| Parameter | Attempt 1 (Initial Run) | Attempt 2 (Resume Check 1) | Attempt 3 (Resume Check 2) |
| :--- | :--- | :--- | :--- |
| **Timestamp** | 2026-10-07 23:35:05 UTC+3 | 2026-10-07 23:41:45 UTC+3 | 2026-10-07 23:48:32 UTC+3 |
| **Action** | Paid POST to `/v2/video/generate` | Pre-flight Query (`/v3/users/me`) | Pre-flight Query (`/v3/users/me`) |
| **Scene Target** | `scene_1` ONLY | `scene_1` ONLY | `scene_1` ONLY |
| **Avatar** | Brody (`469ba809c9f6441ba74a580058d41c4b`) | Brody | Brody |
| **Audio CDN URL** | Reused `970ca4f2fde24a6e9caeb61488356148` | Reused `970ca4f2fde24a6e9caeb61488356148` | Reused `970ca4f2fde24a6e9caeb61488356148` |
| **HTTP Response** | `402 PAYMENT REQUIRED` | `200 OK` (Account Query) | `200 OK` (Account Query) |
| **Reported Wallet** | `$0.00 USD` | `$0.00 USD` | **`$0.00 USD`** |
| **Reported Quota** | `0` | `0` | **`0`** |
| **Outcome** | Rejected by HeyGen billing guard | Halted by Section 2 safety rule | **Halted by Section 1 safety rule** |
| **Submissions Made** | 1 (failed with 402) | 0 | **0** |
| **Credits Consumed**| 0 | 0 | **0** |

---

### Root Cause Analysis & Resolution Guide

HeyGen operates two distinct billing repositories:
1. **Web Studio Credits (Creator/Team Workspace)**: Used inside the browser interface (`app.heygen.com`) for manual project creation.
2. **API Wallet (`billing_type: wallet`)**: Specifically required by the REST API (`api.heygen.com/v2/video/generate`).

When querying HeyGen API with `HEYGEN_API_KEY`:
```json
{
  "data": {
    "billing_type": "wallet",
    "email": "alimostafaalimahmoud@gmail.com",
    "wallet": {
      "currency": "usd",
      "remaining_balance": 0.0
    }
  }
}
```

To resolve this so the API can generate `scene_1`:
1. **Option A (If you funded the API Wallet on a different account or workspace)**:
   - Go to `https://app.heygen.com/settings?nav=API` in the funded workspace.
   - Generate a new API Key and replace `HEYGEN_API_KEY` in `.env`.
2. **Option B (If you purchased Web credits instead of API credits)**:
   - On `https://app.heygen.com/settings?nav=API`, add funds directly to the **API Wallet Balance** (or activate an API plan).

---

### Safety Guarantees Maintained
- **Scene 5**: Strictly excluded and untouched.
- **Paid Submissions in this Turn**: 0 new paid generation submissions executed.
- **Git Safety**: Local-only, 0 remote commits.
