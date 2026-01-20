"""Domain-specific exceptions for pressure myography analysis."""


class AnalysisError(Exception):
    """Base error for analysis failures."""


class MissingTraceError(AnalysisError):
    """Raised when a required trace is missing."""


class MissingPassiveDiameterError(AnalysisError):
    """Raised when passive diameter cannot be determined."""


class InvalidEventError(AnalysisError):
    """Raised when event definitions are invalid for analysis."""


class InvalidTimebaseError(AnalysisError):
    """Raised when the timebase is invalid or inconsistent."""
