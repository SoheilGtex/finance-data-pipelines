.PHONY: install dev lint format-check test smoke benchmark-small ci

install:
	python -m pip install .

dev:
	python -m pip install -e '.[dev]'

lint:
	ruff check .

format-check:
	ruff format --check .

test:
	pytest -q

smoke:
	fdp run-all --source synthetic --seed 20270916 --rows 1000 --output-dir .repro/smoke

benchmark-small:
	python scripts/benchmark.py --output-dir .repro/benchmark-small --scales 1000 --repetitions 1

ci: lint format-check test
