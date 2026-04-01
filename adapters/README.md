# Adapters

This directory is for downstream runtime adapters.

Purpose:

- isolate Qantara from runtime-specific integration details
- keep the core gateway testable without a real runtime binding
- support mocked adapter implementations during M0 and M1

Expected contents later:

- adapter interface definitions
- mock adapter for local gateway testing
- runtime-specific adapter implementations once integration validation begins
