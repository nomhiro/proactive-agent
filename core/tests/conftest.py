import pytest

from vehicle_core.seed import Dataset, build_dataset


@pytest.fixture
def dataset() -> Dataset:
    return build_dataset()
