from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest
import yaml
from jsonschema import validate

TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
EXAMPLES_DIR = REPO_ROOT / "examples"
SCHEMA_PATH = REPO_ROOT / "specs" / "001-xml-to-relational-engine" / "contracts" / "mapping.schema.json"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES_DIR


@pytest.fixture
def example_mapping() -> Path:
    return EXAMPLES_DIR / "mapping.yaml"


@pytest.fixture
def schema_path() -> Path:
    return SCHEMA_PATH


@pytest.fixture
def validate_mapping_contract() -> Callable[[Path], None]:
    def validate_mapping(mapping_path: Path) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        instance = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
        validate(instance=instance, schema=schema)

    return validate_mapping


@pytest.fixture
def large_xml_writer(tmp_path: Path) -> Callable[[int, str], Path]:
    def write(count: int, name: str = "large.xml") -> Path:
        path = tmp_path / name
        with path.open("w", encoding="utf-8") as handle:
            handle.write('<?xml version="1.0" encoding="UTF-8"?>\n<Records>\n')
            for index in range(count):
                handle.write(
                    f'  <Record id="{index}"><Value>value-{index}</Value></Record>\n'
                )
            handle.write("</Records>\n")
        return path

    return write
