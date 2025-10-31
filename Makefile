.PHONY: test test-verbose clean backtest-vix backtest-trend backtest-calm help

help:
	@echo "AlgoStrangle - Make Commands"
	@echo "============================"
	@echo "make test           - Run unit tests"
	@echo "make test-verbose   - Run tests with verbose output"
	@echo "make backtest-vix   - Run VIX spike backtest scenario"
	@echo "make backtest-trend - Run trend day backtest scenario"
	@echo "make backtest-calm  - Run calm period backtest scenario"
	@echo "make clean          - Clean cache and logs"

test:
	pytest tests/ -v

test-verbose:
	pytest tests/ -v -s

backtest-vix:
	@echo "Running VIX spike scenario (June 2024)..."
	python run.py backtest --start 2024-06-03 --end 2024-06-14

backtest-trend:
	@echo "Running trend day scenario..."
	python run.py backtest --start 2024-07-15 --end 2024-07-15

backtest-calm:
	@echo "Running calm period scenario..."
	python run.py backtest --start 2024-05-01 --end 2024-05-15

clean:
	@echo "Cleaning cache and temporary files..."
	rm -rf __pycache__ */__pycache__ */*/__pycache__
	rm -rf .pytest_cache
	rm -rf *.pyc */*.pyc */*/*.pyc
	@echo "Done. Logs in logs/ are preserved."
