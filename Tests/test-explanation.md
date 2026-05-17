# SecureMarket — Contract Test Explanations

This document explains every contract test: what security requirement it validates, how it works step by step, what inputs it needs, and what a failure means.

---

## Why "Contract Tests"?

The word contract describes the agreement between the API and whoever calls it. Before the application is built, these tests write down that agreement precisely:

- This endpoint accepts these inputs
- It returns this status code under these conditions
- It enforces these security rules

When a developer implements a feature, the test tells them exactly what "correct" means. If their implementation breaks any clause, the test fails immediately. Writing tests before the application also forces the team to agree on endpoint paths, field names, and status codes before anyone writes a line of application code.

---

## Test File: `test_auth.py`

These tests validate the authentication and session management requirements from SR-AUTH.

---

### `test_login_with_valid_credentials_returns_200`

**Requirement:** FR-AC-02, SR-AUTH-01

**What it tests:**
That the login endpoint exists, accepts valid credentials, and returns both a short-lived access token and a longer-lived refresh token in the response body.

**How it works step by step:**
1. Sends a POST request to `/api/v1/auth/login` with a JSON body containing Buyer A's email and password.
2. Checks that the HTTP status code is exactly 200.
3. Checks that the JSON response contains an `access_token` field.
4. Checks that the JSON response contains a `refresh_token` field.

**Inputs required:**
- Buyer A must exist in the database (`buyera@test.com`, `BuyerPass123!`)
- The login endpoint must be reachable at `/api/v1/auth/login`

**What a failure means:**
- Status code is not 200: the endpoint does not exist, or credentials are being rejected even when correct
- `access_token` missing: the developer returned only one token or used a different field name
- `refresh_token` missing: the dual-token flow has not been implemented

---

### `test_login_with_wrong_password_returns_401`

**Requirement:** SR-AUTH-01

**What it tests:**
That incorrect credentials are rejected with HTTP 401 Unauthorized — not 400, not 403, and certainly not 200.

**How it works step by step:**
1. Sends a POST to `/api/v1/auth/login` with Buyer A's email but the wrong password (`wrongpassword`).
2. Asserts the status code is 401.

**Inputs required:**
- Buyer A must exist in the database
- `wrongpassword` must NOT be Buyer A's actual password

**What a failure means:**
- Status is 200: catastrophic — the application is accepting wrong passwords
- Status is 400: the developer returned a validation error instead of an auth error — semantically wrong
- Status is 403: implies the user is known but forbidden, which reveals account existence — a security issue in itself

---

### `test_login_error_message_does_not_reveal_user_existence`

**Requirement:** NFR-09, T-P1-02 mitigation

**What it tests:**
That failed login error messages are identical regardless of whether the failure was caused by a wrong password for a real account, or a request for an account that does not exist at all. Different messages allow an attacker to enumerate valid email addresses, which directly enables credential stuffing.

**How it works step by step:**
1. Sends a POST to login with Buyer A's real email and a wrong password. Records the `detail` field from the 401 response.
2. Sends a POST to login with a completely fabricated email (`doesnotexist@test.com`) and any password. Records the `detail` field from the 401 response.
3. Asserts that both `detail` values are identical strings.

**Inputs required:**
- Buyer A must exist with email `buyera@test.com`
- `doesnotexist@test.com` must NOT exist in the database at all
- Both requests must return 401 (if either returns a different code, the comparison is invalid)

**What a failure means:**
- The two messages differ: the developer wrote separate error messages for "user not found" and "wrong password", which is an extremely common mistake. An attacker can exploit this to build a valid user list before launching a credential stuffing attack.

---

### `test_account_locks_after_5_failed_attempts`

**Requirement:** SR-AUTH-07, MST-01

**What it tests:**
That the account lockout mechanism activates after exactly 5 consecutive failed login attempts, and that even a correct password is rejected while the account is locked.

