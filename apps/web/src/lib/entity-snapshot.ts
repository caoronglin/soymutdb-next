/**
 * Build-time prerendering of released entity pages ("dynamic-eligible").
 *
 * A record page such as `/genes/<accession>` is a parameterised route: there is
 * no metadata flag that could make it a static document, because the document
 * depends on *which record* the deployment released. This module therefore
 * turns a data snapshot — the list of entities a release publishes — into the
 * documents the build writes:
 *
 *   - `normalizeEntitySnapshot()` validates the payload against an explicit
 *     public whitelist and re-emits it, so an unknown upstream field can never
 *     be copied into a published artifact.
 *   - `planEntityDocuments()` maps each validated entry onto its route document,
 *     with the title/description it will show and a real `<main>` body carrying
 *     the record's own facts.
 *
 * Fail-closed, by construction:
 *
 *   - with no snapshot (or an empty `entities` array) `planEntityDocuments()`
 *     returns nothing, so the artifact keeps the SPA shell for every dynamic
 *     path. That is the default, and it is what `deriveStaticRouteEntries()`
 *     relies on: a dynamic path is skipped unless the snapshot supplies it.
 *   - the snapshot names exactly one site variant and one release; a payload
 *     that disagrees with the build's pin is rejected rather than published.
 *   - an entry whose identifier could escape its directory (`../`, `a/b`,
 *     a leading dot) is rejected, never sanitised into a nearby path.
 *
 * NOT hydration: the emitted body is a pre-rendered document for crawlers and
 * no-JS clients. The portal boots with `createRoot`, which clears the mount
 * container and renders the React tree, so a JS-capable client sees the app
 * replace the static body.
 *
 * The static body is English, like the news/about documents
 * (`scripts/content-snapshot-build.ts`): it is the no-JS fallback, while the
 * app's own copy is translated at runtime. The document never carries the
 * "enable JavaScript" shell — it has real content.
 */

import { escapeHtml } from "./static-routes";

/** Snapshot schema this build understands. Anything else is rejected. */
export const ENTITY_SNAPSHOT_SCHEMA_VERSION = 1;

/**
 * Gene accessions are the public identifier: a dot/dash/underscore token such
 * as `Glyma.01G000100.Wm82.a4.v1`. Anything that could name another directory
 * (a slash, a leading dot, a percent escape) is rejected by this pattern.
 */
export const PUBLIC_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

/** Route template each supported entity kind is materialised from. */
const KIND_TEMPLATES = { gene: "/genes/:geneId" } as const;

export interface GeneEntity {
  kind: "gene";
  /** Stable public identifier; the URL segment and the document's `<h1>`. */
  public_id: string;
  symbol: string | null;
  assembly_id: string;
  assembly_name: string;
  release_id: number;
  chromosome: string;
  /** 1-based inclusive start. */
  start: number;
  /** 1-based inclusive end. */
  end: number;
  strand: "+" | "-" | ".";
  /** The `<h1>`-adjacent document title this page will be published under. */
  title: string;
  /** `<meta name="description">` and the body summary. */
  description: string | null;
}

export interface EntitySnapshot {
  schema_version: number;
  generated_at: string;
  site_variant: "external";
  entities: GeneEntity[];
}

export interface EntityDocument {
  /** Concrete router path, e.g. `/genes/Glyma.01G000100.Wm82.a4.v1`. */
  path: string;
  /** The dynamic route template this path was materialised from. */
  templatePath: string;
  title: string;
  description?: string;
  /** Artifact-relative document path, e.g. `genes/<id>/index.html`. */
  relativePath: string;
  /** Build-assembled, already-escaped `<main>` fragment. */
  mainHtml: string;
}

export class EntitySnapshotError extends Error {
  constructor(message: string) {
    super(`[entity-snapshot] ${message}`);
    this.name = "EntitySnapshotError";
  }
}

