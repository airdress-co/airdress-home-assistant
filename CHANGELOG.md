# Changelog

Versions are pre-releases until 0.1.0, shown in HACS only to users who opt in
to betas. release-please writes them in the form `0.1.0-b4`; Home Assistant
and HACS read that as the same version as `0.1.0b4`. Entries from 0.1.0-b4 on
are generated from conventional commits; the ones below were written by hand
from the history before that.

## [0.1.0-b4](https://github.com/airdress-co/airdress-home-assistant/compare/v0.1.0-b3...v0.1.0-b4) (2026-09-29)


### Bug Fixes

* **translations:** German for re-authentication, notify and location ([76ae042](https://github.com/airdress-co/airdress-home-assistant/commit/76ae042bd7b98a4a13f4357091a0ccb609f829a7))

## 0.1.0b3 (2026-09-29)

The first release, a GitHub pre-release for HACS. Generated from the core
integration at `00cfe612`; the manifest pins `airdress-home==0.1.0b3`.

### Features

* Sign in with Airdress, and the machine enrollment the owner approves on
  their operator.
* Exposure levels per entity, with a double opt-in for sensitive entities
  (locks, alarm panels, entry-point covers).
* Operate, observe and emit over the held channel; a device tracker for the
  owner's position; notifications into the owner's Home conversation.
* Revoked and lapsed machines handled: a lapsed approval is renewed through
  reauthentication, a revoked machine enrolls anew; the hourly re-dial stays
  available.

### Bug Fixes

* The tests run against the library the manifest pins: the generator now
  writes that pin into `requirements_test.txt` and `--check` fails when it
  drifts.
