# Ordinary updater subprocess fixture

`test_deployment_rehearsal.py` runs the ordinary `update.sh` plan/apply/status/
continue/reconcile entrypoints in disposable repositories. It keeps the real
client, fixed bootstrap, shell launcher, stdio owner, host backend, Git commands,
Linux lifecycle flock, phase journals, ciphertext framing, receive verification,
and helper-pin checks.

The only executable boundary replacements are Docker, curl (GitHub and provider
responses), and the network-only `git ls-remote` call. Other Git commands execute
the real binary. Unknown boundary commands fail closed. No Docker daemon/socket
or network is needed inside the fixture. Docker state, images, application
readiness and the in-container smoke validator are models, not real services.

`recovery_adapter.txt` is appended only inside each copied, committed fixture
repository. It replaces capture/encryption and isolated restore with explicit
synthetic evidence. The actual receive implementation still hashes, counts,
fsyncs and publishes the synthetic bytes without overwriting existing attempts.
A successful rehearsal therefore does not prove real encryption, full restore,
image startup, answer quality, provider billing or service downtime. Canonical
recovery and container rehearsals have separate acceptance evidence.

The lost-smoke case records one modeled provider call and then kills its own
ancestor stdio owner before the response is consumed. It checks that the real
journal records uncertainty, continuation refuses, read-only reconciliation
works, and no second provider call appears. It never kills a process outside the
fixture's own ancestry.

Enable pytest cases only inside an explicitly isolated Linux test environment:

```sh
BISQ_RUN_DEPLOYMENT_REHEARSAL=1 python3 -m pytest \
  api/tests/scripts/test_deployment_rehearsal.py
```

The standalone stdlib runner needs Git, Bash, flock, jq, OpenSSL and Python. Its
`--output` must name a new directory; failures and partial receipts are retained.
Use separate output directories for `success`, `preflight_refusal` and
`lost_smoke` scenarios. Do not reuse or mutate a failed operation to obtain a
passing result.