/* -------------------------------------------------------------------------- */
/* Validation primitives                                                       */
/* -------------------------------------------------------------------------- */

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireString(value: unknown, path: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new EntitySnapshotError(`${path} must be a non-empty string`);
  }
  return value;
}

function optionalString(value: unknown, path: string): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string") {
    throw new EntitySnapshotError(`${path} must be a string or null`);
  }
  return value;
}

function requirePositiveInteger(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) {
    throw new EntitySnapshotError(`${path} must be a positive integer`);
  }
  return value;
}

function requireStrand(value: unknown, path: string): "+" | "-" | "." {
  if (value !== "+" && value !== "-" && value !== ".") {
    throw new EntitySnapshotError(`${path} must be "+", "-" or ".".`);
  }
  return value;
}

/* -------------------------------------------------------------------------- */
/* Normalisation                                                               */
/* -------------------------------------------------------------------------- */

function normalizeGene(raw: Record<string, unknown>, path: string): GeneEntity {
  const publicId = requireString(raw.public_id, `${path}.public_id`);
  if (!PUBLIC_ID_PATTERN.test(publicId)) {
    throw new EntitySnapshotError(
      `${path}.public_id is not a safe public identifier (${JSON.stringify(publicId)})`,
    );
  }
  const start = requirePositiveInteger(raw.start, `${path}.start`);
  const end = requirePositiveInteger(raw.end, `${path}.end`);
  if (end < start) {
    throw new EntitySnapshotError(
      `${path} has end (${end}) before start (${start}): coordinates are 1-based inclusive`,
    );
  }
  return {
    kind: "gene",
    public_id: publicId,
    symbol: optionalString(raw.symbol, `${path}.symbol`),
    assembly_id: requireString(raw.assembly_id, `${path}.assembly_id`),
    assembly_name: requireString(raw.assembly_name, `${path}.assembly_name`),
    release_id: requirePositiveInteger(raw.release_id, `${path}.release_id`),
    chromosome: requireString(raw.chromosome, `${path}.chromosome`),
    start,
    end,
    strand: requireStrand(raw.strand, `${path}.strand`),
    title: requireString(raw.title, `${path}.title`),
    description: optionalString(raw.description, `${path}.description`),
  };
}

/**
 * Validate a raw snapshot and re-emit it through the public whitelist.
 *
 * Every rejection below is fail-closed: a partial or misattributed entity set
 * would publish another release's record under this artifact's canonical URLs.
 */
export function normalizeEntitySnapshot(raw: unknown): EntitySnapshot {
  if (!isPlainObject(raw)) {
    throw new EntitySnapshotError("snapshot must be a JSON object");
  }
  if (raw.schema_version !== ENTITY_SNAPSHOT_SCHEMA_VERSION) {
    throw new EntitySnapshotError(
      `unsupported schema_version ${JSON.stringify(raw.schema_version)}; ` +
        `this build understands ${ENTITY_SNAPSHOT_SCHEMA_VERSION}`,
    );
  }
  if (raw.site_variant !== "external") {
    throw new EntitySnapshotError(
      `snapshot site_variant must be "external", got ${JSON.stringify(raw.site_variant)}`,
    );
  }
  const generatedAt = requireString(raw.generated_at, "generated_at");
  if (Number.isNaN(new Date(generatedAt).getTime())) {
    throw new EntitySnapshotError(`generated_at is not a valid timestamp: ${generatedAt}`);
  }
  if (!Array.isArray(raw.entities)) {
    throw new EntitySnapshotError("entities must be an array");
  }

  const entities: GeneEntity[] = [];
  const seen = new Set<string>();
  raw.entities.forEach((entry, index) => {
    const path = `entities[${index}]`;
    if (!isPlainObject(entry)) throw new EntitySnapshotError(`${path} must be an object`);
    if (entry.kind !== "gene") {
      throw new EntitySnapshotError(
        `${path}.kind is ${JSON.stringify(entry.kind)}; this build prerenders ` +
          `${Object.keys(KIND_TEMPLATES).join(", ")} only`,
      );
    }
    const gene = normalizeGene(entry, path);
    const key = `${gene.kind}:${gene.public_id}`;
    if (seen.has(key)) {
      throw new EntitySnapshotError(
        `${path} repeats ${key}: two entries would write the same document`,
      );
    }
    seen.add(key);
    entities.push(gene);
  });

  return {
    schema_version: ENTITY_SNAPSHOT_SCHEMA_VERSION,
    generated_at: generatedAt,
    site_variant: "external",
    entities,
  };
}

