---
id: bisq1-build-jdk
title: Selecting the Java toolchain when building Bisq 1
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
risk_level: low
reviewed_by: ai-review:codex:knowledge-batch-20260918
reviewed_at: '2026-09-18T08:30:52.377693+00:00'
source_refs:
- https://github.com/bisq-network/bisq/blob/master/docs/build.md
---
## Canonical Support Answer

Follow the build instructions for the exact Bisq 1 branch or release being compiled. Installing a JDK does not necessarily change the compiler selected by the shell or the JVM selected by Gradle.

Check `javac -version` and `./gradlew --version`. If either selects the wrong installed JDK, set `JAVA_HOME` and `PATH` to the version required by that checkout. Use the repository's Gradle wrapper.

The official Bisq 1 master build instructions checked on 2026-09-18 specify JDK 21. Historical releases can differ, so do not teach a timeless Java 11/15-only restriction or infer supported versions from an unrelated installed compiler. This is a source-build diagnostic, not a requirement to replace the JVM bundled in an ordinary desktop installer.

## Evidence / Sources

- https://github.com/bisq-network/bisq/blob/master/docs/build.md

## Review Notes

Independently reviewed by the parent AI reviewer after individual candidate review. Reviewer: `ai-review:codex:knowledge-batch-20260918`. Sources checked on 2026-09-18; verify release-sensitive behavior against the user's installed version.

## Last Change Summary

Replaced obsolete compiler lists with exact-checkout instructions and observable shell/Gradle version checks.
