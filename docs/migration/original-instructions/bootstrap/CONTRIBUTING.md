# Contributing to SARGuardian Monorepo

## Before changing source code
1. Read [AGENTS.md](AGENTS.md) and the relevant architecture/science constraints.
2. Identify the authoritative source repository, branch, and commit for the code being changed.
3. Confirm whether the change is migration-only or an intentional product/science change.
4. Keep migration-only PRs free of algorithm changes.

## Branch and pull request rules
- Do not commit directly to `main`.
- Use a focused branch and a draft PR while migration is in progress.
- Include source provenance and file-level integrity evidence for imported code.
- Explain any path, import, workflow, build-root, or environment-name changes.
- Never include secrets, service-account files, raw NISAR products, or private data in commits.

## Required evidence
A migration PR should state:
- source repository/ref/commit;
- imported and excluded paths;
- file counts and SHA-256 integrity result;
- relevant tests and workflow runs;
- deployment/API impact;
- rollback path;
- confirmation that scientific output/status semantics are unchanged, or a separate science-review record if intentionally changed.

## Review bar
A passing build alone is not sufficient. Review source provenance, workflow event scope, cross-repository dispatch, callback contracts, retention, secret handling, and scientific meaning.
