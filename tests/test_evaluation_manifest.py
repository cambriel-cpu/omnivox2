import json
from pathlib import Path

import pytest
from omnivox_evaluation import (
    MAX_MANIFEST_BYTES,
    EvaluationManifestError,
    load_evaluation_manifest,
)
from omnivox_protocol import AudioInput, RequestContext

CONVERSATION_ID = "00000000-0000-4000-8000-000000000002"
REQUEST_ID = "00000000-0000-4000-8000-000000000003"


def valid_case(**overrides: object) -> dict[str, object]:
    case: dict[str, object] = {
        "case_id": "clock-basic",
        "audio_file": "audio/clock-basic.opus",
        "codec": "opus",
        "conversation_id": CONVERSATION_ID,
        "request_id": REQUEST_ID,
    }
    case.update(overrides)
    return case


def write_manifest(root: Path, cases: list[dict[str, object]]) -> Path:
    path = root / "manifest.json"
    path.write_text(
        json.dumps({"schema_version": 1, "cases": cases}),
        encoding="utf-8",
    )
    return path


def test_manifest_loads_private_audio_without_retaining_its_path(
    tmp_path: Path,
) -> None:
    audio_directory = tmp_path / "audio"
    audio_directory.mkdir()
    (audio_directory / "clock-basic.opus").write_bytes(b"private opus bytes")

    cases = load_evaluation_manifest(write_manifest(tmp_path, [valid_case()]))

    assert cases[0].case_id == "clock-basic"
    assert cases[0].audio == AudioInput(codec="opus", data=b"private opus bytes")
    assert cases[0].context == RequestContext(
        conversation_id=CONVERSATION_ID,
        request_id=REQUEST_ID,
    )
    assert "clock-basic.opus" not in repr(cases)


def test_manifest_rejects_oversize_before_json_parsing(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(b"{" + (b"x" * MAX_MANIFEST_BYTES))

    with pytest.raises(EvaluationManifestError, match="size"):
        load_evaluation_manifest(path)


def test_manifest_rejects_duplicate_json_fields(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        '{"schema_version":1,"schema_version":1,"cases":[]}',
        encoding="utf-8",
    )

    with pytest.raises(EvaluationManifestError, match="duplicate"):
        load_evaluation_manifest(path)


def test_manifest_rejects_parent_path_traversal(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    (tmp_path / "outside.opus").write_bytes(b"private audio")
    path = write_manifest(
        private_root,
        [valid_case(audio_file="../outside.opus")],
    )

    with pytest.raises(EvaluationManifestError, match="path"):
        load_evaluation_manifest(path)


@pytest.mark.parametrize(
    "cases",
    [
        [valid_case(), valid_case(audio_file="audio/second.opus")],
        [
            valid_case(),
            valid_case(
                case_id="second-case",
                audio_file="audio/second.opus",
            ),
        ],
    ],
)
def test_manifest_rejects_duplicate_case_or_request_ids(
    tmp_path: Path,
    cases: list[dict[str, object]],
) -> None:
    with pytest.raises(EvaluationManifestError, match="unique"):
        load_evaluation_manifest(write_manifest(tmp_path, cases))


@pytest.mark.parametrize(
    "override",
    [
        {"unexpected": True},
        {"case_id": "Invalid ID"},
        {"codec": "wav"},
        {"request_id": "NOT-A-UUID"},
    ],
)
def test_manifest_rejects_invalid_case_schema(
    tmp_path: Path,
    override: dict[str, object],
) -> None:
    with pytest.raises(EvaluationManifestError):
        load_evaluation_manifest(write_manifest(tmp_path, [valid_case(**override)]))
