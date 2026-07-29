# B-04A canonical fingerprint alignment — implementation plan

## Task 1. Freeze the proven historical metadata contract

Add a pure executable contract for the four column-order snapshots, six
server-default values, and the named Joint self-FK. Run it before model changes
and record the expected RED.

## Task 2. Align canonical metadata

Make only the approved model declaration/default/FK-name changes. Preserve
Python-side defaults and all domain behavior. Do not touch revisions,
fingerprint code, generated candidate, services, or APIs.

## Task 3. Verify and review

Run focused tests, full pure migration contracts, compileall and
`git diff --check`. Request an independent scoped review and resolve all
Critical/Important findings before any live regeneration.

## Task 4. Regenerate and prove

Only after Tasks 1–3 are accepted:

1. safely reset the two owned disposable databases;
2. preserve the current generated candidate as diagnostic evidence outside the
   candidate target;
3. regenerate the candidate from corrected canonical metadata;
4. apply the original Task 6 deterministic hardening and only the proven
   metadata-alignment deltas; do not accept raw renderer output directly;
5. run candidate AST, offline SQL and full pure/static checks;
6. perform one fresh equivalence evidence run;
7. inspect accepted artifacts before closing B-04A.

No commit, push, merge or cleanup without the separately required owner gate.