**How it works step by step:**
1. Sends 5 POST requests to the login endpoint with Buyer A's email but the wrong password.
2. Sends a 6th POST request with Buyer A's **correct** password.
3. Asserts that the 6th response status code is 403 or 429 — access is denied even though the password is correct.

**Inputs required:**
- Buyer A must exist
- The database must have a fresh failed-attempt counter for Buyer A (no leftover failures from previous test runs)
- The application must track failed login attempts per account

**Important note:**
After this test runs, Buyer A's account is locked. The database must be reset before the next test run, or this test must use a dedicated user account that is not shared with any other test. This is why the seed script must reset state between test classes.

**What a failure means:**
- Status is 200 on the 6th attempt: lockout is not implemented
- Status is 401 (wrong password error) on the 6th attempt: the lockout check is not being triggered
- Lockout triggers after fewer than 5 attempts: the threshold is wrong

---

### `test_access_token_expiry_is_short`

**Requirement:** SR-AUTH-05

**What it tests:**
That the JWT access token issued at login has an expiry time of 15 minutes or less. A longer expiry increases the damage window if a token is stolen via XSS or network sniffing (T-EE-02).

**How it works step by step:**
1. Logs in as Buyer A and retrieves the access token from the response.
2. Decodes the JWT **without signature verification** — this is intentional, because the goal is only to read the time claims, not to verify identity.
3. Reads the `iat` (issued at) and `exp` (expires at) timestamps from the decoded payload.
4. Calculates the difference in minutes: `(exp - iat) / 60`.
5. Asserts the result is 15 or less.

**Inputs required:**
- Buyer A must exist
- `pyjwt` must be installed (`pip install pyjwt`)
- The JWT must contain both `iat` and `exp` claims

**What a failure means:**
- `KeyError` on `iat` or `exp`: the developer did not include these standard claims in the token — this is itself a security gap because tokens without `exp` never expire
- TTL is greater than 15 minutes: the expiry is too long, meaning stolen tokens remain valid for too long

---

## Test File: `test_authz.py`

These tests validate the authorisation and access control requirements from SR-AUTHZ.

---

### `test_buyer_cannot_access_another_buyers_order`

**Requirement:** SR-AUTHZ-02, SR-AUTHZ-04, MST-05

**What it tests:**
That resource-level authorisation is enforced — a legitimately authenticated buyer cannot read another buyer's order by substituting a different UUID in the URL. This is an IDOR (Insecure Direct Object Reference) vulnerability.

**How it works step by step:**
1. Authenticates as Buyer A with a valid token.
2. Sends a GET request to `/api/v1/orders/{buyer_b_order_uuid}` — using Buyer B's order UUID, not Buyer A's.
3. Asserts the response is 403 Forbidden.

**Inputs required:**
- Buyer A and Buyer B must both exist
- Buyer B must have an order with a known UUID (`66666666-ffff-ffff-ffff-666666666666`)
- The application must check not just that the requester is a BUYER, but that the requester owns this specific order

**What a failure means:**
- Status is 200: the application only checks the role (is this user a BUYER?) but not ownership (is this order theirs?). An attacker can access any order by guessing or iterating UUIDs.
- Status is 404: acceptable behaviour — returning "not found" instead of "forbidden" is a valid security pattern (it does not reveal the resource exists), but the test would need updating to accept 404 as well.

---

### `test_seller_cannot_modify_another_sellers_product`

**Requirement:** SR-AUTHZ-05, MST-06

**What it tests:**
That a seller can only modify products they own. Seller A is authorised to update products in general (the SELLER role permits it), but must be blocked from updating Seller B's product.

**How it works step by step:**
1. Authenticates as Seller A.
2. Sends a PUT request to `/api/v1/products/{seller_b_product_uuid}` with a modified title.
3. Asserts the response is 403 Forbidden.

**Inputs required:**
- Seller A and Seller B must both exist
- Seller B must have a product with a known UUID (`33333333-cccc-cccc-cccc-333333333333`)

