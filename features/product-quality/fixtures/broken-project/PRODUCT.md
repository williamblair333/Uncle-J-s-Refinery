# brittle

**Core job:** someone with a text file gets a summary of it in one command.

Fixture for the first-run gate. Expected result: **FAIL**, even though the core
command exits 0. The gate must catch it on the observable proofs.

```yaml
verify:
  image: debian:bookworm-slim
  network: required
  install:
    - apt-get update && apt-get install -y python3
  run: python3 brittle.py sample.txt
  expect:
    - stdout_contains: "summary written"
    - file: /tmp/brittle.out
    - exit_code: 0
  time_target_seconds: 300
```
