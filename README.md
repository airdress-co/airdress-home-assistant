# Airdress for Home Assistant

Link your [Home Assistant](https://www.home-assistant.io/) to your
[airdress](https://airdress.co), so that functions running on your airdress can
operate and observe exactly the entities you chose to share, and nothing else.

> **Beta, installed through HACS as a custom repository.** The integration is
> written for Home Assistant itself, and this repository carries it until a Home
> Assistant release ships it. It is not in the HACS default store.

## What you need

- **An airdress.** Airdress is invite-only today; without one there is nothing
  to link to.
- **Home Assistant 2026.9.0 or newer.**
- [HACS](https://hacs.xyz/).

## Install

1. In HACS, open the menu, choose **Custom repositories**, and add
   `https://github.com/airdress-co/airdress-home-assistant` with the type
   **Integration**.
2. Find **Airdress** in HACS and download it. Releases are pre-releases while
   this is a beta: switch on **Show beta versions** for the repository if HACS
   offers none.
3. Restart Home Assistant.
4. **Settings → Devices & services → Add integration → Airdress**, then
   **Sign in with Airdress** and follow the steps. You approve the link on your
   own airdress; nothing is shared until you choose entities in the
   integration's options.

## What it shares

Nothing by default. In the integration's options you choose which entities
your airdress may **operate** and which it may only **observe**. Locks, alarm
panels, and garage, door, gate, window and unclassified covers are refused
unless you opt each one in separately, and your airdress has to allow it as
well. Every action taken from your airdress appears in the logbook, naming the
function that took it.

## Remove it

**Settings → Devices & services → Airdress → Delete**, then remove it in HACS.
To end the link on your airdress's side as well, revoke the machine there.

## How this repository is made

Nothing in `custom_components/airdress/` or `tests/airdress/` is edited here.
They are generated:

```text
upstream/   a verbatim snapshot of the integration and its tests from a
            home-assistant/core branch; upstream/SOURCE names the commit
overlay/    what only this repository adds: the version and pinned library
            (mirror.json), the German translation, the brand images
scripts/export_upstream.py   refreshes upstream/ from a core checkout
scripts/generate.py          builds the generated trees from the two
```

`scripts/generate.py` documents every difference from the core integration.
CI runs `scripts/generate.py --check` and fails when the generated trees
differ from what `upstream/` and `overlay/` produce, so a hand edit cannot be
merged.

To update the mirror from a core checkout:

```sh
scripts/export_upstream.py --core ../ha-core   # refuses uncommitted changes there
scripts/generate.py
# commit upstream/, overlay/ and the generated trees together
```

To release, set `version` (and `library`, if the library moved) in
`overlay/mirror.json`, regenerate, merge, and push the tag `v<version>`. The
release workflow refuses a tag that is not the manifest's version, and a
library pin that is not on PyPI.

The protocol lives in the [`airdress-home`](https://github.com/airdress-co/airdress-home)
library, not here.

## License

Apache License 2.0; see [LICENSE](LICENSE). `tests/logbook_common.py` is
copied from Home Assistant core, also under the Apache License 2.0.
