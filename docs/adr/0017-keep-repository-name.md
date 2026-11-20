# ADR-0017: keep the repository, package and artifact name `soymutdb`

Status: accepted (2026-11-09)

Context: task #21 in the 2026-11-08 working round proposed renaming the
repository to `rlcao-mutdb`. The rename was listed as "still pending" in
`docs/dev/project-status.md` without a decision, and it was carried forward as
an open item across several rounds.

The rename would have touched, at minimum:

* the npm workspace scope (`@soymutdb/*` — every workspace package name, every
  `catalog:` consumer, every `workspace:` protocol reference);
* the Python distributions (`soymutdb-api`, `soymutdb-worker`, `soymutdb-jobs`,
  `soymutdb-import-protocol`, `soymutdb-mcp-server`) and the editable-install
  plan in `scripts/install_python_workspace.py`;
* the container images, artifact directory names, Compose service names and
  the `docs/dev/go-gateway.md` gateway module layout;
* the CI contract surface, where several guard scripts assert on exact package
  and artifact names (`scripts/test_platform_delivery_contracts.py`,
  `scripts/check_toolchain_pins.py`, `scripts/check_supply_chain.sh`).

None of those names carry scientific or contractual meaning: they are
mechanical identifiers. What *does* carry meaning is the public contract
layer — `public_id`, assembly-scoped namespaces, release scoping, the
external/internal site split — and none of it is affected by a repository
rename.

Decision: **the rename is abandoned.** The repository, the package scope and
the artifact names keep their current `soymutdb` spelling.

Consequences:

* no package, image, artifact or guard churn is spent on a rename that carries
  no product value;
* every existing name in the tree stays valid, so no compatibility alias or
  migration window is required;
* `docs/dev/project-status.md` no longer carries the rename as an open task;
  the only remaining mention of the string `rlcao` in the repository is in
  historical research/plan documents that record other people's home
  directories, which are kept as evidence;
* if a future release needs a different product-facing name, that is a
  product decision about the public site, not a repository-mechanics change,
  and it must be evaluated on its own merits (URLs, citations, DOIs) rather
  than inherited from this task.

Rollback: not applicable — this ADR records a decision not to act.
