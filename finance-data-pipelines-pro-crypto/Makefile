install:
	python -m pip install --upgrade pip
	pip install -r requirements.txt

dev: install
	pip install -r requirements-dev.txt
	pre-commit install

format:
	black .
	isort .

lint:
	flake8 .

test:
	pytest -q

run:
	python -m fdp.cli run-all