**What a failure means:**
- Status is 200: the application checks the role (is this a SELLER?) but not ownership (does this seller own this product?). Any seller can edit any product, which allows malicious sellers to sabotage competitors.

---

### `test_buyer_cannot_access_admin_endpoints`

**Requirement:** SR-AUTHZ-01, MST-08

**What it tests:**
Function-level access control — that a buyer's role is checked against every endpoint, and admin-only endpoints return 403 when accessed by a buyer.

**How it works step by step:**
1. Authenticates as Buyer A.
2. Sends a GET request to `/api/v1/users` (admin-only user list).
3. Asserts 403.
4. Sends a GET request to `/api/v1/audit-log` (admin-only audit log).
5. Asserts 403.

**Inputs required:**
- Buyer A must exist
- Both endpoints must exist — they can return 403 before they are fully implemented, which is why this test can pass early in development

**What a failure means:**
- Either endpoint returns 200: the RBAC middleware is not applied to that route, or was applied with the wrong role requirement.
- Either endpoint returns 404: the endpoint does not exist yet — the test cannot pass until the routes are registered, even if the access control is correct.

---

### `test_buyer_cannot_access_draft_product`

**Requirement:** SR-AUTHZ-06, MST-09

**What it tests:**
That buyers can only see ACTIVE products. A product in DRAFT status is invisible to buyers — they should receive 403 or 404 when attempting to access it directly by UUID.

**How it works step by step:**
1. Authenticates as Buyer A.
2. Sends a GET request to `/api/v1/products/{draft_product_uuid}` where the product is in DRAFT status.
3. Asserts the response is 403 or 404.

**Inputs required:**
- Buyer A must exist
- The draft product (`22222222-bbbb-bbbb-bbbb-222222222222`) must exist in DRAFT status owned by Seller A

**What a failure means:**
- Status is 200: buyers can see unpublished, potentially incomplete or incorrect product listings. A seller testing pricing or descriptions would have that information exposed.

---

### `test_role_field_cannot_be_self_assigned`

**Requirement:** SR-AUTHZ-03, MST-07

**What it tests:**
That a user cannot escalate their own privileges by including a `role` field in an update request. This is a parameter tampering / privilege escalation test.

**How it works step by step:**
1. Authenticates as Buyer A.
2. Sends a PUT request to `/api/v1/users/{buyer_a_uuid}` with `{"role": "ADMIN"}` in the body.
3. Checks two acceptable outcomes:
   - The response is 403 (the field is explicitly rejected), OR
   - The response is 200 but the `role` in the response body is still `BUYER` (the field was silently ignored)
4. The test fails only if the role in the response is `ADMIN`.

**Inputs required:**
- Buyer A must exist with a known UUID
- A profile update endpoint must exist at `/api/v1/users/{id}`

**What a failure means:**
- The role in the response is ADMIN: any user can make themselves an admin. This is a critical privilege escalation vulnerability.

---

## Test File: `test_business.py`

These tests validate the business logic security requirements from SR-BIZ and SR-DATA.

---

### `test_client_supplied_price_is_ignored`

**Requirement:** SR-DATA-06, SR-DATA-07, MST-11

**What it tests:**
Server-side price integrity — the single most financially critical test. Even if a buyer sends a manipulated price in the request body, the order total must be calculated using the price stored in the database, not the client-supplied value.

**How it works step by step:**
1. Authenticates as Buyer A.
2. Sends a POST to `/api/v1/orders` with a request body that includes `"unit_price": 0.01` — a manipulated price far below the actual product price of 29.99.
3. Asserts the response status is 201 Created (the order is accepted).
4. Reads the `total_amount` from the response.
5. Asserts that `total_amount` equals `29.99 * quantity` — the real price from the database — not `0.01 * quantity`.

**Inputs required:**
- Buyer A must exist
- The active product must exist with price 29.99 and stock ≥ 1
- The order endpoint must return the calculated total in the response body
- A valid shipping address must be included in the request (required field)

