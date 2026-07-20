"""Strict loader for private, bounded evaluation fixtures."""

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Never, cast
from uuid import UUID

from omnivox_protocol import AudioInput, RequestContext

from omnivox_evaluation.suite import EvaluationCase

MAX_MANIFEST_BYTES = 262_144
MAX_AUDIO_BYTES = 4_194_304
MAX_CASES = 1_000
_SCHEMA_VERSION = 1
_MANIFEST_FIELDS = {"cases", "schema_version"}
_CASE_FIELDS = {
    "audio_file",
    "case_id",
    "codec",
    "conversation_id",
    "request_id",
}
_CASE_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class EvaluationManifestError(ValueError):
    """A private evaluation manifest or fixture is invalid."""


@dataclass(frozen=True, slots=True)
class _ManifestCase:
    case_id: str
    audio_path: PurePosixPath
    conversation_id: str
    request_id: str


def load_evaluation_manifest(path: Path) -> tuple[EvaluationCase, ...]:
    """Load bounded private audio without retaining fixture paths in cases."""
    raw = _read_manifest(path)
    value = _decode_manifest(raw)
    manifest_cases = _parse_manifest(value)
    root = path.parent.resolve()
    return tuple(_load_case(root, case) for case in manifest_cases)


def _read_manifest(path: Path) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as error:
        message = "evaluation manifest is not readable"
        raise EvaluationManifestError(message) from error
    if not 1 <= size <= MAX_MANIFEST_BYTES:
        message = "evaluation manifest size is invalid"
        raise EvaluationManifestError(message)
    try:
        raw = path.read_bytes()
    except OSError as error:
        message = "evaluation manifest is not readable"
        raise EvaluationManifestError(message) from error
    if len(raw) > MAX_MANIFEST_BYTES:
        message = "evaluation manifest size is invalid"
        raise EvaluationManifestError(message)
    return raw


def _decode_manifest(raw: bytes) -> object:
    try:
        return cast(
            "object",
            json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        message = "evaluation manifest is not valid UTF-8 JSON"
        raise EvaluationManifestError(message) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            message = "evaluation manifest contains a duplicate field"
            raise EvaluationManifestError(message)
        value[key] = item
    return value


def _reject_json_constant(_value: str) -> Never:
    message = "evaluation manifest contains a non-finite number"
    raise EvaluationManifestError(message)


def _parse_manifest(value: object) -> tuple[_ManifestCase, ...]:
    if not isinstance(value, dict) or set(value) != _MANIFEST_FIELDS:
        message = "evaluation manifest fields do not match schema"
        raise EvaluationManifestError(message)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        message = "evaluation manifest schema version is unsupported"
        raise EvaluationManifestError(message)
    cases_value = value["cases"]
    if not isinstance(cases_value, list) or len(cases_value) > MAX_CASES:
        message = "evaluation manifest case list is invalid"
        raise EvaluationManifestError(message)

    cases = tuple(_parse_case(item) for item in cases_value)
    case_ids = [case.case_id for case in cases]
    request_ids = [case.request_id for case in cases]
    if len(case_ids) != len(set(case_ids)) or len(request_ids) != len(set(request_ids)):
        message = "evaluation case and request identifiers must be unique"
        raise EvaluationManifestError(message)
    return cases


def _parse_case(value: object) -> _ManifestCase:
    if not isinstance(value, dict) or set(value) != _CASE_FIELDS:
        message = "evaluation case fields do not match schema"
        raise EvaluationManifestError(message)
    case_id = value["case_id"]
    codec = value["codec"]
    if not isinstance(case_id, str) or _CASE_ID.fullmatch(case_id) is None:
        message = "evaluation case identifier is invalid"
        raise EvaluationManifestError(message)
    if codec != "opus":
        message = "evaluation audio codec is unsupported"
        raise EvaluationManifestError(message)
    return _ManifestCase(
        case_id=case_id,
        audio_path=_audio_path(value["audio_file"]),
        conversation_id=_canonical_uuid(value["conversation_id"], "conversation"),
        request_id=_canonical_uuid(value["request_id"], "request"),
    )


def _audio_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or "\\" in value:
        message = "evaluation audio path is invalid"
        raise EvaluationManifestError(message)
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or str(path) != value:
        message = "evaluation audio path is invalid"
        raise EvaluationManifestError(message)
    return path


def _canonical_uuid(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        message = f"evaluation {field_name} id must be a string"
        raise EvaluationManifestError(message)
    try:
        identifier = UUID(value)
    except ValueError as error:
        message = f"evaluation {field_name} id is invalid"
        raise EvaluationManifestError(message) from error
    if str(identifier) != value:
        message = f"evaluation {field_name} id is not canonical"
        raise EvaluationManifestError(message)
    return value


def _load_case(root: Path, case: _ManifestCase) -> EvaluationCase:
    try:
        candidate = (root / Path(*case.audio_path.parts)).resolve(strict=True)
        candidate.relative_to(root)
        size = candidate.stat().st_size
    except (OSError, ValueError) as error:
        message = "evaluation audio path is invalid"
        raise EvaluationManifestError(message) from error
    if not candidate.is_file() or not 1 <= size <= MAX_AUDIO_BYTES:
        message = "evaluation audio fixture size or type is invalid"
        raise EvaluationManifestError(message)
    try:
        audio = candidate.read_bytes()
    except OSError as error:
        message = "evaluation audio fixture is not readable"
        raise EvaluationManifestError(message) from error
    if not 1 <= len(audio) <= MAX_AUDIO_BYTES:
        message = "evaluation audio fixture size is invalid"
        raise EvaluationManifestError(message)
    return EvaluationCase(
        case_id=case.case_id,
        audio=AudioInput(codec="opus", data=audio),
        context=RequestContext(
            conversation_id=case.conversation_id,
            request_id=case.request_id,
        ),
    )
