import json

import jsonschema

from vhhs.paths import CONTRACTS
from vhhs.redpanda_io import iter_events


def _validator():
    schema = json.loads((CONTRACTS / "temperature_event.schema.json").read_text())
    return jsonschema.Draft202012Validator(schema)


def test_snapshot_events_match_the_contract():
    validator = _validator()
    count = 0
    for event in iter_events(limit=200):
        validator.validate(event)
        count += 1
    assert count == 200


def test_impossible_temperature_is_rejected():
    validator = _validator()
    event = {
        "lga_code": "20110",
        "event_time": "2026-01-16T00:00:00+11:00",
        "temp_max_c": 80,
        "temp_min_c": 20,
        "temp_mean_c": 50,
        "source": "archive",
    }
    errors = list(validator.iter_errors(event))
    assert errors
