/**
 * CSP composition, parsing and comparison — shared by the build-time writers and
 * the gates that check their output.
 *
 * ## Why this is a separate module
 *
 * The portal policy used to be assembled in three places that had to agree by
 * hand: the `<meta>` tag in `index.html`, the SSG template in
 * `apps/web/scripts/base-template.ts`, and a static `_headers` file. They
 * drifted, and the failure mode is silent — browsers take the *intersection* of
 * a meta policy and a header policy, so the narrowest copy wins and a
 * forgotten origin shows up as "the API call just fails".
 *
 * One builder (`composeCsp`) plus one parser (`parseCsp`) removes the
 * hand-agreement. Everything that emits a policy composes it here, and every
 * gate compares parsed directive maps rather than strings, so an ordering or
 * whitespace difference is not mistaken for a policy difference.
 *
 * This module is dependency-free and portable on purpose. The portal reaches
 * it from browser code (`buildCsp()` lives in src/lib/deployment.ts, which the
 * SPA imports for URL helpers), so nothing here may pull in a Node built-in.
 * Inline-script hashing needs `node:crypto` and therefore lives in the sibling
 * `./csp-hash` module, which only build scripts import.
 */

/** Directive order used by every emitted policy. */
export const CSP_DIRECTIVE_ORDER = [
  "default-src",
  "script-src",
  "style-src",
  "img-src",
  "font-src",
  "connect-src",
  "frame-src",
  "base-uri",
  "form-action",
  "frame-ancestors",
  "object-src",
  "worker-src",
] as const;

export type CspDirective = (typeof CSP_DIRECTIVE_ORDER)[number];

/** A parsed policy: directive name → its source tokens. */
export type CspMap = Map<string, string[]>;

/**
 * Render a policy.
 *
 * Values are arrays so callers can spread conditional sources without building
 * stray `""` tokens (an empty token makes the directive invalid). Unknown
 * directive names are emitted after the known ones, in the order given, so a
 * caller is never silently ignored.
 */
export function composeCsp(directives: Partial<Record<CspDirective | string, string[]>>): string {
  const known = CSP_DIRECTIVE_ORDER.filter((name) => directives[name]?.length);
  const extra = Object.keys(directives).filter(
    (name) => !(CSP_DIRECTIVE_ORDER as readonly string[]).includes(name) && directives[name]?.length,
  );
  return [...known, ...extra]
    .map((name) => `${name} ${(directives[name] ?? []).join(" ")}`.trim())
    .join("; ");
}

/**
 * Parse a policy into directive → tokens.
 *
 * Tolerates the trailing `;` most authors write, and collapses internal
 * whitespace, so comparison is about policy and not formatting.
 */
export function parseCsp(policy: string): CspMap {
  const map: CspMap = new Map();
  for (const raw of policy.split(";")) {
    const clause = raw.trim();
    if (!clause) continue;
    const [name, ...tokens] = clause.split(/\s+/);
    map.set(name.toLowerCase(), tokens);
  }
  return map;
}

export interface DirectiveComparison {
  /** Present in both, with different tokens. */
  differing: string[];
  /** Present only in `expected`. */
  missing: string[];
  /** Present only in `actual`. */
  unexpected: string[];
}

/**
 * Compare two policies directive by directive.
 *
 * `only` restricts the comparison to a subset — the gates use it to assert the
 * directives that must match byte-for-byte while deliberately allowing
 * `script-src` / `connect-src` / `frame-src` to differ between the development
 * proxy and the generated static-host policy.
 */
export function compareCsp(
  expected: string,
  actual: string,
  options: { only?: readonly string[]; ignore?: readonly string[] } = {},
): DirectiveComparison {
  const expectedMap = parseCsp(expected);
  const actualMap = parseCsp(actual);
  const ignore = new Set(options.ignore ?? []);
  const names = options.only
    ? options.only.filter((name) => !ignore.has(name))
    : [...new Set([...expectedMap.keys(), ...actualMap.keys()])].filter((name) => !ignore.has(name));

  const differing: string[] = [];
  const missing: string[] = [];
  const unexpected: string[] = [];

  for (const name of names) {
    const want = expectedMap.get(name);
    const got = actualMap.get(name);
    if (want && !got) missing.push(name);
    else if (!want && got) unexpected.push(name);
    else if (want && got && want.join(" ") !== got.join(" ")) differing.push(name);
  }
  return { differing, missing, unexpected };
}

/** Convenience predicate over `compareCsp`. */
export function directivesEqual(
  expected: string,
  actual: string,
  options: { only?: readonly string[]; ignore?: readonly string[] } = {},
): boolean {
  const result = compareCsp(expected, actual, options);
  return result.differing.length === 0 && result.missing.length === 0 && result.unexpected.length === 0;
}
