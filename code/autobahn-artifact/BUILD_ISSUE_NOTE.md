# Build Issue Note

The Autobahn codebase has a known RocksDB compilation issue with newer Rust toolchains due to bindgen compatibility. 

## Quick Fix Options

1. **Use older Rust version** (recommended):
   ```bash
   rustup install 1.70.0
   rustup override set 1.70.0
   cargo build --release --features benchmark
   ```

2. **Update bindgen** (if possible):
   ```bash
   cargo update -p bindgen
   ```

3. **Skip RocksDB** (if store is optional):
   - May require code modifications

## For Testing

If you have a pre-built binary, you can:
1. Place it in `target/release/node` or `target/debug/node`
2. Run the test script - it will use the existing binary

## Manual Test

If build succeeds, run:
```bash
cd /Users/iliya/Dev/Blockchain/code/autobahn-artifact
python3 run_fissure_attack.py
```

Then calculate ASR:
```bash
python3 scripts/calculate-fissure-asr.py logs/primary-*.log
```





