import pytest

from vehicle_core.impact import Graph
from vehicle_core.seed import Dataset, build_dataset


@pytest.fixture
def dataset() -> Dataset:
    return build_dataset()


@pytest.fixture
def graph(dataset: Dataset) -> Graph:
    return Graph.from_artifacts(dataset.artifacts)
