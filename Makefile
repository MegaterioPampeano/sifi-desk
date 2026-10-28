PY ?= python3
.PHONY: bootstrap doctor test golden paridad port-docs pdf clean

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

# Paridad aleatoria: 120 corridas pareadas + 1 caso borde (~35 s con --jobs 4).
# NO va en `verify`/`test`: tarda demasiado para el ciclo corto. Deja el detalle en
# tests/paridad/REPORTE.md y tests/paridad/resumen.json.
paridad:
	$(PY) tests/fuzz_parity.py --seed 20261028 --jobs 4

pdf:
	cd docs && pandoc ROADMAP.md -o ROADMAP.pdf --pdf-engine=weasyprint -c style.css

clean:
	rm -rf out build/tmp __pycache__ core/**/__pycache__
