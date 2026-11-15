PY := .venv/bin/python

.PHONY: build sim verify screenshots clean help

help:
	@echo "make build       - regenerate mjcf/world.xml from spec/arena.yaml"
	@echo "make sim         - open interactive MuJoCo viewer with the world"
	@echo "make verify      - run env sanity checks"
	@echo "make screenshots - render docs/screenshots/*.png"
	@echo "make clean       - remove generated mjcf/ output"

build:
	$(PY) scripts/build_world.py

sim:
	$(PY) scripts/run_viewer.py

verify:
	$(PY) scripts/verify_env.py

screenshots:
	$(PY) scripts/render_screenshot.py

clean:
	rm -f mjcf/world.xml
