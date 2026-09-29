<p align="center">
  <a href="https://airdress.co">
    <img src="https://raw.githubusercontent.com/airdress-co/airdress-home-assistant/main/docs/assets/airdress-banner.png" alt="Airdress" width="640">
  </a>
</p>

<h1 align="center">Airdress for Home Assistant</h1>

<p align="center">
  <strong>Your home, reachable from your airdress. No port forwarding, no VPN.</strong>
</p>

<p align="center">
  <a href="https://hacs.xyz/docs/faq/custom_repositories/"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS custom repository"></a>
  <a href="https://github.com/airdress-co/airdress-home-assistant/releases"><img src="https://img.shields.io/github/v/release/airdress-co/airdress-home-assistant?include_prereleases&amp;label=release" alt="Latest release"></a>
  <a href="https://github.com/airdress-co/airdress-home-assistant/actions/workflows/ci.yml"><img src="https://github.com/airdress-co/airdress-home-assistant/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/airdress-co/airdress-home-assistant" alt="License: Apache 2.0"></a>
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=airdress-co&amp;repository=airdress-home-assistant&amp;category=integration"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant instance and open this repository in HACS"></a>
</p>

Link your [Home Assistant](https://www.home-assistant.io/) to your own
[airdress](https://airdress.co). Functions running on your airdress can then
press the buttons you exposed and read the state you exposed, and Home
Assistant gets events from Airdress and a way to message you in your Airdress
chat.

## Why

Your home automation already knows when the door opened and can turn the
heating up. What it usually cannot do is take part in anything outside the
house without opening a port on your router or running a VPN.

Home Assistant dials out to your airdress and holds that connection open, so
nothing on your router changes and nothing listens for the internet.
What your airdress can reach is exactly what you chose in Home Assistant,
entity by entity, and nothing else.

## Features

- **Operate.** Your airdress's functions run the actions of the entities you
  share for operation: turn on a light, press a button, set a thermostat. Each
  action is checked in Home Assistant before it runs, whatever your airdress
  allowed, and appears in the logbook naming the function that ran it.
- **Observe.** Functions read the state of the entities you share, and can
  follow their changes as they happen.
- **Events.** Your airdress declares events; each becomes an event entity in
  Home Assistant that your automations can trigger on.
- **Messages to you.** A notify entity, *Home conversation*, delivers messages
  from your automations to the Home conversation in the Airdress app on your
  phones.
- **Your location, if you send it.** A device tracker follows your position
  when a function on your airdress reports it, with your consent.
- **Outbound only.** Home Assistant holds a WebSocket open to your airdress,
  and falls back to HTTP long-polling on networks that refuse WebSockets. It
  remembers per network which one worked.
- **English and German.**

## Screenshots

<!--
  Screenshots come later. Do not add mockups or edited images here: each
  slot is a real capture from a running Home Assistant, saved under
  docs/assets/screenshots/ and linked by its raw.githubusercontent.com URL,
  so that HACS renders it too. Wanted, in this order:
    1. config-flow-sign-in.png   Add integration -> Airdress -> "Sign in with Airdress"
    2. approve.png               the approval step, with its confirmation code
    3. exposure-options.png      the options: entities to operate and to observe
    4. entities.png              the integration's entities (event, notify, tracker)
    5. home-conversation.png     a message from Home Assistant in the Airdress app
-->

Screenshots are on their way. The shots planned:

| | |
|---|---|
| Sign in with Airdress | *coming soon* |
| Approving the link on your airdress | *coming soon* |
| Choosing what to expose | *coming soon* |
| The integration's entities | *coming soon* |
| The Home conversation in the Airdress app | *coming soon* |

## What you need

- **An airdress.** Airdress is invite-only today; without one there is nothing
  to link to. [Join the waitlist at airdress.co](https://airdress.co).
- **Home Assistant 2026.9.0 or newer.**
- [HACS](https://hacs.xyz/).

## Install

Use the button above, or:

1. In HACS, open the menu, choose **Custom repositories**, and add
   `https://github.com/airdress-co/airdress-home-assistant` with the type
   **Integration**.
2. Find **Airdress** in HACS and download it. Releases are pre-releases while
   this is a beta: switch on **Show beta versions** for the repository if HACS
   offers none.
3. Restart Home Assistant.

## Set it up

1. **Settings → Devices & services → Add integration → Airdress.**
2. Choose **Sign in with Airdress**. Open airdress.co, sign in, confirm the
   code Home Assistant shows, and pick your airdress.
3. **Approve** the link on your airdress. Check that it shows the same
   confirmation code as Home Assistant before you approve. Home Assistant
   continues by itself once you have.

You can also link by entering your airdress's address, or with a pre-auth key
you created on your airdress, which skips approving by hand.

## What it exposes

**Nothing by default.** In the integration's options you choose, entity by
entity:

- **Operate:** your functions can run the entity's actions and read its state.
- **Observe:** your functions can read its state, nothing more.

Locks, alarm panels, and garage door, door, gate, window and unclassified
covers are **sensitive**. Sharing one for operation is not enough: you allow
each one again in a separate step, and your airdress has to allow it too.
Anything not allowed on both sides is refused.

Actions run as a dedicated *Airdress* user in Home Assistant, which is not an
administrator. Airdress's own entities are never shared back.

## Privacy

- **What leaves Home Assistant:** the state of the entities you share, when a
  function reads it or follows it, and the result of each action it runs. For
  followed entities, only the attributes your airdress asked for. Messages you
  send through the notify entity go to your airdress.
- **Where it goes:** to your airdress only. Home Assistant contacts airdress.co
  only while you link it with **Sign in with Airdress**.
- **Your location is not recorded by default.** When a function sends your
  position, Home Assistant's history keeps only *home*, *away* or the zone,
  never your coordinates. Keeping coordinates is a separate option behind a
  confirmation, and you can exclude the tracker from the recorder entirely.
- **The link's key** is stored in Home Assistant's configuration, so it is in
  your backups. Remove the integration, or revoke the machine on your
  airdress, to end the link.

## Beta

This is a beta. The integration is written for Home Assistant itself and is
planned to ship as a core integration; this repository carries the same code
until a Home Assistant release includes it. That is also why it is a HACS
custom repository and not in the HACS default store.

Report problems on the [issue tracker](https://github.com/airdress-co/airdress-home-assistant/issues).

## Remove it

**Settings → Devices & services → Airdress → Delete**, then remove it in HACS.
To end the link on your airdress's side as well, revoke the machine there.

## Links

- [airdress.co](https://airdress.co)
- [Support](https://airdress.co/support)
- [Issues](https://github.com/airdress-co/airdress-home-assistant/issues)
- The protocol lives in the [`airdress-home`](https://github.com/airdress-co/airdress-home)
  library.

## Development

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
It also writes the `airdress-home` line of `requirements_test.txt` from
`overlay/mirror.json`, so the tests run against the library the manifest pins.
CI runs `scripts/generate.py --check` and fails when the generated trees
differ from what `upstream/` and `overlay/` produce, so a hand edit cannot be
merged.

The code is held to Home Assistant core's own bar, and CI enforces it:

- **ruff** with core's rule set (`pyproject.toml`, `tests/ruff.toml`), check
  and format;
- **mypy `--strict`** over `custom_components/airdress`, against the Home
  Assistant release the tests run on;
- **100% test coverage** of `custom_components/airdress`.

```sh
uv venv --python 3.14 && uv pip install -r requirements_test.txt
prek install                                     # ruff, mypy, generated files, commit messages
prek run --all-files
.venv/bin/python -m pytest --cov                 # fails under 100%
```

To update the mirror from a core checkout:

```sh
scripts/export_upstream.py --core ../ha-core   # refuses uncommitted changes there
scripts/generate.py
# commit upstream/, overlay/ and the generated trees together
```

### Commits and releases

Commit messages and PR titles are
[conventional commits](https://www.conventionalcommits.org/en/v1.0.0/)
(`fix: …`, `feat: …`, `docs: …`, `feat!: …` for a breaking change). The
commit-msg hook checks each commit, and CI checks a PR's title and commits.
PRs are merged by rebase (merge commits are off): the PR's own commits are
the history release-please reads, so each one should say what it changes.

Releases are made by [release-please](https://github.com/googleapis/release-please),
never by hand:

1. Every push to `main` updates one open release PR, `chore(main): release
   <version>`. It sets `version` in `overlay/mirror.json` and
   `.release-please-manifest.json` and adds the `CHANGELOG.md` entry; a
   second commit on it, `chore: regenerate for <version>`, runs
   `scripts/generate.py` so the manifest carries the new version and the
   generated-files check passes. A `fix:` or `feat:` commit makes a release
   PR; `docs:`, `chore:`, `ci:` and the like do not on their own.
2. Merging that PR tags `vX.Y.Z-bN` and creates a draft GitHub release.
3. The tag starts `release.yml`, which refuses a tag that is not the
   manifest's version and a library pin that is not on PyPI, and then
   publishes the draft as a pre-release, which HACS offers to users who
   opted in to betas.

**The library pin is not part of this.** `library` in `overlay/mirror.json`
names the `airdress-home` release the integration installs, and it moves only
in its own PR, e.g. `fix: require airdress-home 0.1.0b4`, once that release
is on PyPI and the tests pass against it.

Until 0.1.0 every version is a beta: `fix:`, `feat:` and even a breaking
change all move `0.1.0-b3` to `0.1.0-b4`. release-please spells it with a
hyphen; Home Assistant and HACS read it as the same version as `0.1.0b4`. To
leave the betas, put `Release-As: 0.1.0` in the body of a commit on `main`,
and remove `versioning`, `prerelease` and `prerelease-type` from
`release-please-config.json`.

## License

Apache License 2.0; see [LICENSE](LICENSE). `tests/logbook_common.py` is
copied from Home Assistant core, also under the Apache License 2.0.