**What a failure means:**
- `total_amount` is 0.01: the application used the client-supplied price. An attacker can purchase any product for a fraction of a cent. This is a direct, immediate financial loss.
- Status is 422: the endpoint is rejecting the `unit_price` field as an unknown field rather than silently ignoring it — this is also acceptable behaviour but the test assertion on total_amount cannot run in this case.

---

### `test_buyer_cannot_review_without_purchase`

**Requirement:** SR-BIZ-01, MST-13

**What it tests:**
That the review system enforces purchase verification — a buyer with no delivered order for a product cannot post a review for it. This prevents fake reviews from non-customers.

**How it works step by step:**
1. Authenticates as Buyer A.
2. Sends a POST to `/api/v1/products/{active_product_uuid}/reviews` with a rating and comment.
3. Asserts the response is 403 — Buyer A has no delivered order for this product.

**Inputs required:**
- Buyer A must exist
- The active product must exist
- Buyer A must have NO delivered order for this specific product — verify the seed data does not accidentally create one

**What a failure means:**
- Status is 201: anyone can leave reviews for any product without buying it. Review scores become meaningless and can be weaponised by competitors submitting fake negative reviews.

---

### `test_buyer_cannot_leave_duplicate_review`

**Requirement:** SR-BIZ-02, MST-14

**What it tests:**
That the one-review-per-buyer-per-product constraint is enforced, backed by a database unique constraint. A buyer who has left a review cannot leave a second one for the same product.

**How it works step by step:**
1. Authenticates as Buyer A (who has a DELIVERED order for the active product via the seed data).
2. Sends a first POST to the reviews endpoint — this should succeed with 201.
3. Sends a second POST to the same reviews endpoint for the same product.
4. Asserts the second response is 400 or 409.

**Inputs required:**
- Buyer A must exist
- The delivered order (`55555555-eeee-eeee-eeee-555555555555`) must link Buyer A to the active product
- The database must have a unique constraint on `(buyer_id, product_id)` in the reviews table

**What a failure means:**
- Second request returns 201: the duplicate check is missing. A buyer can submit unlimited reviews, manipulating the product's average rating.
- First request returns 403: the purchase verification check is failing — Buyer A's delivered order is not being found, which means the seed data for the delivered order may be incorrect.

---

### `test_invalid_order_status_transition`

**Requirement:** SR-BIZ-03, MST-15

**What it tests:**
That the order state machine is enforced — an order cannot skip states. A PENDING order cannot jump directly to DELIVERED.

**How it works step by step:**
1. Authenticates as Buyer A.
2. Sends a PATCH or PUT request attempting to move the pending order directly to `DELIVERED` status.
3. Asserts the response is 400 Bad Request.

**Inputs required:**
- Buyer A must exist
- The pending order (`44444444-dddd-dddd-dddd-444444444444`) must exist in PENDING status
- The valid transition path is PENDING → CONFIRMED → SHIPPED → DELIVERED — jumping from PENDING to DELIVERED skips three states

**What a failure means:**
- Status is 200: the state machine is not enforced. A buyer can force their order into DELIVERED status, which then allows them to leave a review without the seller ever shipping anything.

---

### `test_cancel_non_pending_order`

**Requirement:** SR-BIZ-04, MST-16

**What it tests:**
That buyers can only cancel orders in PENDING status. A CONFIRMED or SHIPPED order cannot be cancelled by the buyer.

**How it works step by step:**
1. Uses the confirmed order — an order that has already moved past PENDING (you may need to add a CONFIRMED order to your seed data for this test).
2. Authenticates as Buyer A.
3. Sends a cancellation request for the confirmed order.
4. Asserts the response is 400.

**Inputs required:**
- Buyer A must exist
- An order in CONFIRMED (or later) status belonging to Buyer A must exist
- The cancellation endpoint must be defined

**What a failure means:**
- Status is 200: a buyer can cancel orders after they have been packed and shipped, causing operational and financial loss for the seller.

---

## Test File: `test_files.py`

These tests validate file upload security requirements from SR-INPUT and SR-DATA.

