.PHONY: verify test demo replay lint format typecheck

verify: test demo replay

test:
	PYTHONPATH=src python -m unittest discover -s tests -v

demo:
	PYTHONPATH=src python -m catalyst.demo

replay:
	PYTHONPATH=src python -m catalyst.replay_demo

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy src
