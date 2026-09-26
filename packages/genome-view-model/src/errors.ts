/** Raised when an operation would compare intervals across assemblies. */
export class AssemblyMismatchError extends Error {
  constructor(left: string, right: string) {
    super(
      `refusing to compare intervals across assemblies: '${left}' vs '${right}' ` +
        "(assemblies are distinct namespaces; DB-CORE-3)",
    );
    this.name = "AssemblyMismatchError";
  }
}

/** Raised for malformed coordinates (non-integer, start > end, or < 1). */
export class InvalidCoordinateError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidCoordinateError";
  }
}
