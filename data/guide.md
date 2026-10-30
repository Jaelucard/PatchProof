# Support-ticket annotation guide

This guide defines provisional labels for synthetic English tickets. It extracts the customer's current request. It does not decide policy, eligibility or whether a company should approve an action. All demo labels await human review, including after an independent agent check.

Each answer has exactly `order_id`, `issue_type`, `requested_action` and `needs_review`. Order IDs are strings (preserve leading zeros) or `null`. Never substitute a tracking number, quoted example or guessed identifier. The issue is one of `delivery_problem`, `damaged_item`, `wrong_item`, `billing_problem`, `other` or `null`. The action is one of `status_update`, `cancel_order`, `refund`, `replacement`, `other` or `null`. Review is a JSON boolean.

- **Plain request:** “Order 0041 arrived cracked. Send a replacement.” → `0041`, `damaged_item`, `replacement`, `false`.
- **Negation:** “Do not refund order 71; replace the broken plate.” → `71`, `damaged_item`, `replacement`, `false`. A negated request is not a current action.
- **Quoted history:** “Earlier I wrote ‘cancel order 16’. Now I only want its delivery status.” → `16`, `delivery_problem`, `status_update`, `false` when delivery trouble is explicit. Quote membership alone never establishes current intent.
- **Clear change of mind:** “Refund order 32 for the duplicate charge. Actually, don't refund it; explain the charge instead.” → `32`, `billing_problem`, `other`, `false`. An explicit correction supersedes the earlier request.
- **Missing identifier:** “My parcel is late; cancel my order.” → `null`, `delivery_problem`, `cancel_order`, `true`. The targeted order needs clarification. A clear general product enquiry can have no order ID and `needs_review=false`.
- **Unresolved contradiction:** “Cancel order 54, but keep it active. It has not shipped.” → `54`, `delivery_problem`, `null`, `true`. Do not choose one conflicting action; retain the clear ID and issue.
- **Absent action:** “Order 62 contains the wrong item.” → `62`, `wrong_item`, `null`, `true`; the desired response is unspecified. “Order 62 contained the wrong item; this is only a record, no action is requested” → `62`, `wrong_item`, `null`, `false`, because no clarification or action is sought.
- **Multiple targets:** “Both order 80 and order 81 were charged twice; refund both duplicate charges.” → `null`, `billing_problem`, `refund`, `true`. One ID cannot represent both targets. Preserve the shared issue and action. A reference to an unrelated past order does not create a second target.
- **Independent actions:** “Cancel order 90 and send its replacement; the parcel is missing.” → `90`, `delivery_problem`, `null`, `true`. One action cannot encode two incompatible independent requests.
- **Outside the enum:** “Add a gift message to order 12” → `12`, `other`, `other`, `false`. `other` denotes a clear category outside the enum, never uncertainty.
- **Uncertain issue:** “Order 28 is either damaged or the wrong model; I cannot tell. Replace it.” → `28`, `null`, `replacement`, `true`. Preserve the unambiguous request and mark only the uncertain field unknown.

Interpret “status update” as a request for progress/status of the order or an ongoing case, not any question. Explanations, invoice copies, address changes and contact requests use `other`. A return for money uses `refund` only when money back is explicit. Do not infer a refund from “return” alone. A clear known reason outside the issue enum uses `other`; an unresolved reason uses `null`.

Keep scenario variants in one partition. Preserve original inputs. Record disputes in the review sheet and exclude any unresolved label from scored experiments until resolved. Do not alter expected answers or weaken checks to produce a successful-looking repair.

## Fixture provenance

The demo supplies explicit baseline, first-proposal and second-proposal output strings. These are scripted illustrations, not model predictions. The first proposal intentionally loses a previously correct check. The second illustrates a non-regressing improvement. All six checks remain strict. Editing a prompt does not make these scripts into inference, and simulated improvements do not establish repair quality or hackathon qualification.