---

### `test_php_file_disguised_as_png_is_rejected`

**Requirement:** SR-INPUT-02, MST-18

**What it tests:**
Magic byte validation — a file with a `.png` extension containing PHP source code must be rejected. The server must inspect the actual binary content of the file, not trust the extension or Content-Type header.

**How it works step by step:**
1. Creates an in-memory file object containing the text `<?php system($_GET['cmd']); ?>`.
2. Sends it as a multipart form upload to the product image endpoint with the filename `shell.png` and Content-Type `image/png`.
3. Asserts the response is 422.

**How magic byte detection works:**
PNG files always start with the bytes `89 50 4E 47 0D 0A 1A 0A` (hexadecimal), which correspond to `\x89PNG\r\n\x1a\n`. The PHP content in `fake.png` starts with `3C 3F 70 68` (the bytes for `<?ph`). The server reads the first few bytes of the uploaded file and compares them to the expected signature — the mismatch causes rejection.

**Inputs required:**
- Seller A must exist and be authenticated
- A product owned by Seller A must exist
- The `fake.png` fixture file must exist at `tests/fixtures/fake.png` — a text file containing PHP code with a `.png` extension

**What a failure means:**
- Status is 201: the server accepted a PHP file. If the server ever executes files from the upload directory (a misconfiguration called remote code execution via file upload), an attacker can run arbitrary commands on the server.

---

### `test_path_traversal_filename_is_rejected`

**Requirement:** SR-INPUT-04, MST-17

**What it tests:**
Path traversal prevention — a filename containing `../` sequences must not result in a file being written outside the intended storage directory.

**How it works step by step:**
1. Opens `tests/fixtures/valid.png` — a genuine PNG file that will pass magic byte validation.
2. Sends it as an upload with the filename `../../etc/passwd` and Content-Type `image/png`.
3. Asserts the response is 422.

**Why a real PNG is used here:**
The filename is the threat vector, not the file content. Using a real PNG ensures the magic byte check passes and the only thing being tested is the path validation. If a fake file were used, both checks would fail and it would be unclear which one caused the rejection.

**Inputs required:**
- Seller A and product must exist
- `tests/fixtures/valid.png` must be a genuine PNG file
- The server must never use the client-supplied filename for path construction — it must generate a UUID filename server-side

**What a failure means:**
- Status is 201 and a file is written: the `../../etc/passwd` part of the filename caused the server to write a file to `/etc/passwd` (or two directories above the storage root, wherever that resolves). This is a critical filesystem compromise.
- Status is 201 but file is stored safely: the server generated a UUID filename but did not validate the submitted filename at all — this is still a finding because the original filename may be logged or stored in a way that creates secondary vulnerabilities.

---

### `test_file_over_10mb_is_rejected`

**Requirement:** SR-INPUT-03

**What it tests:**
That the 10MB file size limit is enforced, preventing storage exhaustion attacks (T-P5-06).

**How it works step by step:**
1. Creates an in-memory byte object of exactly 10,485,761 bytes (10MB + 1 byte).
2. Sends it as an upload to the product image endpoint.
3. Asserts the response is 413 or 422.

**Why both 413 and 422 are accepted:**
The limit can be enforced at two different layers. If Nginx (the reverse proxy) enforces it, the response is 413 Payload Too Large and FastAPI never sees the request. If it is enforced in application code via a Pydantic validator or file size check, the response is 422 Unprocessable Entity. Both are correct — the test must accept both.

**Inputs required:**
- Seller A and product must exist
- Either Nginx or the application must have the size limit configured

**What a failure means:**
- Status is 201: no size limit is enforced. An attacker can upload hundreds of files near or over the limit, filling the server's disk and causing a denial of service.

---

### `test_response_does_not_expose_server_path`

**Requirement:** SR-DATA-01, T-P5-04

**What it tests:**
Information disclosure — a successful upload response must not reveal the internal filesystem path where the file was stored. Exposing paths like `/var/www/uploads/images/` helps an attacker understand the server's directory structure.

