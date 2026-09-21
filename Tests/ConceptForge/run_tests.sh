#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../.." && pwd)"
export PYTHONPATH="${REPO_ROOT}/ConceptForge${PYTHONPATH:+:${PYTHONPATH}}"

python3 -m unittest discover -s "$TEST_DIR" -p 'test_*.py' -v

new_subject="$(bash "${REPO_ROOT}/everspark" concept new cli-subject "CLI Subject")"
python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["subject_id"] == "cli-subject"' <<< "$new_subject"

validate_result="$(bash "${REPO_ROOT}/everspark" concept validate "${REPO_ROOT}/ConceptForge/Examples/character_subject.example.json")"
python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["ok"] is True' <<< "$validate_result"

compile_result="$(bash "${REPO_ROOT}/everspark" concept compile "${REPO_ROOT}/ConceptForge/Examples/character_subject.example.json")"
python3 -c 'import json,sys; value=json.load(sys.stdin); assert "amber" in value["positive_prompt"]' <<< "$compile_result"

printf 'Concept Forge CLI tests: OK\n'
