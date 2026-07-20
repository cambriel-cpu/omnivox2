import pytest

from tests.conftest import should_skip_real_provider


@pytest.mark.parametrize(
    ("opted_in", "marked", "expected"),
    [
        (False, True, True),
        (True, True, False),
        (False, False, False),
        (True, False, False),
    ],
)
def test_real_provider_skip_policy(
    *, opted_in: bool, marked: bool, expected: bool
) -> None:
    assert should_skip_real_provider(opted_in=opted_in, marked=marked) is expected


@pytest.mark.real_provider
def test_real_provider_marker_requires_opt_in(request: pytest.FixtureRequest) -> None:
    assert request.config.getoption("--run-real-provider") is True
