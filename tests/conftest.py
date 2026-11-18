import pytest

from anonymizer.dataset import generate
from anonymizer.detection import Detector


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    directory = tmp_path_factory.mktemp("synthetic")
    return directory, generate(directory)


@pytest.fixture(scope="session")
def detector():
    return Detector()
