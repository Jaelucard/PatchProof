# Independent demo label review

Reviewed at: 2026-10-20T19:11:14.711369+00:00
Demo SHA-256: `9eeb48163f9135a8eb5f81adede0fb002c33de4b81dbc15cc3916ee8589bbbcb`

Kind: **Independent agent review. Human review remains pending.** This reviewer did not author the labels and read every ticket, expected four-field object and annotation note against the approved brief and annotation guide. This is a consistency review of synthetic examples, not a human audit or a measurement of extraction accuracy.

## Result

All 60 expected objects are consistent with the approved contract and the stated annotation conventions. No unresolved blocking label dispute was found. Labels may be marked `independently_agent_checked`; none may be marked human-reviewed.

## Conventions retained for human review

- Explicit record-only messages (`dev-22`, `dev-25`, `reg-14`) have `requested_action=null` and `needs_review=false`: no clarification or action is sought. This differs from an unresolved desired action (`dev-11`, `final-15`), which requires review.
- Clear general enquiries use `other` for issue and action, with no fabricated order ID. The labels extract the request and do not answer policy or approve a remedy.
- Multiple independent remedies (`dev-13`, `final-11`) cannot be encoded in one action field. Shared clear facts remain; action becomes null and review true.
- `reg-12` explicitly states unresolved wrong-versus-damaged classification. The unreadable label alone is not treated as overriding that uncertainty.
- Distinct hand-authored scenario seeds share behavioural categories across partitions. Unique family names and exact-input checks do not prove semantic deduplication, statistical independence or reliable generalisation. No generated paraphrase or same concrete order scenario was observed crossing partitions.

## Case-by-case disposition

All dispositions below mean accepted by this independent agent pass, with human review pending.

