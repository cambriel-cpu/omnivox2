import pytest

_REAL_PROVIDER_OPTION = "--run-real-provider"
_REAL_PROVIDER_MARKER = "real_provider"


def should_skip_real_provider(*, opted_in: bool, marked: bool) -> bool:
    return marked and not opted_in


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        _REAL_PROVIDER_OPTION,
        action="store_true",
        default=False,
        help="run explicitly marked real-provider tests",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    opted_in = bool(config.getoption(_REAL_PROVIDER_OPTION))
    skip = pytest.mark.skip(reason="requires explicit --run-real-provider opt-in")
    for item in items:
        marked = item.get_closest_marker(_REAL_PROVIDER_MARKER) is not None
        if should_skip_real_provider(opted_in=opted_in, marked=marked):
            item.add_marker(skip)
