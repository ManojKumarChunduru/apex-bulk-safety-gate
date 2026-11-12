PYTHON ?= python3
FIXTURE ?= fixture

.PHONY: install lint test gate explain experiments receipts evidence verify clean

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check src tests experiments tools
	$(PYTHON) -m ruff format --check src tests experiments tools

test:
	$(PYTHON) -m pytest --junitxml=reports/junit.xml --cov=absg --cov-report=json:reports/coverage.json --cov-report=xml:reports/coverage.xml --cov-report=term-missing

# The headline run. Exit code 1 is the expected outcome on the fixture: breaches were found.
gate:
	-$(PYTHON) -m absg gate --project $(FIXTURE) --coverage $(FIXTURE)/coverage/test-result-codecoverage.json

explain:
	$(PYTHON) -m absg explain TaskAssignmentTrigger --project $(FIXTURE)

experiments:
	$(PYTHON) experiments/exp01_breach_census.py
	$(PYTHON) experiments/exp02_coverage_vs_bulk.py
	$(PYTHON) experiments/exp03_resolution.py
	$(PYTHON) experiments/exp04_undecidable.py

receipts:
	$(PYTHON) tools/collect_metrics.py --skip-tests
	$(PYTHON) tools/check_numbers.py

evidence:
	$(PYTHON) tools/render_architecture.py
	$(PYTHON) tools/capture_screenshots.py
	$(PYTHON) tools/record_demo.py

verify: lint test experiments receipts

clean:
	rm -rf reports build dist .pytest_cache .ruff_cache src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
