.PHONY: verify test demo lint format typecheck

verify: test demo

test:
	PYTHONPATH=src python -m unittest discover -s tests -v

demo:
	PYTHONPATH=src python -m catalyst.demo

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy src