/**
 * Require the snapshot to describe the release the build pins.
 *
 * A record prerendered from release 7 must not be published into an artifact
 * built for release 8: the coordinates and the assembly namespace would come
 * from a release this site no longer serves.
 */
export function assertEntitySnapshotRelease(
  snapshot: EntitySnapshot,
  expectedReleaseId: number | undefined,
): void {
  if (expectedReleaseId === undefined) return;
  for (const entity of snapshot.entities) {
    if (entity.release_id !== expectedReleaseId) {
      throw new EntitySnapshotError(
        `${entity.kind} ${entity.public_id} carries release_id=${entity.release_id} ` +
          `but the build pins release_id=${expectedReleaseId}`,
      );
    }
  }
}

/* -------------------------------------------------------------------------- */
/* Document planning                                                           */
/* -------------------------------------------------------------------------- */

/** Thousands separators, written out so the artifact does not depend on ICU. */
function formatCoordinate(value: number): string {
  return String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function renderGeneMain(entity: GeneEntity, basePath: string): string {
  const facts: Array<[string, string]> = [
    [
      "Coordinates",
      `${entity.chromosome}:${formatCoordinate(entity.start)}–${formatCoordinate(entity.end)}`,
    ],
    ["Strand", entity.strand],
    ["Assembly", `${entity.assembly_name} (id ${entity.assembly_id})`],
    ["Release", String(entity.release_id)],
  ];
  const rows = facts
    .map(
      ([term, description]) =>
        `<div class="rl-entity-fact"><dt>${escapeHtml(term)}</dt>` +
        `<dd class="font-mono">${escapeHtml(description)}</dd></div>`,
    )
    .join("");
  return [
    '<main data-rl-static="entity" class="container-prose">',
    `<nav class="rl-entity-back"><a href="${escapeHtml(basePath)}genes">← Gene search</a></nav>`,
    `<h1 class="font-mono">${escapeHtml(entity.public_id)}</h1>`,
    entity.symbol ? `<p class="rl-entity-symbol">${escapeHtml(entity.symbol)}</p>` : "",
    '<section aria-label="Gene facts">',
    `<dl class="rl-entity-facts">${rows}</dl>`,
    "</section>",
    entity.description
      ? `<p class="rl-entity-description">${escapeHtml(entity.description)}</p>`
      : "",
    "</main>",
  ]
    .filter(Boolean)
    .join("\n");
}

export interface PlanEntityOptions {
  /** Normalized deployment prefix, e.g. `/` or `/soymutdb/`. */
  basePath?: string;
}

/**
 * Map validated entities onto the documents the build writes.
 *
 * An empty snapshot yields an empty plan — the caller then writes nothing and
 * the artifact keeps the SPA shell. Documents are ordered by path so two builds
 * of the same snapshot emit the same sequence.
 */
export function planEntityDocuments(
  snapshot: EntitySnapshot,
  options: PlanEntityOptions = {},
): EntityDocument[] {
  const basePath = options.basePath ?? "/";
  return snapshot.entities
    .map((entity) => {
      const templatePath: string = KIND_TEMPLATES[entity.kind];
      const path = templatePath.replace(":geneId", entity.public_id);
      const relativePath = `${path.replace(/^\/+|\/+$/g, "")}/index.html`;
      return {
        path,
        templatePath,
        title: entity.title,
        description: entity.description ?? undefined,
        relativePath,
        mainHtml: renderGeneMain(entity, basePath),
      };
    })
    .sort((left, right) => left.path.localeCompare(right.path));
}