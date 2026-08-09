# ADR: Staged `qantara.*` Namespace Migration

- Status: Proposed
- Target: a future compatibility-focused release, not `0.3.1`

## Context

The SDK lives under `qantara`, while historical runtime packages remain top-level: `adapters`, `gateway`, `providers`, and `discovery`. Public examples and third-party code may import both forms. Moving files directly would break imports, package resources, scripts, and downstream extensions.

## Decision

Do not perform a broad namespace move during the `0.3.1` hardening release. Prepare a staged migration with explicit compatibility shims and package-artifact tests.

## Proposed stages

1. Inventory every documented/imported module and every runtime resource path.
2. Define canonical `qantara.adapters`, `qantara.gateway`, `qantara.providers`, and `qantara.discovery` targets.
3. Add new packages without removing historical imports; ensure both resolve to the same public classes and avoid duplicate module state.
4. Update first-party imports and docs to canonical paths.
5. Emit narrowly scoped deprecation warnings only where they will not pollute normal gateway output.
6. Publish a migration guide and maintain shims for an explicitly documented compatibility window.
7. Remove shims only in a release whose changelog and versioning policy permit the break.

## Acceptance criteria

- Wheel and sdist smoke tests cover old and new imports.
- Static assets, protocols, and schemas resolve from installed artifacts.
- Adapter/provider entry points do not create duplicate registries or session state.
- Source-checkout commands, Docker entry points, and Python SDK examples work on all CI platforms.
- The release notes state the exact deprecation/removal timeline.

## Consequences

The package remains less tidy in `0.3.x`, but existing users keep a stable import surface while security and release changes stay reviewable. The eventual migration becomes a compatibility project rather than a mechanical directory move.
