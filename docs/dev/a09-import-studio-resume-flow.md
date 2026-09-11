# A-09 Import Studio Post-upload Resume Flow

## Scope

The legacy Admin import modal may collect a user’s intent before upload, but it must not create an Import Studio server draft until the source object has been uploaded or selected and inspected. This document defines the safe hand-off into the existing persisted Import Studio lifecycle.

## Why pre-upload drafts are prohibited

`POST /admin/imports/studio/dataset-versions` requires authoritative, immutable source metadata: object key, SHA-256 checksum, source/license and MIME type, plus inspected row and column counts. Placeholder values would allow a draft to be validated against a source other than the object eventually committed.

The server lifecycle therefore starts only after a trusted inspection result:

```text
selected/uploaded immutable object
  → server inspection metadata
  → DatasetVersion
  → ImportDraft
  → mapping / patches
  → validate
  → ready
  → explicit commit
```

## Required hand-off contract

1. **Upload or select the object.** The result must contain a stable object key or immutable selected-object identifier.
2. **Server-side inspection.** The inspection response supplies the checksum, MIME type, source/license metadata, and row/column shape. The client must not invent these values.
3. **Create the DatasetVersion.** Send the inspection-derived values to `POST /admin/imports/studio/dataset-versions`.
4. **Create or resume the ImportDraft.** Call `POST /admin/imports/studio/drafts` with the returned DatasetVersion identity. If a draft already exists for the same DatasetVersion, resume it rather than duplicate it.
5. **Persist only the server identity in navigation.** Put the returned draft id in route state/query state or show it in a dedicated resume list. Do not serialize the full source payload into browser storage.
6. **Constrain later screens to server state.** Mapping, patching, validation, readiness, and commit reload the draft and operate through the typed Import Studio client. A committed draft must remain immutable.

## UX requirements

- The pre-upload wizard must label its progress as local preparation, not a saved draft.
- The first persisted-state confirmation appears only after DatasetVersion and ImportDraft creation succeeds.
- Resume UI shows dataset identity, inspection timestamp, draft state, and the next permitted action; it never exposes an arbitrary manual state jump.
- A failed inspection or DatasetVersion creation leaves no resumable draft and provides a retry path from the immutable object step.

## Acceptance gates before wiring the UI

- [ ] Upload/select endpoint returns the immutable source identity plus trusted inspection metadata.
- [ ] DatasetVersion creation is tested with this exact inspected metadata.
- [ ] Re-entering the same source either resumes its permitted draft or presents an explicit conflict outcome; it never silently duplicates data.
- [ ] Route/resume state carries only the draft identifier and is access-controlled.
- [ ] Mapping/validation/commit integration tests prove state transitions and committed-draft immutability.
- [ ] Browser flow proves that an interrupted upload cannot appear as a persisted server draft.

## Existing implementation boundary

The existing typed client is `packages/api-client/src/admin-import-studio.ts`; API schemas and safety rules reside in `apps/api/app/api/v1/import_studio.py` and `apps/api/app/schemas/import_studio.py`. This design does not add any endpoint or mutate the current inline wizard.
