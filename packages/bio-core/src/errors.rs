use thiserror::Error;

/// Stable error codes shared with the Python API layer.
///
/// The message never carries sequence content, file paths or credentials.
#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum BioCoreError {
    #[error("empty sequence")]
    EmptySequence,
    #[error("invalid character for the selected alphabet")]
    InvalidCharacter,
    #[error("unsupported alphabet for this operation")]
    UnsupportedAlphabet,
    #[error("sequence exceeds the configured size limit")]
    SequenceTooLong,
    #[error("input exceeds the configured budget")]
    BudgetExceeded,
    #[error("invalid coordinate: start must be >= 0 and stop must be > start")]
    InvalidInterval,
    #[error("integer overflow while computing coordinates")]
    CoordinateOverflow,
    #[error("unsupported parameter value")]
    UnsupportedParameter,
    #[error("genetic code is not implemented")]
    UnknownGeneticCode,
    #[error("invalid FASTA/FASTQ record")]
    InvalidRecord,
}

impl BioCoreError {
    /// Machine-readable code used by the PyO3 exception and the FastAPI envelope.
    pub const fn code(&self) -> &'static str {
        match self {
            Self::EmptySequence => "EMPTY_SEQUENCE",
            Self::InvalidCharacter => "INVALID_CHARACTER",
            Self::UnsupportedAlphabet => "UNSUPPORTED_ALPHABET",
            Self::SequenceTooLong => "SEQUENCE_TOO_LONG",
            Self::BudgetExceeded => "BUDGET_EXCEEDED",
            Self::InvalidInterval => "INVALID_INTERVAL",
            Self::CoordinateOverflow => "COORDINATE_OVERFLOW",
            Self::UnsupportedParameter => "UNSUPPORTED_PARAMETER",
            Self::UnknownGeneticCode => "UNKNOWN_GENETIC_CODE",
            Self::InvalidRecord => "INVALID_RECORD",
        }
    }
}
