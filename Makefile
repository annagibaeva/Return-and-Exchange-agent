.PHONY: test run setup install

test:
	python evals/test_golden_set.py
	python evals/test_usage.py

run:
	python app.py

install:
	pip install -r requirements.txt

setup: install
	@echo "Copy .env.example to .env and set ANTHROPIC_API_KEY"
