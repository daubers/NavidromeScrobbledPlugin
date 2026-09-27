PLUGIN_ID = navidrome-scrobbled
WASM_FILE = dist/plugin.wasm
NDP_FILE = dist/$(PLUGIN_ID).ndp

.PHONY: build package validate test clean

build: $(WASM_FILE)

$(WASM_FILE): plugin/__init__.py
	mkdir -p dist
	extism-py plugin/__init__.py -o $(WASM_FILE)

package: $(NDP_FILE)

$(NDP_FILE): $(WASM_FILE) manifest.json
	zip -j $(NDP_FILE) manifest.json $(WASM_FILE)

validate: package
	navidrome plugin validate $(NDP_FILE)

test:
	python3 -m unittest discover -s tests -v

clean:
	rm -rf dist
