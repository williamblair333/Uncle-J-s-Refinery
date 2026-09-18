# tinycount

**Core job:** someone with a text file gets its word count in one command.

Fixture for the first-run gate. Expected result: **PASS**.

```yaml
verify:
  image: debian:bookworm-slim
  network: required
  install:
    - apt-get update && apt-get install -y python3
  run: python3 tinycount.py sample.txt
  expect:
    - stdout_contains: "counted 9 words"
    - file: /tmp/tinycount.out
    - exit_code: 0
  time_target_seconds: 300
```
