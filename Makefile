PYTHON ?= python3
CATALOG ?= benchmarks/v1

.PHONY: validate test smoke

validate:
	$(PYTHON) -m mcbench.cli validate $(CATALOG)

test:
	$(PYTHON) -m pytest -q

smoke: validate
	$(PYTHON) -m mcbench.cli benchmark $(CATALOG) --output-dir runs/catalog-smoke
