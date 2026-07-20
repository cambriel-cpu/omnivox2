"""Deterministic, content-free evaluation measurements."""

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from unicodedata import normalize

MAX_REFERENCE_CHARACTERS = 16_000
MAX_HYPOTHESIS_CHARACTERS = 16_000
MAX_ACCURACY_WORDS = 2_048
MAX_PROPER_NOUNS = 64
MAX_PROPER_NOUN_CHARACTERS = 128


class EvaluationMeasurementError(ValueError):
    """A requested measurement or observation is invalid."""


class RecoveryScenario(StrEnum):
    """Hardware-independent fault scenarios measured by the harness."""

    PACKET_LOSS = "packet_loss"
    PROVIDER_TIMEOUT = "provider_timeout"
    GATEWAY_RESTART = "gateway_restart"
    INTERRUPTION = "interruption"


@dataclass(frozen=True, slots=True)
class AccuracyReference:
    """Private expected speech used only to calculate content-free counts."""

    reference_transcript: str = field(repr=False)
    proper_nouns: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class AccuracyMeasurement:
    """Content-free word-error and proper-noun counts for one case."""

    word_errors: int
    reference_words: int
    proper_nouns_correct: int
    proper_nouns_total: int

    def __post_init__(self) -> None:
        """Reject impossible or misleading aggregate inputs."""
        counts = (
            self.word_errors,
            self.reference_words,
            self.proper_nouns_correct,
            self.proper_nouns_total,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            message = "accuracy counts must be non-negative integers"
            raise EvaluationMeasurementError(message)
        if self.reference_words == 0:
            message = "accuracy reference word count must be positive"
            raise EvaluationMeasurementError(message)
        if self.proper_nouns_correct > self.proper_nouns_total:
            message = "correct proper nouns cannot exceed the annotated total"
            raise EvaluationMeasurementError(message)

    def as_record(self) -> dict[str, int | float | None]:
        """Return accuracy counts and their deterministic rates."""
        return {
            "word_errors": self.word_errors,
            "reference_words": self.reference_words,
            "word_error_rate_percent": _percentage(
                self.word_errors, self.reference_words
            ),
            "proper_nouns_correct": self.proper_nouns_correct,
            "proper_nouns_total": self.proper_nouns_total,
            "proper_noun_accuracy_percent": _percentage(
                self.proper_nouns_correct, self.proper_nouns_total
            ),
        }


@dataclass(frozen=True, slots=True)
class RecoveryObservation:
    """Content-free result supplied by a deterministic fault driver."""

    recovered: bool
    recovery_ms: float | None

    def __post_init__(self) -> None:
        """Reject observations that could produce misleading metrics."""
        if type(self.recovered) is not bool:
            message = "recovered must be a boolean"
            raise EvaluationMeasurementError(message)
        if self.recovered:
            if self.recovery_ms is None or not _valid_duration(self.recovery_ms):
                message = "successful recovery requires a valid duration"
                raise EvaluationMeasurementError(message)
        elif self.recovery_ms is not None:
            message = "unsuccessful recovery cannot have a duration"
            raise EvaluationMeasurementError(message)


@dataclass(frozen=True, slots=True)
class RecoveryMeasurement:
    """A recovery observation correlated with its public scenario name."""

    scenario: RecoveryScenario
    recovered: bool
    recovery_ms: float | None

    def __post_init__(self) -> None:
        """Validate values even when a report is created outside the runner."""
        if not isinstance(self.scenario, RecoveryScenario):
            message = "recovery scenario is invalid"
            raise EvaluationMeasurementError(message)
        RecoveryObservation(self.recovered, self.recovery_ms)

    def as_record(self) -> dict[str, object]:
        """Return a machine-readable recovery record."""
        return {
            "scenario": self.scenario.value,
            "recovered": self.recovered,
            "recovery_ms": self.recovery_ms,
        }


def validate_accuracy_reference(reference: AccuracyReference) -> None:
    """Validate a bounded private accuracy reference."""
    if not isinstance(reference.reference_transcript, str):
        message = "accuracy reference transcript must be text"
        raise EvaluationMeasurementError(message)
    if not 1 <= len(reference.reference_transcript) <= MAX_REFERENCE_CHARACTERS:
        message = "accuracy reference transcript length is invalid"
        raise EvaluationMeasurementError(message)
    reference_tokens = _tokens(reference.reference_transcript)
    if not reference_tokens:
        message = "accuracy reference transcript has no words"
        raise EvaluationMeasurementError(message)
    if len(reference_tokens) > MAX_ACCURACY_WORDS:
        message = "accuracy reference transcript has too many words"
        raise EvaluationMeasurementError(message)
    _validate_proper_nouns(reference_tokens, reference.proper_nouns)


def _validate_proper_nouns(
    reference_tokens: list[str],
    proper_nouns: tuple[str, ...],
) -> None:
    """Validate bounded, unique annotations against normalized reference words."""
    if len(proper_nouns) > MAX_PROPER_NOUNS:
        message = "accuracy proper-noun count is invalid"
        raise EvaluationMeasurementError(message)

    normalized_terms: set[tuple[str, ...]] = set()
    for proper_noun in proper_nouns:
        if not isinstance(proper_noun, str):
            message = "accuracy proper noun must be text"
            raise EvaluationMeasurementError(message)
        if not 1 <= len(proper_noun) <= MAX_PROPER_NOUN_CHARACTERS:
            message = "accuracy proper noun length is invalid"
            raise EvaluationMeasurementError(message)
        term = tuple(_tokens(proper_noun))
        if not term or term in normalized_terms:
            message = "accuracy proper nouns must be unique words"
            raise EvaluationMeasurementError(message)
        if not _contains(reference_tokens, term):
            message = "accuracy proper noun is absent from the reference"
            raise EvaluationMeasurementError(message)
        normalized_terms.add(term)


def measure_accuracy(
    reference: AccuracyReference,
    hypothesis: str,
) -> AccuracyMeasurement:
    """Calculate deterministic WER and proper-noun counts without retaining text."""
    validate_accuracy_reference(reference)
    if not isinstance(hypothesis, str):
        message = "accuracy hypothesis must be text"
        raise EvaluationMeasurementError(message)
    if len(hypothesis) > MAX_HYPOTHESIS_CHARACTERS:
        message = "accuracy hypothesis has too many characters"
        raise EvaluationMeasurementError(message)
    reference_tokens = _tokens(reference.reference_transcript)
    hypothesis_tokens = _tokens(hypothesis)
    if len(hypothesis_tokens) > MAX_ACCURACY_WORDS:
        message = "accuracy hypothesis has too many words"
        raise EvaluationMeasurementError(message)
    proper_nouns = tuple(tuple(_tokens(value)) for value in reference.proper_nouns)
    return AccuracyMeasurement(
        word_errors=_levenshtein(reference_tokens, hypothesis_tokens),
        reference_words=len(reference_tokens),
        proper_nouns_correct=sum(
            _contains(hypothesis_tokens, proper_noun) for proper_noun in proper_nouns
        ),
        proper_nouns_total=len(proper_nouns),
    )


def _tokens(value: str) -> list[str]:
    normalized = normalize("NFKC", value).casefold()
    tokens: list[str] = []
    current: list[str] = []
    for character in normalized:
        if character.isalnum():
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def _levenshtein(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_word in enumerate(reference, start=1):
        current = [reference_index]
        for hypothesis_index, hypothesis_word in enumerate(hypothesis, start=1):
            substitution = previous[hypothesis_index - 1] + (
                reference_word != hypothesis_word
            )
            current.append(
                min(previous[hypothesis_index] + 1, current[-1] + 1, substitution)
            )
        previous = current
    return previous[-1]


def _contains(words: list[str], phrase: tuple[str, ...]) -> bool:
    width = len(phrase)
    return any(
        tuple(words[index : index + width]) == phrase for index in range(len(words))
    )


def _percentage(numerator: int, denominator: int) -> float | None:
    return (numerator / denominator) * 100.0 if denominator else None


def _valid_duration(value: float) -> bool:
    return type(value) in {int, float} and isfinite(value) and value >= 0.0