**How it works step by step:**
1. Uploads `tests/fixtures/valid.png` as a legitimate image and gets a 201 response.
2. Checks that the JSON response body does not contain a key named `file_path`.
3. Checks that the string representation of the entire response body does not contain common Unix path prefixes: `/var/`, `/home/`, `/srv/`, `/tmp/`.

**Inputs required:**
- `tests/fixtures/valid.png` must exist and be a real PNG
- Seller A and product must exist
- The upload must succeed — this test only makes sense after basic upload functionality works

**What the response should contain instead:**
A UUID identifying the image (for use in the download endpoint), or a URL pointing to the authenticated download API. Never a raw filesystem path.

**What a failure means:**
- `file_path` appears in the response: the developer returned the full storage path for debugging convenience. An attacker learns the directory structure and storage conventions, making other attacks (path traversal, direct file access) easier to plan.

---

## Test File: `tests/sast/test_sast.py`

These tests run static analysis tools against the source code. They do not require a running application and can be executed from day one.

---

### `test_bandit_no_high_severity`

**Requirement:** SAST-01 quality gate

**What it tests:**
That Bandit (a Python security linter) finds zero high or critical severity issues in the application source code.

**How it works:**
Runs `bandit -r ./app -ll -f json` as a subprocess, parses the JSON output, and asserts the results list contains no items with severity `HIGH` or `CRITICAL`.

**Common issues Bandit catches:** Hardcoded passwords, use of `eval()`, use of `subprocess` with `shell=True`, use of `pickle`, weak random number generators, SQL string formatting.

**Inputs required:** Only the source code directory `./app` — no running server needed.

---

### `test_no_hardcoded_secrets`

**Requirement:** SR-AUTH-06, SAST-01

**What it tests:**
That no JWT secret, database password, or API key is hardcoded as a string literal in the source code.

**How it works:**
Runs `grep -r 'SECRET_KEY\s*=\s*[' ./app` and asserts the output is empty. Any match means a secret is hardcoded.

**Inputs required:** Source code only.

**What a failure means:**
A hardcoded secret was found. If this code is ever committed to a repository, the secret is permanently exposed in Git history even if it is later deleted.

---

### `test_no_raw_sql`

**Requirement:** SR-INPUT-07, SAST-02

**What it tests:**
That no f-string formatted SQL queries appear in the source code. Raw string-formatted SQL is the primary cause of SQL injection vulnerabilities.

**How it works:**
Runs `grep -rn 'execute(f"' ./app` and asserts the output is empty. The pattern targets f-strings passed directly to database execute calls.

**Inputs required:** Source code only.

**What a failure means:**
A raw SQL string was found. Even if the current value being interpolated happens to be safe, using this pattern means a future developer may introduce an unsafe value without realising the risk.

---

## Test File: `tests/sast/test_sca.py`

---

### `test_no_critical_cves_in_dependencies`

**Requirement:** SR-3RD-02, SCA-01

**What it tests:**
That none of the Python dependencies listed in `requirements.txt` have known critical CVEs.

**How it works:**
Runs `pip-audit --format json` and parses the output. Asserts that no vulnerabilities with available fixes are present (a known fix means the vulnerability is actively tracked and exploitable).

**Inputs required:** `requirements.txt` must exist with dependencies listed.

---

### `test_all_dependencies_pinned`

**Requirement:** SR-3RD-01, SCA-02

**What it tests:**
That every dependency in `requirements.txt` is pinned to an exact version using `==`, not a range (`>=`, `~=`) or no version at all.

**How it works:**
Reads `requirements.txt` line by line and checks that every non-comment, non-empty line contains `==`. Lines without `==` are collected and reported in the assertion failure message.

**Inputs required:** `requirements.txt` must exist.

**What a failure means:**
An unpinned dependency was found. At the next `pip install`, that package could update to a version containing a vulnerability or a breaking change, without any explicit decision being made.
