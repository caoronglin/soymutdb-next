//! SoyMutDB biological computation core.
//!
//! Single Rust kernel exposing sequence algorithms (Rust-Bio), typed k-mers
//! and standard translation (bio-seq), half-open interval overlap
//! (rust-lapper) and bounded format inspection (noodles).  The Python API and
//! Celery worker own all authorization, release/assembly resolution, database
//! access and object storage; this crate receives only validated bytes.

pub mod coordinates;
pub mod errors;
pub mod formats;
pub mod intervals;
pub mod sequence;
pub mod translation;

#[cfg(feature = "python")]
pub mod bindings;

pub use errors::BioCoreError;
pub use sequence::Alphabet;

/// Engine identification returned in every API result's metadata.
pub const ENGINE: &str = "soymutdb-bio-core";
pub const ENGINE_VERSION: &str = env!("CARGO_PKG_VERSION");
