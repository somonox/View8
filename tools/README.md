# Recovery Tools

## recover_from_snir.py

Rebuilds source-like JavaScript from View8 SNIR constant pools.

Settings-like module recovery:

```bash
python3 tools/recover_from_snir.py \
  /path/to/module.snir.json \
  --out /path/to/module.recovered.js \
  --source-label app/js/util/settings.jsc \
  --check
```

Generic constant-pool dump:

```bash
python3 tools/recover_from_snir.py \
  /path/to/module.snir.json \
  --out /tmp/module.constants.js \
  --kind generic \
  --check
```

`--kind auto` detects a settings-style module from exported userscript helpers.
Other modules fall back to a CommonJS file exposing `constantsByFunction` and
`objectConstants`.
