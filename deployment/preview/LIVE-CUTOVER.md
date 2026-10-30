# Gate for a funded private judge deployment

The local preview is fixture-only. This document is a review checklist, not
authorization to deploy, migrate data, publish credentials or spend more credit.
The preparer deliberately has no live-key option or automatic cutover command.

1. **Agree the destination and final access.** Choose a host that can run the two
   services and persistent storage, a public TLS domain and the judge-login
   delivery route. Confirm hosting cost and access through the end of judging.
   A bring-your-own-funded-key route is not expressly approved by the rules.
2. **Keep the single-user scope visible.** Judge credentials enter one shared
   workspace. Retain the landing notice, accept synthetic examples only, and do
   not promise per-user isolation. Multi-user private records need a separate
   design.
3. **Preserve complete canonical state.** Quiesce the original app and any
   operator helper before making a consistent SQLite backup. Preserve the full
   experiments, datasets, exposure and case_exposure tables, dataset identities,
   and the same cumulative provider-usage ledger. At the latest verified point
   that ledger contained 84 accounted requests and estimated US$0.00317376.
   Recheck it at cutover. Never replace it with this review's fixture ledger,
   copy only an export, clear unknown usage or reset exposure to claim freshness.
4. **Allow only one writer.** Stop the previous server before the deployment
   takes ownership. Keep database and ledger beside one another on the same
   persistent volume so the existing app selects the correct ledger. Confirm
   content hashes and all row counts after backup, restore and service
   recreation. An unresolved reservation blocks further real calls.
5. **Provision secrets explicitly.** After approval, mount only the specifically
   authorized raw provider-key file to the app as a private read-only file owned
   by the app's effective UID with mode 600. Keep the key out of images, Compose
   values, environment files, browser code, logs and gateway mounts. New judge
   credentials should be provisioned privately rather than reusing local review
   credentials. Keep the same non-root UID/GID as the private host files and
   retain the gateway's expected-runtime-identity guard. Docker Desktop can
   virtualize bind-file UID metadata; the backend's raw-key owner/mode checks
   must still pass inside the actual runtime. Provision a correctly owned
   private in-container file or an approved Linux-host mount if necessary;
   never weaken the existing key-file reader to bypass that check.
6. **Set the approved cumulative cap.** Verify currently available promotional
   credit and account liabilities. All testing/preview use counts toward the
   user's US$24.50 overall ceiling; the earlier app subcap was US$1. A local
   reservation cap does not control unrelated account usage, pricing changes or
   taxes. Do not top up a card or raise the cap without authorization.
7. **Enable live flags only in the reviewed deployment configuration.** The
   app's explicit key-file, access-confirmation and total-cap flags remain the
   sole live gate. No current generated Compose configuration includes those
   flags or a provider-key mount. Do not improvise a live overlay around this
   disposable review database.
8. **Verify the real boundary.** Test authentication for pages, assets, docs,
   API reads/writes and exports; wrong credentials; wrong/duplicate Host;
   wrong/null/duplicate Origin; cross-site fetch metadata; forwarding spoofing;
   hidden backend/admin ports; private file ownership; and no credentials sent
   upstream or to browser bundles. Public Basic authentication must travel over
   TLS. The outer TLS proxy must preserve the agreed Host/Origin and must not
   publish the app or Caddy administration port separately.
9. **Test persistence and accounting.** Recreate both services with the approved
   persistent volume, confirm saved results/exports remain unchanged and ensure
   no inference resumes automatically. Use a separately bounded synthetic live
   check only after approval and account for it in the same ledger.
10. **Approve publication last.** Review the concrete deployment, judge URL,
    credentials route, source/video and remaining balance before public access
    or submission. Keep Devpost's access requirement marked unresolved until
    the funded route is running and verified, or written organizer clarification
    accepts another route.

No public host, TLS endpoint, paid hosting account, live deployment or organizer
message has been created by this preparation.
