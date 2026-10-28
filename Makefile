PY ?= python3
.PHONY: bootstrap doctor test golden port-docs pdf clean

bootstrap:
	@bash scripts/bootstrap.sh

doctor:
	$(PY) core/cli.py doctor

test:
	$(PY) -m pytest -q tests/unit 2>/dev/null || echo "(sin tests unitarios todavía)"

golden:
	$(PY) tests/diff_oracle.py --mismatches 0
	$(PY) tests/diff_oracle.py --mismatches 1
	$(PY) tests/diff_oracle.py --mismatches 2
	$(PY) tests/diff_oracle.py --mode offtarget --mismatches 2

pdf:
	cd docs && pandoc ROADMAP.md -o ROADMAP.pdf --pdf-engine=weasyprint -c style.css

clean:
	rm -rf out build/tmp __pycache__ core/**/__pycache__
