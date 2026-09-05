---
lane: security-exposure
tier: base
schedule_hint: normal
severity_cap: blocker
---

# security-exposure

Security review of the changed code.

- `security/secret-exposure` — secrets/tokens/keys in code, logs, error
  messages, fixtures, or client-visible payloads.
- `security/injection` — SQL/command/path/template injection: untrusted input
  reaching an interpreter without parameterization or sanitization.
- `security/authz-gap` — endpoints/actions missing authentication or
  authorization checks present on sibling paths; privilege checks bypassable
  by direct invocation; IDOR via unvalidated ids.
- `security/unsafe-input-flow` — SSRF via user-controlled URLs, unsafe
  deserialization, XSS via unescaped output, path traversal, bidi/control
  characters in source.

Trace the concrete flow from source to sink before reporting.

## rule: security/secret-exposure

The rule is defined by the lane guidance above.

## rule: security/injection

The rule is defined by the lane guidance above.

## rule: security/authz-gap

The rule is defined by the lane guidance above.

## rule: security/unsafe-input-flow

The rule is defined by the lane guidance above.
