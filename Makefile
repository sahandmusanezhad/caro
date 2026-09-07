PY := PYTHONPATH=. python3

.PHONY: test test-w0 test-w1 test-w2 demo policy clean

test: test-w0 test-w1 test-w2

test-w0:
	@$(PY) tests/test_tracking.py

test-w1:
	@$(PY) tests/test_appraisal.py

test-w2:
	@$(PY) tests/test_agents.py

demo:
	@$(PY) demo/export_demo.py
	@echo "open demo/index.html"

policy:
	@$(PY) -c "from caro.agents import DEFAULT_POLICY; print(DEFAULT_POLICY.explain())"

clean:
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