| ID | Disposition | Reason |
|---|---|---|
| dev-01 | Agent check accepted | Explicit late order/status request; leading zeros preserved. |
| dev-02 | Agent check accepted | Cracked product; explicit replacement. |
| dev-03 | Agent check accepted | Wrong product; explicit money-back request. |
| dev-04 | Agent check accepted | Duplicate charge; targeted second-charge refund. |
| dev-05 | Agent check accepted | Clear gift-message edit is other/other. |
| dev-06 | Agent check accepted | Negated cancellation; current status request. |
| dev-07 | Agent check accepted | Quoted old refund superseded by current replacement. |
| dev-08 | Agent check accepted | Explicit change of mind resolves earlier cancellation. |
| dev-09 | Agent check accepted | Missing required order ID triggers review without losing damage/refund. |
| dev-10 | Agent check accepted | Unresolved cancel/keep-active contradiction affects action only. |
| dev-11 | Agent check accepted | Wrong product; absent desired remedy needs clarification. |
| dev-12 | Agent check accepted | Multiple targets; shared delivery issue/refund retained. |
| dev-13 | Agent check accepted | Two independent remedies; action null and review. |
| dev-14 | Agent check accepted | General product question needs no order. |
| dev-15 | Agent check accepted | Issue explicitly uncertain; replacement remains clear. |
| dev-16 | Agent check accepted | Target unresolved between two orders; billing/refund clear. |
| dev-17 | Agent check accepted | Agent offer does not establish customer intent. |
| dev-18 | Agent check accepted | Explicit order ID takes precedence over carrier tracking decoy. |
| dev-19 | Agent check accepted | General policy enquiry extracted as other; no policy answer inferred. |
| dev-20 | Agent check accepted | Billing contact request is other, not refund. |
| dev-21 | Agent check accepted | Negated refund; explicit replacement. |
| dev-22 | Agent check accepted | Explicit record only/no reply; no action clarification needed. |
| dev-23 | Agent check accepted | Missed dispatch date is delivery trouble; cancellation explicit. |
| dev-24 | Agent check accepted | Issue and remedy explicitly unresolved; both null. |
| dev-25 | Agent check accepted | Clear thanks/record only; no remedy requested. |
| dev-26 | Agent check accepted | Wrong adapter variant; explicit refund. |
| dev-27 | Agent check accepted | Reverse charge means refund; cancellation is historical. |
| dev-28 | Agent check accepted | Locate/status phrases form one status goal, not independent remedies. |
| dev-29 | Agent check accepted | Damaged product; payment return explicit; replacement negated. |
| dev-30 | Agent check accepted | Address change outside enum; unrelated example ID ignored. |
| reg-01 | Agent check accepted | Torn physical product; explicit replacement. |
| reg-02 | Agent check accepted | Lost crate/search progress is delivery/status. |
| reg-03 | Agent check accepted | Wrong product form; exchange for correct item is replacement. |
| reg-04 | Agent check accepted | Disputed delivery fee is billing, not delivery failure. |
| reg-05 | Agent check accepted | Invoice-copy request; no amount dispute. |
| reg-06 | Agent check accepted | Gift-card wording edit is other/other. |
| reg-07 | Agent check accepted | Late delivery; explicit refund, alternate delivery negated. |
| reg-08 | Agent check accepted | Only current order is target; unrelated old order retained as history. |
| reg-09 | Agent check accepted | Missing required ID; cancellation clear. |
| reg-10 | Agent check accepted | Unresolved refund/not-refund contradiction affects action only. |
| reg-11 | Agent check accepted | General assembly enquiry; no order needed. |
| reg-12 | Agent check accepted | Customer explicitly cannot establish wrong versus damaged; issue null. |
| reg-13 | Agent check accepted | Explicit billing explanation; money back negated. |
| reg-14 | Agent check accepted | Explicit record only/no remedy; review false under guide convention. |
| reg-15 | Agent check accepted | Two parcels of one order; status request has one target. |
| final-01 | Agent check accepted | Missing dispatch progress; explicit cancellation. |
| final-02 | Agent check accepted | Tax error is billing; corrected invoice is other; refund negated. |
| final-03 | Agent check accepted | Snapped product; replacement explicit. |
| final-04 | Agent check accepted | Quoted seller cancellation not current intent; replacement explicit. |
| final-05 | Agent check accepted | General accessibility question; no target needed. |
| final-06 | Agent check accepted | Physical crack/leak establishes damage; refund explicit. |
| final-07 | Agent check accepted | Order ID with leading zeros; job-number decoy ignored. |
| final-08 | Agent check accepted | Wrong ordered size; remedy explicitly undecided, not inferred refund. |
| final-09 | Agent check accepted | Missing-order investigation progress is status update. |
| final-10 | Agent check accepted | Conflicting target IDs; shared billing/refund retained. |
| final-11 | Agent check accepted | Both independent remedies requested; action null and review. |
| final-12 | Agent check accepted | Earlier replacement withdrawn; current refund explicit. |
| final-13 | Agent check accepted | Hypothetical contact/process enquiry, not cancellation request. |
| final-14 | Agent check accepted | Billing dispute plus contact request; other action. |
| final-15 | Agent check accepted | Damage clear; next action explicitly undecided. |

## Secondary mechanical checks

- Domain validation accepted all 60 expected schemas.
- Counts were independently rerun: 30 development, 15 regression, 15 final; 60 unique IDs and 60 unique normalized inputs.
- There are 60 supplied scenario-family IDs; none occurs in more than one partition. This is a supplied-family/exact-text check, not arbitrary semantic deduplication.
- Explicit scripts were rerun against the strict six-check evaluator. Development baseline: 17/30 cases, 155/180 checks; candidate 1: 29/30 cases, 179/180 checks, 25 gains and 1 loss; candidate 2: 29/30 cases, 179/180 checks, 24 gains and 0 losses.
- Regression baseline: 12/15 cases, 87/90 checks; candidate 2: 15/15 cases, 90/90 checks, 3 gains and 0 losses.
- Final baseline: 6/15 cases, 72/90 checks; candidate 2: 14/15 cases, 89/90 checks, 17 gains and 0 losses.
- Candidate 1 loses a previously correct order ID in the already-failing `dev-03`. Candidate 2 retains the deliberate `dev-15` issue error and `final-11` action error.

## Limits

All script counts above are **Fixture simulation** evidence. The reviewer made zero live provider calls. No model inference, provider usability, actual prompt-repair benefit, human label approval, statistical reliability or hackathon qualification was verified. The stored receipt binds only to the exact demo bytes above. Changes to that file require a new review receipt.
