import pytest

from minimq import Broker


@pytest.fixture
def broker(tmp_path):
    b = Broker(data_dir=str(tmp_path / "mq"))
    yield b
    b.close()


@pytest.fixture
def mem_broker():
    b = Broker()  # pure in-memory
    yield b
    b.close()
