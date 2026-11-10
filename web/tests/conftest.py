import pytest

from tests.helpers import seeded


@pytest.fixture
def store():
    return seeded()
