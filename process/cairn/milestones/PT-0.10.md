---
id: PT-0.10
name: ledger hygiene
kind: product
major: PT-V1
status: in-progress
target_tag: v0.10.0
ga: false
---

**Definition of done:** `process/STATE.md` holds only current state, as its own
header already promises. Duplicated, unbounded history is removed from it and the
surfaces that instruct agents to append history are corrected, with a machine
check in the existing hard gate so the bound cannot silently regress.
