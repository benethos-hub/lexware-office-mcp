# Releasing

A patch release is cheap here and has been used for an image that had merely
fallen behind, so the list is short on purpose. In this order:

1. **`uv lock --upgrade --dry-run`.** Dependabot proposes direct dependencies
   only. Everything transitive moves when a direct bump happens to drag it
   along, and otherwise never - and the container image is built from the
   lockfile, so it is the one installation that inherits that silence. An
   install from the index resolves the newest allowed versions on its own.
   The issue "Pinned versions have newer releases", which `freshness.yml`
   keeps daily, lists the same, transitive packages included. If the dry run
   lists anything, refresh on its own branch first, with the suite and a look
   at the notes of whatever sits in the transport or under the SDK. A new
   minor of one of the six packages in a `~=` window is not in the dry run at
   all, the issue lists it as outside the bounds: raise the window in
   `pyproject.toml` on that branch, after its notes, and `uv lock` follows. A
   security fix does not wait for this step: the bot's security updates cover
   transitive packages too. **The base images as well**: the digest each
   `FROM` line pins against the one its tag points to now. A rebuild under
   the same tag moves the digest only, and Dependabot asks about it once a
   week. If one moved, raise it on the same branch as a lockfile refresh, and
   compare the packages of the old and the new image before the merge.
2. **Live checks while an account exists.** `live/smoke.py` and
   `live/api_shape.py`, and the capture stays as this release's marker.
3. **The version, in every place that quotes it.** `pyproject.toml`, the
   README's status line, pin example and exact image tag, `LXO_VERSION` in
   `containers/production/.env.example`, the status line of
   `docs/CONCEPT.md`, the `server_status` example in
   `docs/concept/tools.md`, a row in `docs/ROADMAP.md`, the example start
   line in `docs/LOGGING.md`, the MCP Registry entry in
   `.github/publish/mcp-registry/server.json` (its own version, the PyPI
   package's, the image tag and the bundle's download address), the bundle's
   manifest in `.github/publish/mcpb/manifest.json`, and the changelog
   section with its link reference. Then `uv lock`, which carries the
   package's own version. The guards in `tests/test_packaging.py` catch a
   missed one in any of these places, and `uv lock --check` one in the
   lockfile. **The minor line** (`:0.10` in the README, and in the comment of
   `.env.example`) changes only with a minor release - the image tag itself
   follows the release tag when the image is built.
4. **A trial run, only when asked for.** It is there to test the publishing
   machinery after a change to it, such as the move onto the
   organisation's actions, and is never started on its own. When it is
   asked for, start `publish.yml` by hand on main before tagging:
   `pypi-trial` builds and checks the wheel and asks PyPI whether it would
   take it, and the image goes out as `edge`, which has to be deleted by
   hand afterwards. A warning that the version is on PyPI already is
   expected before step 3 is merged. The pins of `mcp-publisher` and of the
   mcpb packer live in the organisation's actions, not here.
5. **Branch, PR, merge**, then `gh release create vX.Y.Z --target main`,
   which fires `publish.yml`. Its first job, `ci-passed` (the
   organisation's `python-release-ci-passed` workflow), waits for the CI
   run the merge commit's push to main started and lets nothing be built
   unless that run succeeded, so a tag on a commit that never reached main,
   or on one whose CI is red, publishes nothing. That is the run as a whole,
   so `codeql` or `dockerfile-lint` gone red stops a release as well, though
   a merge does not wait for either. `ci-passed` also audits `uv.lock` once
   more, and a waiver in `ignore-vulns` belongs there as well as in
   `ci.yml`. Each action after it stops when the tag is not `v` plus the
   version in its file, `pyproject.toml`, `manifest.json` or
   `server.json`, so a tag ahead of step 3 publishes nothing rather than an
   image with the old code.
6. **Verify the delivered artefacts, not the build.** The PyPI simple index
   with a cache-busting query - the JSON API lags for minutes after an upload
   and has reported a finished release as missing. The ghcr index manifest
   for the exact tag, the minor line and `latest`, all three on the same
   revision. Then install the wheel into a scratch environment and pull the
   image, and check inside each that the change the release is for is there.
   The release carries both bundles, each twice, under its version and
   without one. Last the registry entry, under
   `https://registry.modelcontextprotocol.io/v0/servers?search=benethos-lexware-office-mcp`,
   at this version, with this image tag and with the bundle's checksum in
   place of the zeros the committed file holds.
