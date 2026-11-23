# Roadmap

Section 16 of the [concept](CONCEPT.md).

## What exists today

Built, tested offline and exercised against a live test account:

- **every module in the table of [section 4](ARCHITECTURE.md)**, which is the
  list, so that this does not become a second one to keep in step
- twenty-six tools, twenty-five of them in seven groups, over **stdio**
  and, since 0.2.0, over **streamable-HTTP** or **SSE** behind a required
  bearer token. Reading:
  `get_profile`, `search_contacts`, `get_contact`, `search_articles`,
  `get_article`, `search_vouchers`, `get_voucher`, `get_payments`,
  `get_sales_document`, `get_recurring_templates`, `get_master_data`,
  `download_file`, `download_document`, `read_download` and `get_deeplink`.
  Writing:
  `create_contact`, `update_contact`, `create_article`, `update_article`,
  `create_voucher`, `update_voucher`, `create_sales_document`, `upload_file`
  and `attach_file_to_voucher`. Irreversible: `delete_article`,
  `create_sales_document` when it is asked to finalize, and `update_voucher`
  when it books an unchecked voucher. Outside the groups and the policy
  file, `server_status`, checked against the test account by
  `live/smoke.py` on 2026-10-29
- one flag per tool in a JSON file, enforced when the list is built and again
  when a call arrives, with nothing enabled until that file says so and an
  edit taking effect in both directions without a restart. Presets and the
  file it writes come from the command line, `--tools` and `--tools-file`,
  and `--env-file` names the settings the same way
- **a client told when that list changes**: `tools.listChanged` announced and
  `notifications/tools/list_changed` sent when the set of enabled tools
  differs, which Claude Desktop acts on without a restart — measured
  2026-08-22, see [section 9.2](concept/permissions.md#92-the-policy). The
  same for the downloads since 2026-10-16: `resources.listChanged` announced
  and `notifications/resources/list_changed` sent after each one, see
  [section 13](concept/errors-and-output.md#13-output-format)
- **a configuration interface in the browser**, `setup`, four pages: where the
  installation stands and which files are in effect, the API key checked before
  it is written, one checkbox per tool with what it costs the model in context,
  permission profiles and the policy file as a download, and every setting with
  where its value came from. Reworked 2026-10-08 with templates, a content
  security policy, Post/Redirect/Get and a start code. Never part of the server
  process, loopback only, see
  [section 7.1](concept/configuration-interface.md#71-the-configuration-interface)
- **a Claude Desktop extension and an entry in the MCP Registry**, since 0.5.1,
  and over stdio a prompt, *Set up Lexware Office*, that starts `setup` from
  the client, see
  [section 7.1](concept/configuration-interface.md#71-the-configuration-interface)
  and items 7 and 8 below
- **three prompts**, since 0.10.0: Open items, Missing receipts and Contact
  overview, recipes a person picks in the client that read and never write,
  offered whatever the policy file says, with both extensions leaving their
  tools and prompts to the server, see [section 8](concept/tools.md#8-tools)
- **a container image and two Compose folders**, two stages, non-root,
  180 MB on 2026-11-23, on Python 3.15.2. The server on a loopback-published
  port and the configuration interface behind a `setup` profile on the same
  volume. A bearer token made on first start rather than baked in, and a
  process that ends when its settings file changes so the new ones take
  effect.
  `containers/production/` runs the
  published image at a version named in `.env` and puts Caddy in front of
  it behind an `https` profile for clients on the local network,
  `containers/development/` builds from the checkout beside it, see
  [section 6](concept/transport.md#6-transport-and-runtime)
- one shared token bucket per process, retries decided per method and failure
  mode, upstream statuses mapped onto `ToolError` subclasses
- paging and filtering in the client, one page per call, never a walk over
  every page, and one page shape shared by every list tool
- writes that read before they replace, so an update changes only what it was
  given, and a stale `version` is refused before anything is sent
- binary downloads and multipart uploads through the same rate limiter and
  retry rules as every other call, and three ways to hand a downloaded file
  to a client: a path, an MCP resource, and the file rendered into the answer
- an upload read from a path or, since 2026-10-15 and only from the
  addresses `LXO_MCP_UPLOAD_URLS` names, fetched from a URL by a client of
  its own, see [section 7.2](concept/configuration.md#72-uploads-from-a-url)

Verified against a live account rather than assumed, and written up where it
belongs in [section 5](concept/upstream-api.md#5-upstream-api): the profile
response shape, the per-endpoint page ceiling, the 404 and 400 error bodies
including the `IssueList`-only form, the three-character minimum on the contact
filters, the voucher type and status enums, that a stale version arrives as 406
rather than 409, that a voucher PUT carries a status only to book, the upload
contract and its 5 MiB ceiling, that master data comes back as a bare list,
that a key can be created inside a test account, and that the bucket paces real
calls (five tool calls at rate 1.5 took 2.69 seconds).

The contact and voucher tools were exercised against that account end to end:
records created, read back, searched, and updated in a way that proved the
merge keeps the fields the caller did not mention. The shapes in the test
fixtures are the shapes the API actually returned, and the enum values in the
voucher schemas were measured rather than taken from the documentation, which
does not list them.

**Feature complete.** Every tool of [section 8](concept/tools.md#8-tools)
exists, every resource group of [section 4](ARCHITECTURE.md) is built, and
every documented call is covered except the event subscriptions, which
[section 2](CONCEPT.md#2-scope) rules out. The configuration question of
section 16.1 is answered too: `setup` serves the interface described in
[section 7.1](concept/configuration-interface.md#71-the-configuration-interface).
Nothing on the API side is outstanding.

**What surrounds the code**, in the order it was built:

1. ~~**A public repository.**~~ **Done 2026-08-22:**
   `github.com/benethos-hub/lexware-office-mcp`. `main` is protected and can
   only be reached through a pull request whose required checks are green,
   for the owner as well. Merges are squash or rebase, the history stays
   linear, and a merged branch deletes itself. Nothing is written to `main`
   directly any more.
2. ~~**CI.**~~ **Done 2026-08-22**, and grown since:
   `.github/workflows/ci.yml` holds ten jobs. Eight call the organisation's
   reusable workflows in `benethos-hub/.github`, which follow `main` there
   rather than a commit, since the rules are the organisation's and are meant
   to reach every repository as they change. `brand` wants `assets/brand/` to
   hold `icon.svg` and, rendered from it, a 512x512 `icon.png` and a 1280x640
   `social-preview.png`, neither committed before the last change to the SVG.
   `lint` runs `ruff check`, the format check, `mypy` and `uv lock --check`.
   `test` runs the suite across the Python matrix of
   [section 6](concept/transport.md#6-transport-and-runtime), and
   `coverage-badge` publishes the percentage the coverage run writes as
   `coverage.json` on the `badges` branch after a push to main, never for a
   pull request, so it is no required check. `lowest-versions` installs the
   oldest allowed version of every direct dependency on Python 3.11, with no
   lockfile, runs the suite and audits those versions, so a lower bound in
   `pyproject.toml` that has stopped being true shows up: its first run found
   `mcp>=2.0.0` allowing GHSA-84m7-p3x7-pcfv, and the floor went to 2.2.0.
   `audit` checks every version in `uv.lock` against PyPI and OSV. `codeql`
   and `dockerfile-lint` are described below. `ci.yml` names the tested
   Pythons, the coverage one, the oldest one and the coverage floor
   explicitly rather than relying on the workflows' defaults, so
   `tests/test_packaging.py` can hold them to the classifiers,
   `requires-python` and CLAUDE.md. Two jobs are this project's own.
   `fresh-install` builds the wheel, installs it with no lockfile involved
   and asserts that an installation without a policy file offers no tools at
   all - the rule of [section 9.2](concept/permissions.md#92-the-policy),
   which no offline test reaches because every one of them writes a policy
   file first - and runs the commands of the build spec Glama keeps on its
   own site, which writes a policy file with every tool on and asks for no
   key, and expects every tool over stdio, so a changed flag fails here
   rather than in a build nobody watches. The spec and the step change
   together. `docker` builds the image and asserts the same rule against the
   artefact people actually run: the container generates its own bearer
   token, refuses a request that does not carry it, and answers `tools/list`
   with nothing but `server_status`. It asks the same over stdio as well,
   through `docker run -i` without a network, the way a directory lists a
   server's tools, and fails on any line on stdout that is not JSON-RPC. It
   also fails the build if a plain `up` would start the configuration
   interface, which belongs behind its profile. Both architectures a release
   publishes are built, and only `linux/amd64` is started. Every job passes
   with no key, no network and no account, see
   [section 14.1](concept/testing.md#141-live-checks-are-not-a-gate).
   `.github/dependabot.yml` asks weekly about the dependency ranges, the
   pinned actions, the container base image and the Caddy image of the
   production compose file.

   **Only the newest Python of the matrix measures coverage and holds the
   floor**, decided 2026-10-10: `test / Python 3.15`, where coverage.py
   follows branches through `sys.monitoring`. The other matrix jobs run the
   suite without measuring, since under the older tracer the test step took
   up to 112 seconds on 3.12 against 42 to 46 on 3.14, and 30 to 43 without
   it. Locally coverage added 8 percent to a run on 3.14 and 1 percent on
   3.15. The job keeps its name, so the floor stays a required check once
   that name is one, and a line that only an older Python runs no longer
   counts.

   **CodeQL became a job of this repository, decided 2026-11-05.** The
   default setup of code scanning, a setting with no file, ran the security
   queries alone, and the quality queries are no setting of it. `codeql` in
   `ci.yml` calls the organisation's workflow with its default suite
   `security-and-quality`, on the Python code, the JavaScript of the
   configuration interface and the workflows, on every push and pull request.
   `.github/workflows/codeql.yml` makes the same call once a week, since
   GitHub adds queries over time and only a run on a schedule reads code
   nobody changed with them. Both file under one category, so each run
   refreshes the last. A finding goes to Security, Code scanning, and never
   fails the job, so it is no required check. GitHub refuses a workflow's
   upload while the default setup is on, so that setting went off with the
   merge, and the API has reported it as not configured since 2026-11-05.
   `tests/test_packaging.py` holds the two calls equal, the languages, the
   weekly schedule and the one permission.

   **hadolint reads the Dockerfile, decided the same day.** `dockerfile-lint`
   in `ci.yml` calls the organisation's workflow over
   `containers/**/Dockerfile`, with `docker.io` and `ghcr.io` as the registries
   a `FROM` may pull from. `docker` builds and runs the image, this job judges
   the form of the file. Its findings go to Security, Code scanning, and the
   job stays green on them: whether a new finding turns the pull request's
   "Code scanning results" check red is the repository's protection rule, one
   threshold for every scanner. It is no required check.
   `tests/test_packaging.py` holds the pattern to every Dockerfile, the
   registries to every `FROM` line and the one permission.

   **A new job is not required by itself.** The jobs that block a merge are
   listed in the branch protection, all eleven since 2026-10-19:
   `lint / lint`, `test / Python 3.11` to `test / Python 3.15`,
   `lowest-versions / Python 3.11`, `audit / Dependency audit`,
   `fresh-install`, `docker` and `brand / Brand assets`. A job added later -
   `docker` with 0.2.0, or a Python version added to the matrix - runs, may
   fail, and still lets the merge through until it is added to that list as
   well, which needs one run of it first. A job that moves into a reusable
   workflow changes its name the same way, so the list is swapped while the
   pull request that moves it waits, and the old names show as expected and
   never reported until then.
3. ~~**`config/.env.sample` inside the wheel.**~~ **Done 2026-08-22.** The
   sample moved into the package as `env.sample`, so it is installed with the
   code instead of sitting beside it, and `--settings-sample` prints it, see
   [section 16.1](#161-answered-how-a-user-configures-the-server).
4. ~~**Publication to PyPI**~~, which is what makes the installation
   instructions in the README true for someone who has not cloned the
   repository.
   `.github/workflows/publish.yml` does it from a published release over
   Trusted Publishing, so no token is stored here. It needs a pending
   publisher on PyPI first, for `publish.yml` and the environment
   `pypi-benethos-lexware-office-mcp`.
   **The release itself** is a `release/X.Y.Z` branch and pull request, then
   a tag and a GitHub release on the merged commit, which is what triggers
   the upload, step by step in [RELEASING.md](RELEASING.md). **Every job
   first checks that the tag is the version in its file**: a tag ahead of
   the version has PyPI refuse the upload, and without the check the image
   job would still push the tag's version, its minor line and `latest` with
   the old code.
   **Since 2026-10-19 every upload is an action of the organisation**,
   `publish/pypi`, `publish/ghcr`, `publish/mcpb` and
   `publish/mcp-registry` in `benethos-hub/.github`, followed at `main`
   like the CI workflows. The jobs stay in `publish.yml`, because PyPI and
   the registry trust the workflow of the job that uploads. The actions do
   the tag check against `pyproject.toml`, `manifest.json` and
   `server.json`, which replaced this project's own script, and a manual
   run gained `pypi-trial`, which builds and checks the wheel and asks PyPI
   whether it would take it, without the environment and without an OIDC
   token.
   **Since 2026-10-19 nothing is built before the CI run of the release
   commit on main has succeeded.** The first job, `ci-passed`, calls the
   organisation's `python-release-ci-passed` workflow, which looks for the
   run of `ci.yml` that the commit's push to main started, waits up to 30
   minutes while it is still going, and stops the release when it failed,
   or after five minutes when there is none, as for a commit that only ever
   lived on a pull request branch. Until then only the release procedure
   made sure the tagged commit had been tested, and a version on PyPI
   cannot be replaced. It checks that run rather than testing again,
   because the run is the full CI with every required check, and it costs
   seconds. With `audit: true` it also audits `uv.lock` once more, for a
   vulnerability that became known between the merge and the release. The
   PyPI, image and bundle jobs need it, and the registry job needs those
   three. A manual run on main goes through it as well, and on another
   branch it does not run, since nothing would be built there. Measured
   against this repository the same day, read-only: the merge commit of
   #134 passed, a commit only ever on a pull request branch stopped with
   "No CI run on main", and a wrong workflow name with GitHub's 404.
5. **Publication of the image**, so that running this server in a container
   does not require cloning the repository first. A second job of
   `publish.yml` pushes it for `linux/amd64` and `linux/arm64`, authenticated
   by the automatic `GITHUB_TOKEN`, which is why the registry is ghcr and not
   one that needs an account and a stored secret. The two jobs are
   independent: a broken image does not withhold the upload to PyPI. A manual
   run pushes the image as `edge` and tries PyPI without uploading, see
   [RELEASING.md](RELEASING.md), and only from `main`: `edge` is public, and
   the form that starts a manual run offers every branch.

   **The metadata has to sit on the index, not only on the manifests.** A
   multi-architecture image is an index pointing at one manifest per
   architecture, and the package page reads the index. Labels in the image
   configuration are then present and read by nothing, which is how a package
   page comes to say "No description provided" about an image that carries a
   description. `DOCKER_METADATA_ANNOTATIONS_LEVELS: index,manifest` puts them
   in both places, and the job then reads the published index back and fails
   if the description, the source or the version is not on it - a release is a
   poor moment to discover that setting a value and it arriving are different
   things. Since 2026-10-19 the organisation's `publish/ghcr` action does
   all of it, the annotations, the readback and the tags, and reuses the
   arm64 layers the CI build caches in the scope `buildkit`.

   **Measured on 2026-08-22 by running it**, which is the only way the
   metadata could be believed. `workflow_dispatch` pushed `edge`, the readback
   found both architectures and the description on the index, and the package
   page shows that description rather than "No description provided". The
   image was then pulled on a machine with no login and started from the pull:
   it generated its own token and refused a request without it. Contrary to
   the documented behaviour, the package did not need a visibility switch - it
   was public from the first push.

   **The image takes the package's name**, decided 2026-10-08:
   `ghcr.io/benethos-hub/benethos-lexware-office-mcp`, the name on PyPI,
   where it had carried the repository's. The publishing environment is
   named the same way, `pypi-benethos-lexware-office-mcp`, so the badge,
   the deployment and the package name one thing. The releases before it,
   0.2.0 to 0.4.1, were copied under the new name with their digests, so
   no tag means different bytes under the two names, and the old name
   received the 0.4 patch releases and stopped with 0.5.0, as the
   changelog had announced.
6. **The workflow actions are pinned to a commit**, decided 2026-09-30 after
   a review, reversing the major tags of 2026-08-23:
   `actions/checkout@3d3c42e… # v7.0.1`. A tag is a pointer its publisher
   can move, and the publish job holds the identity PyPI trusts and the
   right to push the image, so a moved tag would run somebody else's code
   with both. The comment is for the reader and for Dependabot, which raises
   the commit and the comment together. It also retires the special case of
   `astral-sh/setup-uv`, which stopped publishing major tags with its v8 and
   so alone named an exact version. `tests/test_packaging.py` refuses a
   `uses:` without a commit.

   **The images are pinned by digest as well as tag**, decided the same day:
   `python:3.15-slim@sha256:…` in both stages and
   `ghcr.io/astral-sh/uv:<release>@sha256:…`. Until then they followed their
   line, so that a security fix would arrive without anyone acting. It never
   did on its own: the image is published only by a release, so a fix in
   the base reached users with the next release either way. Now a rebuild
   gets the same bytes, and Dependabot's pull request says when the base
   moved, which is the cue for a patch release. The `# syntax=` line went
   with it, because it pulled a frontend image by a moving tag on every
   build. `tests/test_packaging.py` refuses an image without a digest and
   the line coming back.

   **uv has a stage of its own**, since 2026-10-05. Dependabot reads
   `FROM` lines only, and uv was copied with `COPY --from=` straight from
   its image, so no pull request ever came for it. Its tag names the exact
   release, so each one arrives as a new tag. `python:3.15-slim` keeps its
   line tag, so a rebuild of the base under it moves the digest only.

   What makes that bearable is that all three are watched.
   `.github/dependabot.yml` covers the declared ranges, the actions and,
   since 2026-08-23, the container base image - the one that ages silently,
   because an out-of-date base is not a build failure but unpatched system
   packages inside something people pull and run. Since the pins, minor and
   patch updates come as one pull request per ecosystem and week, and a major
   one alone. `mcp` always came alone, since the suite does not see what the
   SDK changes, and since the windows below each of the six does. Since
   2026-11-04 the uv ecosystem runs with
   `versioning-strategy: increase-if-necessary`: a range that already allows
   a new release stays as it is and only `uv.lock` moves, so an update never
   raises the floor for whoever installs the package. The option exists for
   that ecosystem alone. Since 2026-11-20 a fourth entry reads the
   production compose file, whose `caddy:2` names its major line without a
   digest on purpose: a pull brings each fix within the line to an operator
   without a release here, and Dependabot proposes the tag when a new line
   comes out. The server's own image there is named through `LXO_VERSION`,
   and the development file builds it, so neither is anything to raise.

   **Every runtime dependency sits in a patch window.** `mcp`, `httpx`,
   `pydantic`, `platformdirs`, `pypdfium2` and `jinja2` are declared as
   `~=x.y.z` at the version locked last, so `uvx`, `pip` and the
   auto-update extension below take a patch by themselves and a
   minor only once a release raised the window. Dependabot proposes each of
   the six alone, each a check of its own, and with
   `increase-if-necessary` a minor arrives as `~=` again rather than as a
   range over two. `pydantic` is declared since the windows, as the code
   imports it directly. `uvicorn` and `starlette` are imported too and stay
   undeclared, since they come with `mcp` and a window here could contradict
   its bounds. The packages beneath stay open, so a transitive release still
   reaches an installation from the index without a release here. A window
   that turns out too wide or too narrow is changed with the next release,
   which carries its own, and a security fix outside a window means a
   release at once. `tests/test_packaging.py` holds the six to the form and
   Dependabot to both settings.

   **Since 2026-11-04 a daily report sits beside Dependabot.**
   `.github/workflows/freshness.yml` calls the organisation's reusable workflow
   of the same name, which keeps the issue "Pinned versions have newer
   releases": every package `uv.lock` pins that has a newer release, within the
   ranges and beyond them, the build backend, known vulnerabilities of the
   pinned versions, the images of the Dockerfile and the compose files by
   digest and by tag, and the actions pinned by commit. Dependabot proposes the
   direct packages, the actions, the base images and a new line of the
   compose images. The report adds the packages beneath them, the versions a
   range does not allow yet, and a rebuild of a base image under the same
   tag, which is the cue for a patch release. Nothing is written to the
   repository, the upgrade of the lockfile is a dry run inside the runner,
   and the issue closes when there is nothing to report. A job that fails is
   a line in it, so a run that proved nothing never closes it. It is no
   required check, and a pull request never runs it.
   Its first run the same evening opened the issue with platformdirs 4.14.5, a
   patch within the range. **The same run asks a second question**, since the
   same evening: whether the newest versions the ranges allow still work, which
   is what `uvx` without a pin and `pip install` resolve, so what a user runs
   can change on any day without a release here. The job `newest`, the
   organisation's `python/freshness-newest` action run from this workflow,
   upgrades the lockfile inside the runner, runs the suite on those versions
   and then `tests/stdio_check.py`, the server spoken to over stdio without a
   key, see
   [section 14.3](concept/testing.md#143-the-sdk-is-the-second-blind-spot).
   The job `index` of the organisation's workflow installs the published
   release from PyPI into a fresh environment, the path `uvx` takes, and runs
   the same script with its interpreter, so a dependency that moved under a
   fixed version shows there, as platformdirs did under 0.8.1 on 2026-11-04:
   4.14.5 from the index where the release had locked 4.14.3. Both address the
   issue "Newest dependency versions break the server" and say in one sentence
   what passed, which the pins issue lists under Checks. A run that proves
   nothing, the check failing on the locked versions too or a step failing
   while nothing moved, leaves the alarm issue as it was. **The whole run
   starts once more when `publish.yml` has finished,** whatever its result and
   whether a release or the hand started it. It is there for `index`, whose
   answer changes at that moment, so a release that does not install stands in
   the alarm issue within minutes instead of at the next cron. A publishing run
   that failed leaves the index as it was, and the run after it repeats the day
   before. An index that shows a fresh version a minute late is measured once
   on the version before, and the schedule corrects that.
   `tests/test_packaging.py` holds the call: the schedule, the hand and the run
   after Publish, whose name it compares with `publish.yml`, the permission to
   write issues and nothing else, the two titles, the job's artifact and the
   check commands.
7. **An entry in the official MCP Registry**, published with 0.5.1 on
   2026-10-10. The job took it at the first attempt, and the registry
   lists the version as active and newest, with the PyPI package, the
   image and the extension, the extension's checksum the one its release
   asset has.
   `.github/publish/mcp-registry/server.json` names the PyPI package and
   the image, and a third job in `publish.yml` sends it once both are
   up, logged in with the workflow's OIDC identity, so no account and
   no secret are involved. The registry hosts nothing, it points at the
   packages and checks at that moment that each names the entry: the
   README PyPI shows carries an invisible `mcp-name:` line, and the image
   a `LABEL` in its configuration. **The name cannot be changed later**,
   so it is the package's own, in the namespace the workflow's identity
   is allowed to write, `io.github.benethos-hub/`. A pre-release gets no
   entry, since an entry cannot be taken back.

   **The image entry mounts the two named volumes** `lxo-config` and
   `lxo-downloads`, the ones the README's `setup` command for a single
   container mounts. Measured on 2026-10-10 with the command the template
   of the registry's documentation gives, `docker run -i --rm <image>`:
   the image declares `/config` as a volume, so each start got a fresh
   anonymous one, no policy file was there and no tool was offered. With
   the named volumes, what the configuration interface saved was the tool
   list of the next start, and a permission changed while the server ran
   reached it as `tools/list_changed`. A changed `.env` still needs the
   client to restart the server, because ending the process on a change
   is for the HTTP transport, where a restart policy brings it back. The
   entry also carries the hardening of the Compose files and
   `--no-healthcheck`, since the image's check knocks on the HTTP port,
   which a stdio server never opens. Both spellings a client may give a
   named argument, `--volume x` and `--volume=x`, started the server
   with the saved tools. Whether a client passes the arguments on at all
   is the client's business and is assumed.

   **No environment variables in the entry.** A client asks for each one
   at installation and puts it in its own configuration, where it is a
   real environment variable and beats the `.env` - so `setup` could
   no longer change the key or anything else asked for there. The
   README says how to configure the server, as it does for an
   installation from PyPI.

   **The icon** is `assets/brand/icon.svg`, with a PNG of 512 by 512 pixels
   rendered from it for clients that show no SVG. `assets/render_icon.py`
   renders it with a pinned resvg in a throwaway environment, so the
   renderer never enters the project's dependencies. The entry, the
   handshake and the README title link both by their address on `main`.
   Until 2026-10-13 they lived directly in `assets/`. The copies there
   stay, because 0.5.2 and earlier, their registry entries and the README
   PyPI shows for them link to those addresses.

   **The Claude Desktop bundle of item 8 is the third package**, by its
   address as an asset of the release, which is the one form the registry
   takes for it: `/owner/repo/releases/download/<tag>/<file>`, with "mcp" in
   it, so the file with the version in its name rather than the one without.
   The registry wants its SHA-256, which exists only once the release has
   built the bundle, so the committed entry holds zeros and the job, which
   waits for the bundle as well, downloads the file the release carries and
   writes its hash in before publishing. **The registry takes an entry
   whole or not at all**, so a refusal that outlasts the retries falls back
   to the entry without the bundle, the newest of its packages: the version
   is listed at least with PyPI and the image, and the job still fails, so
   the refusal is looked at. Since 2026-10-19 both are done by the
   organisation's `publish/mcp-registry` action, which also pins
   `mcp-publisher` by version and checksum, in place of this project's
   `fill_bundle_checksum.py` and its own pin.

   `tests/test_packaging.py` holds the entry against the package: the
   versions, the description, the package names, the namespace, both
   ownership proofs, the volumes, the icons, the placeholder, and the job
   that waits for all three packages.
8. **A Claude Desktop extension**, attached to every release since 0.5.1
   of 2026-10-10, whose job built and attached it at its first run.
   `.github/publish/mcpb/` holds the
   manifest as it ships, the `server.py` uv starts by its path and the
   `build.py` that stages the bundle from the files git tracks. It is a
   `uv` bundle: it carries `pyproject.toml`, `uv.lock` and the source, and
   Claude Desktop installs Python and the dependencies itself, from the
   lockfile because the manifest says `--frozen`. A job in `publish.yml`
   stages it with `build.py` through `uv run`, and the organisation's
   `publish/mcpb` action checks its version against the tag, validates and
   packs it, holds the packed file to the staged tree byte for byte, and
   attaches it to the release twice, under its version and under a name
   without one for a link that always reaches the newest release. The
   comparison matters because the registry entry vouches for the bundle by
   its hash. Until 2026-10-19 this project packed with an mcpb CLI pinned
   in the workflow, whose dependencies npx resolved afresh at every
   release, and compared with its own `check_packed.py`. The action locks
   the packer and everything beneath it in a `package-lock.json`.

   **Tried before anything was built**, in a Windows Sandbox with Claude
   Desktop from the Store and no uv or Python on the machine. Claude Desktop
   brought its own uv 0.9.7, which fetched Python 3.14.0 and installed from a
   lockfile uv 0.13 had written. The server read the per-user directory,
   `AppData\Local\benethos-lexware-office-mcp`, the same as an installation
   from PyPI, since the Store app's container does not redirect it. What it
   could not do was let anyone start `setup` from outside, see
   [section 7.1](concept/configuration-interface.md#71-the-configuration-interface),
   which is what the prompt there is for. With the prompt, the whole way ran in
   the sandbox: install, pick the prompt, set the key and the tools in the
   browser, and `get_profile` answered for the test account.

   **The manifest asks for two files and no key.** Its `user_config` could
   carry the key into the install dialog, and a first try did, but a value
   there reaches the server as an environment variable, which beats the `.env`
   and so could no longer be changed on the configuration pages. One place for
   everything won. Since 2026-11-05 it asks for two optional files, `env_file`
   and `tools_file`, type `file`, passed as
   `--env-file=${user_config.env_file}` and
   `--tools-file=${user_config.tools_file}`, each with an empty default. A path
   is not a setting and names the file the setup pages write into, so one place
   for everything stays. The `=` form and the empty default are there for a
   Claude Desktop defect: an args element that is exactly a `${user_config.…}`
   placeholder is left as it is when the field is empty, with or without a
   default, because the reference substitution substitutes only a truthy value,
   while a placeholder inside a longer string is replaced whenever the field
   exists (issue #250 of modelcontextprotocol/mcpb, open since 2026-05-28).
   Measured on Windows with Desktop 4.16336: both empty arrives as
   `--env-file=` and `--tools-file=`, which the server already reads as not
   given, a file set on the extension's page arrives as `--env-file=<path>` and
   Save restarts the server at once. Claude Desktop keeps the tool list it
   holds across that restart: measured on 2026-11-05 on the bundle below, the
   server read all 25 tools at once and the open session went on offering
   `server_status` alone until Claude Desktop itself was restarted. **It lists
   every tool**, since the dialog shows what the extension can offer, and its
   long description says that none but `server_status` is on until the person
   chooses. Before that tool, Claude Desktop showed a server that offered no
   tool as failed, "Offered no tools to Cowork and Code sessions", and listed
   the prompt all the same. A server offering `server_status` alone is shown as
   running, measured the same day. **Every prompt is declared with its exact
   text**, for the installation dialog to show, and since 0.10.0 both manifests
   set `tools_generated` and `prompts_generated`, so Desktop checks neither
   list, see [section 8](concept/tools.md#8-tools). Without the flags it
   refuses an undeclared prompt and drops an answer that differs from the
   declaration.

   **A second bundle updates itself.** `build.py --auto-update` stages
   `benethos-lexware-office-mcp-auto-update`, which carries no code, only the
   manifest, the icon and the license, and the same job attaches it through
   the same action. Claude Desktop runs `uv tool run
   benethos-lexware-office-mcp` with the same two file arguments, the newest
   release on PyPI with whatever dependency versions that release allows. Its
   manifest is made from the pinned one, with its own name, since Claude
   Desktop keys an extension by it and the two stand side by side, its own
   display name, description and server. The registry entry lists the pinned
   bundle alone. The patch windows described above decide what it runs, and
   the packages beneath them stay open. An extension keeps the manifest it
   was installed with while the server moves on. One installed from 0.9.1 or
   earlier has no flags and declares the setup prompt alone, which makes
   **the setup prompt's name and text permanent**: a new word would be
   dropped as a possible injection on every such extension, with no new file
   to reach them through. `tests/test_mcpb.py` holds both to their literal
   value.

   A release can change what an enabled tool does under its name, which the
   policy file cannot see, since it names a tool and not its abilities. The
   README says so, and nothing here stops it.

   Measured on 2026-11-05 on Windows with uv 0.13.6, no key, 0.8.2 from PyPI,
   uv's cache and tool directories of their own: both fields empty arrives as
   `--env-file= --tools-file=` and starts, in 4.8 seconds cold and 1.1 warm,
   and over stdio with two scratch files the server offers `server_status`
   and the prompt. `setup`, started with the interpreter of that server as
   the prompt starts it, answers on its port. The interpreter lives in uv's
   cache, under `archive-v0`. PyPI's simple index says `max-age=600`. **An
   installed tool wins:** with 0.8.1 from `uv tool install`, `uv tool run`
   ran 0.8.1 and `uv tool run <package>@latest` ran 0.8.2. Measured on
   2026-11-03 in a Windows Sandbox on another package of the same form:
   Claude Desktop brought uv 0.9.7, uv a Python 3.14, restarts at 3 minutes
   and at 9 minutes 49 seconds after the last check ran the old release and
   the one at 12 minutes the new one, and offline the command ran from the
   cache within those 10 minutes and failed after them with `Failed to
   fetch`. Smart App Control blocked the downloaded `uv.exe` there, for either
   kind of bundle.

   Measured on 2026-11-05 on this bundle in Claude Desktop, in a Windows
   Sandbox with Smart App Control turned off, against a confirmed test
   account: Claude Desktop's uv 0.9.7 fetched Python 3.14.0 and 37 packages
   and ran 0.8.2, with `server_status` alone while both fields were empty.
   Claude Desktop accepted the prompt's answer as matching the declaration,
   `setup` started from uv's cache and wrote into the `.env` the field named.
   With both files set, `get_profile` answered. Saving the read-only preset
   there told the client at once with no restart, and `create_article` was
   refused after no API call. `UV_EXCLUDE_NEWER` in the user's environment
   did not reach uv, `exclude-newer` in uv's `uv.toml` did: 0.8.1 at the next
   restart of Claude Desktop, and 0.8.2 at the one after the file was gone.
   **(to verify)** for this one: a real release arriving through PyPI, whether
   Claude Desktop's own uv finds a tool from `uv tool install` the same way,
   Smart App Control on this bundle, and a Python newer than the wheels of the
   native dependencies, which `requires-python` does not hold back.

   macOS is not measured, in particular whether Claude Desktop there keeps
   an extension from the per-user directory `setup` writes **(to verify)**.
   The mcpb CLI is locked in the organisation's `publish/mcpb` action, where
   Dependabot keeps it current. `tests/test_mcpb.py` holds the manifests to
   the package: the version, the metadata, every tool with the first
   sentence of its description, every prompt as the server answers it, the
   two file fields and no other, neither sensitive nor required, and no bare
   placeholder in the arguments, a staged bundle that holds the tracked
   source and nothing else, and an auto-update bundle that holds no project.
   The tools and prompts are written by `build.py --sync-manifest`, the two
   generated flags by hand, and a test holds them in place.

**The table records releases.** 0.1.0 carried everything built before the
first release, writing, the policy and the configuration interface among it,
and the tool groups of [section 8](concept/tools.md#8-tools) are named for
what they are, reading, writing and irreversible, not for an order of
arrival.

| Release | Content | State |
|---|---|---|
| 0.1.0 | stdio transport, all twenty-five tools of [section 8](concept/tools.md#8-tools), the per-tool policy of [section 9](concept/permissions.md#9-permission-model), the configuration interface of [section 7.1](concept/configuration-interface.md#71-the-configuration-interface), the client with its rate limiting, retries, error mapping, paging, downloads and uploads, and the offline suite | **released 2026-08-22** — every part of it is built and exercised against a live account |
| 0.2.0 | HTTP transport with its own bearer authentication, Docker image and Compose file | **released 2026-08-22** — `transport.py`, `Dockerfile` and `compose.yaml`, guarded by the `docker` job in CI, which is one of the checks a merge needs. The release publishes the image to ghcr beside the package on PyPI, and a client has reached the live account through the pulled image over HTTP |
| 0.2.1 | The published image on Python 3.14 | **released 2026-08-23** — no change to the package itself. The tags a user pulls, `latest` and the minor line, follow the release tag, so the base image moves only when a version number is spent on it |
| 0.2.2 | `--env-file` reads the file it names and no other | **released 2026-08-23** — the flag had promised that in its own help since it was added and read the named file after everything the search found, so it isolated nothing. See [section 6](concept/transport.md#6-transport-and-runtime). The search behind it follows one rule now as well, which is a decision rather than the fix |
| 0.2.3 | Error messages reach the model again under MCP SDK 2.1 | **released 2026-09-02** — the SDK began sorting a failing tool call by the type of what was raised, and this hierarchy derived from plain `Exception`, so every sentence it sends was replaced by "Error executing tool <name>". It reached installations rather than only this checkout: the declared range already allowed 2.1. See [section 12.1](concept/errors-and-output.md#121-why-toolerror-derives-from-the-sdks). The lockfile was brought current in the same release, and Dependabot had been silent since it was configured because it read `pip` rather than `uv` |
| 0.2.4 | The image on MCP SDK 2.2 and a current HTTP stack | **released 2026-09-14** — no change to the package itself. Anyone installing from the index already resolved to SDK 2.2.0, the container did not, because it is built from the lockfile. Over stdio nothing a client sees moved, measured byte for byte. Over HTTP an idle session now expires after thirty minutes, the SDK's new default and kept, see the changelog. The seven transitive packages Dependabot never proposes came along, three of them in the transport |
| 0.3.0 | A review's hardening, the payload fixes it found, and what the API documentation said all along | **released 2026-09-27** - a minor rather than a patch, because an installation can trip over it: only JSON `true` enables a tool, the base URLs must be `https://`, `LXO_MCP_PDF_PAGES` stops at 100, and the configuration interface answers only to a loopback name and its own port. New: `search_vouchers` by number and on four sort properties, `update_voucher` books an unchecked voucher and moves one back to the collective contact, `LXO_MCP_UPLOAD_DIR`. Verified live against the second test account: `live/smoke.py` 13 of 13, and a shape capture that differs from 0.2.4's only where the account holds different records |
| 0.4.0 | The download directory as a cache, a logging concept, the package layers, and a review's findings | **released 2026-09-30** - a minor, because an installation can trip over it: the download directory is cut down to its newest 100 files on the first start, a key or bearer token with a character no header can carry stops the start, `create_contact` and `update_contact` refuse a field the contact's kind has no place for, and every log line has a new time format and short sources. Workflow actions pinned to a commit and the images by digest. Verified live against the second test account: `live/smoke.py` 13 of 13, and a shape capture that differs from 0.3.0's only where the account holds different records |
| 0.4.1 | The image on current dependencies | **released 2026-10-05** - no change to the package itself. Python 3.14.8, cryptography 50.0.2 with OpenSSL 4.0.3, MCP SDK 2.3.0 and pypdfium2 5.14.0 with PDFium 156, built with uv 0.12.23 from a stage of its own, so Dependabot sees it. Verified live against the second test account: `live/smoke.py` 13 of 13, and a shape capture identical to 0.4.0's |
| 0.4.2 | The container files in `containers/`, and a restart on a changed `.env` that loses nothing | **released 2026-10-08** - `containers/production/` runs the published image at the version its `.env` names, `containers/development/` builds from the checkout beside it, both hardened. The image is published under the package's name as well, and under the old one through the 0.4 line. A save in the first seconds after a start reaches the server, and an open stream holds a shutdown back for five seconds at most |
| 0.5.0 | The configuration interface rebuilt, HTTPS for the local network, and two reviews' findings | **released 2026-10-08** - a minor, because an installation can trip over it: the image is published under the package's name alone, and `setup` listens on 8771, asks for a start code and has no `/export` any more. `setup` has four pages in a frame of its own, `containers/production/` puts Caddy in front of the server for clients on the local network, and the image is built on pydantic 2.14 and a rebuilt Python 3.14.8 base. Verified live against the second test account: `live/smoke.py` 13 of 13, and a shape capture identical to 0.4.1's |
| 0.5.1 | The Claude Desktop extension, the MCP Registry entry, setup from the client, and `search_vouchers` filtering what it says it does | **released 2026-10-10** - a patch, because no installation trips over it: everything new is added beside what was there, and the two flags `search_vouchers` loses never filtered anything (#95). A tool now refuses an argument it does not take, which the SDK used to drop. The extension brings its own uv and Python, `setup` opens from a prompt the person picks in the client, and a key saved into a server that had none is used at once, all measured in a fresh Windows Sandbox. Python 3.15 joins the tested versions. Verified live against the second test account: `live/smoke.py` 13 of 13, and a shape capture identical to 0.5.0's |
| 0.5.2 | What a client receives, and the image on current dependencies | **released 2026-10-12** - a patch, because no installation trips over it. The twenty-two record tools publish no output schema, which shortens the tool list by 1,773 characters while their answers stay byte-identical, the handshake carries the description, website and icons of the registry entry, and a listed download carries its size. The image moves to platformdirs 4.13.0 and pydantic 2.14.1. The README that PyPI shows catches up with the extension's six steps and the redrawn diagram. Verified live against the second test account: `live/smoke.py` 13 of 13, and a shape capture identical to 0.5.1's |
| 0.5.3 | The image on Python 3.15 | **released 2026-10-14** - no change to what a client receives but the address of the icons, which moved to `assets/brand/` while the old one keeps working. The image is built on `python:3.15-slim` with uv 0.13.1 and starlette 1.8.0, and was checked inside before the release: Python 3.15.0, every compiled dependency, a page rendered by pypdfium2, stdio, and HTTP with and without the token. Verified live against the second test account: `live/smoke.py` 13 of 13, and a shape capture identical to 0.5.2's |
| 0.5.4 | The review of 2026-10-15 | **released 2026-10-15** - a patch, because an installation that runs as before sees nothing new: the tool list and every answer over stdio are byte for byte those of 0.5.3. What changed shows in edge cases - a redirect, a withheld tool called with bad arguments, a resource above 5 MiB, a settings file that is not UTF-8, a mistake in the policy file named once - plus `LXO_MCP_SETUP_PROMPT` to withhold the setup prompt and a browser code that works once. Verified live against the second test account: `live/smoke.py` 13 of 13, and a shape capture identical to 0.5.3's |
| 0.6.0 | Uploads from a URL, a client told about downloads, and the review of 2026-10-16 | **released 2026-10-16** - a minor, because an installation can trip over it: the two upload tools take `source` instead of `path`, and a client that passes `path` by name is refused until it lists the tools again. New: `upload_file` and `attach_file_to_voucher` fetch a file from a URL `LXO_MCP_UPLOAD_URLS` allows, so a mailbox server's link to an attachment reaches Lexware from server to server, see [section 7.2](concept/configuration.md#72-uploads-from-a-url), and a client is told when a download was added. The tool list notification reaches clients again, one of the 2026-07-28 protocol on its listen stream. Verified live against the second test account: `live/smoke.py` 13 of 13, a shape capture identical to 0.5.4's, and the mailbox flow end to end from Claude Desktop with 17 receipts |
| 0.6.1 | The image on current dependencies, and the lowest `mcp` raised to 2.2.0 | **released 2026-10-19** - a patch, because nothing a client receives changed: the tool list and every answer are those of 0.6.0. The lockfile the image is built from carries starlette 1.9.0, httpx2 and httpcore2 2.14.0, certifi 2026.10.18 and platformdirs 4.13.5, on the current build of `python:3.15-slim`, and `mcp>=2.2.0` keeps an environment that pins an older SDK from serving Streamable HTTP with sessions that are never reclaimed (GHSA-84m7-p3x7-pcfv). The first release through the organisation's publishing actions, behind the gate that waits for main's CI. Verified live read-only against the test account: `live/smoke.py` 13 of 13, and a shape capture identical to 0.6.0's apart from its timestamp |
| 0.6.2 | The image on Python 3.15.1 | **released 2026-10-22** - a patch, because nothing a client receives changed: the tool list and every answer are those of 0.6.1. The image is built on the current `python:3.15-slim` with Python 3.15.1, the security release, and its `ca-certificates` 20250419+deb13u1, with uv 0.13.5 and a lockfile that carries certifi 2026.10.19 and httpx2 and httpcore2 2.16.0. Old and new image were compared before the merge: the packages differ only there, and an HTTP session answers the same, the bearer check and a TLS connection to Lexware included. Verified live read-only against the test account: `live/smoke.py` 13 of 13, and a shape capture identical to 0.6.1's apart from its timestamp |
| 0.7.0 | The review of 2026-10-28, and the image on Python 3.15.2 | **released 2026-10-28** - a minor, because an installation can trip over it: `upload_file` and `attach_file_to_voucher` refuse a network path unless `LXO_MCP_UPLOAD_DIR` names the same share, since Windows connects to the host on the first look at such a path, and a settings file that is there but cannot be read stops the start instead of being read as empty. The rest of the review's findings show in edge cases, the tool list is byte for byte that of 0.6.2. The image runs Python 3.15.2, the expedited security release, built with uv 0.13.6, and its `/config/.env` is readable by its owner alone. Verified live read-only against the third test account: `live/smoke.py` 13 of 13 on the reviewed code, and a shape capture that differs from 0.6.2's only where the account holds different records |
| 0.8.0 | `server_status`, the one tool outside the policy file | **released 2026-10-29** - a minor, because an installation can trip over it: a server without a policy file now lists `server_status` where it listed no tool at all, and anything that checked for an empty list, as this project's own CI did, sees one. The tool says which server is running and, with `details`, whether Lexware answers and takes the key, from one request a minute at most, and whether the policy file is loaded. Every other tool and answer is that of 0.7.0, and what the configuration interface says the tools cost includes the new one. platformdirs 4.14.0 in the image's lockfile. Verified live read-only against the third test account: `live/smoke.py` 14 of 14 with the status step, and a shape capture identical to 0.7.0's |
| 0.8.1 | The image on a refreshed lockfile | **released 2026-11-03** - a patch, because nothing a client receives changed: the tool list and every answer are those of 0.8.0. The image is built with uv 0.13.7 from a lockfile that carries pydantic 2.14.2, whose two security fixes a scanner reading the image would ask for though neither is reachable here, and anyio 4.16.0 under the SDK's transports. The stdio probe of [section 14.3](concept/testing.md#143-the-sdk-is-the-second-blind-spot) answered byte for byte as before on both protocol versions. Verified live read-only against the third test account: `live/smoke.py` 14 of 14, and a shape capture identical to 0.8.0's |
| 0.8.2 | The image on a refreshed lockfile and a rebuilt base | **released 2026-11-05** - a patch, because nothing a client receives changed: the tool list and every answer are those of 0.8.1, measured over stdio on both protocol versions. The image carries pydantic 2.14.3, apt 3.0.4 and tzdata 2026f, its health check runs without a shell, and it names its user by id, 10001, the same user as before. The capture of the read-only live run against the third test account is identical to 0.8.1's but for its date |
| 0.9.0 | The extension's own files, a second extension that updates itself, and a patch window on every runtime dependency | **released 2026-11-07** - a minor, because an installation can trip over it: `mcp`, `httpx`, `pydantic`, `platformdirs`, `pypdfium2` and `jinja2` are declared as `~=x.y.z`, so a `pip install` into an environment that needs another minor of one of them no longer resolves. Nothing in the source changed, so the tool list and every answer are those of 0.8.2. pypdfium2 5.15.0 brings PDFium 159 with fixes for several CVEs, and a rendered page comes out byte for byte as before. Both extensions were tried in Claude Desktop on Windows in a Windows Sandbox against the third test account, `live/smoke.py` passed 14 of 14 before and after the refresh, and the capture of the read-only live run is identical to 0.8.2's but for its date |
| 0.9.1 | Two tool descriptions that say how to use the tool, and pypdfium2 5.15.1 in the lockfile | **released 2026-11-09** - a patch, because nothing an installation trips over changed: the tool names, their parameters and every answer are those of 0.9.0. The descriptions of `server_status` and `get_article` name what to do with the answer and which tool to use instead, 329 characters more on every request. The image and the pinned extension carry pypdfium2 5.15.1, and a rendered page comes out byte for byte as before. Verified live read-only against the third test account: `live/smoke.py` 14 of 14, and a shape capture identical to 0.9.0's but for its date |
| 0.10.0 | Three prompts, and both extensions leave their tools and prompts to the server | **released 2026-11-11** - a minor, because an installation can trip over it: an extension that updates itself, installed from 0.9.1 or earlier, lists the three prompts and refuses to attach them until it is installed again. The tool names, their parameters and every answer are those of 0.9.1. Open items, Missing receipts and Contact overview are recipes a person picks in the client, they read and never write, and both manifests set `tools_generated` and `prompts_generated`, so Claude Desktop checks neither list. The image and the pinned extension carry pypdfium2 5.15.2. Verified live read-only against the third test account: `live/smoke.py` 14 of 14, a shape capture identical to 0.9.1's but for its date, and the three prompts run in Claude Desktop 5.1231.2 through the pinned extension |
| 0.10.1 | The image and the pinned extension on a refreshed lockfile, and the SDK's HTTP client held at `WARNING` by name | **released 2026-11-17** - a patch, because nothing a client receives changed: the tool list and every answer are those of 0.10.0. The image is built with uv 0.13.8 from a lockfile that carries httpx2 and httpcore2 2.16.2, the SDK's HTTP client, and python-multipart 0.0.34, neither on the path of a request to Lexware. The log holds httpx2 and httpcore2 at `WARNING` by name beside httpx and httpcore. Verified live read-only against the third test account: `live/smoke.py` 14 of 14, and a shape capture identical to 0.10.0's but for its date |
| 0.10.2 | The image and the pinned extension on uv 0.13.9 and platformdirs 4.14.7 | **released 2026-11-18** - a patch, because nothing a client receives changed: the tool list and every answer are those of 0.10.1. The image is built with uv 0.13.9, which installs the same files as 0.13.8, and the lockfile carries platformdirs 4.14.7, with which the configuration and cache directories resolve to the same paths. Verified live read-only against the third test account: `live/smoke.py` 14 of 14, and a shape capture identical to 0.10.1's but for its date |
| 0.10.3 | The design documents in `docs/`, and pydantic 2.14.4 | **released 2026-11-19** - a patch, because nothing a client receives changed: the tool list and every answer are those of 0.10.2, byte for byte with every tool on. The specification moved from one file into `docs/`, split by topic with every section keeping its number, and the README links there. The lockfile carries pydantic 2.14.4 with pydantic-core 2.50.5. Verified live read-only against the third test account: `live/smoke.py` 14 of 14, and a shape capture identical to 0.10.2's but for its date |
| 0.10.4 | The image and the pinned extension on platformdirs 4.14.8 | **released 2026-11-20** - a patch, because nothing a client receives changed: the tool list and every answer are those of 0.10.3, and no file of the package moved. The lockfile carries platformdirs 4.14.8, with which the configuration and cache directories resolve to the same paths as with 4.14.7, on Windows and in the image. Verified live read-only against the third test account: `live/smoke.py` 14 of 14, and a shape capture identical to 0.10.3's but for its date |
| 0.10.5 | The image and the pinned extension on certifi 2026.11.20 | **released 2026-11-21** - a patch: the tool list is that of 0.10.4, and no file of the package moved. The lockfile carries certifi 2026.11.20, whose bundle drops five root certificates and adds none, none of them on the chain to Lexware's API. Verified live read-only against the third test account: `live/smoke.py` 14 of 14, and a shape capture identical to 0.10.4's but for its date |
| 0.10.6 | One answer per SSE request, and sse-starlette 3.7.1 | **released 2026-11-23** - a patch: the tool list is that of 0.10.5. Over `--transport sse`, stopping the server no longer leaves a traceback for each open stream (python-sdk issue 883, worked around in `transport/http.py`), and the lockfile carries sse-starlette 3.7.1, which ends an open event stream cleanly at shutdown. Verified live read-only against the third test account: `live/smoke.py` 14 of 14, and a shape capture identical to 0.10.5's but for its date |

## 16.1 Answered: how a user configures the server

**Settled on 2026-08-21 by building the interface**, the third of the four
directions below. It is specified in
[section 7.1](concept/configuration-interface.md#71-the-configuration-interface).
The problem it was opened for is recorded here as it stood, because the
reasoning is what the interface is answerable to.

**What was wrong**

- A user installing from PyPI gets **no sample**. The wheel packs the package
  directory only, and `config/.env.sample` sat beside it, so the ten settings
  existed only in the README. Verified by building the wheel: 38 files as of
  2026-08-22, none of them the sample. **Fixed the same day** by moving the
  sample into the package.
- There is **no way to create the file**. The only location that works for an
  installed package is the per-user config directory, and neither the
  directory nor the file is created by anything. A user would have to make
  both by hand from a path they have to look up first.
- **Nothing says which file is in effect.** Five sources are merged, and a
  setting that appears not to work gives no hint whether it was overridden, or
  read from a file the user has forgotten about.
- The failure a user met first was therefore a server that starts, lists its
  tools, and answers every one of them with "no API key".

**The four directions, and what became of them**

- **Ship the sample in the wheel** and name its target path in the error
  message. **Done**, though not by shipping a file beside the package: it
  moved *into* the package, which is the only place an installer copies from.
  `--settings-sample` prints it, so no path from the server's machine has to
  be named to hand it over.
- **A command that writes the file**, creating the directory and refusing to
  overwrite an existing one. **Superseded.** The interface writes it, and
  writes it by merging rather than by overwriting, which is what the
  objection to the original version was about.
- **A small local configuration interface.** **Chosen and built.** See
  [section 7.1](concept/configuration-interface.md#71-the-configuration-interface).
  It grew two things beyond the sketch: the context cost of each tool, and
  permission profiles with an export that carries them to another machine.
- **A read-only diagnostic** as a smaller version of the same idea. **Built
  as the overview page** rather than as a separate command: every candidate
  file, whether it exists, which value won and where it came from, without
  ever printing the key.

**Constraints that held, and were kept.** The key never enters a versioned
file and never appears in output — the interface neither displays it back nor
puts it in an export. A real environment variable still outranks every file,
and the page marks a setting it would be pointless to type over. The
interface works for an installed package and for a clone, and names the file
it is acting on rather than leaving it to be inferred.

## The open questions, answered

Numbering is stable, so cross-references elsewhere keep pointing at the right
item. Answered questions stay in place with their answer.

1. ~~Exact maximum page size per endpoint.~~ **Answered 2026-08-20:** it is
   per endpoint, not one number. `voucherlist` caps at 250, `contacts`
   accepts 500 and refuses 1000. This project caps at 250 as the lowest
   ceiling measured. **Extended 2026-08-21:** there are floors as well.
   `/v1/articles` refuses anything below 25 with `size: MIN`, which no other
   list does. See [section 5](concept/upstream-api.md#5-upstream-api).
2. ~~Whether the API offers an idempotency key for POST.~~ **Answered
   2026-08-21: it does not.** Measured by posting the same credit note twice
   under one key, three times over with `Idempotency-Key`, `X-Idempotency-Key`
   and `Idempotency-Id`. Every pair produced **two** documents with different
   ids and a 201 each — an unknown header is ignored here exactly as an unknown
   query parameter is. The rule in
   [section 10.2](concept/client.md#102-retry-safety) that a failed POST
   is never retried therefore rests on a measurement rather than on caution,
   and there is no way to make one safe to repeat.
3. ~~File upload limits: maximum size, accepted MIME types, and whether
   `type=voucher` is the only accepted form value.~~ **Answered 2026-08-20:** 5
   MiB inclusive, PDF, JPEG, PNG and XML, and yes — `voucher` is the only
   accepted value. See [section 5](concept/upstream-api.md#5-upstream-api).
4. ~~The correct app base URL for deeplinks per account region.~~ **Answered
   2026-08-21:** `https://app.lexware.de` serves the permalinks, and
   `https://app.lexoffice.de` answers every one of them with a 301 to it, so
   the old host keeps working and neither is region-specific as far as can be
   seen from here. It stays configurable. The permalink shapes were measured
   the same day, see [section 5](concept/upstream-api.md#5-upstream-api).
5. ~~Whether any endpoint returns a partner or OAuth-only field that a plain
   API key cannot reach.~~ **Closed 2026-08-21.** The question assumed a
   second way in - a partner integration authorized by OAuth2, of the kind
   many vendors run beside an account key, which can see fields a plain key
   cannot. The documentation describes exactly one way in: the account
   owner's private key from `app.lexware.de/addons/public-api`, sent as a
   bearer token. No OAuth2 flow, no partner access, no scopes, no endpoint or
   field level restrictions appear anywhere in it. Nothing read against a live
   account has hinted at a truncated view either: every record carried what
   the web app shows for it. An **undocumented** partner programme cannot be
   ruled out from here, but it would be a question for Lexware rather than a
   measurement, and it would be moot for this server, which serves one account
   deliberately and is not a customer-facing integration.
6. ~~The upstream token bucket capacity, which is not documented.~~ **Answered
   2026-08-21: it is 4.** Measured after a 15 second idle stretch, which at the
   documented 2 per second would have accumulated 30 tokens if the bucket were
   deep. Five requests fired at once: four went through in 1.33 seconds, the
   fifth was refused. Four fired at once went through cleanly. So the capacity
   is small and fixed, not a function of how long the key has been quiet.
   `LXO_MCP_BURST` stays at `2` anyway — see
   [section 10.1](concept/client.md#101-rate-limiting) for why the
   measurement does not simply become the default.
7. ~~Whether 429 responses carry a `Retry-After` header, and whether the block
   duration grows with repeated offences as the wording about permanent
   blocking suggests.~~ **Closed unanswered on 2026-08-22, by decision.**
   Answering it means provoking 429s against a production account on purpose,
   and the second half cannot be answered by anything but repeated offences -
   the behaviour the documentation says leads to a permanent block. This
   project does not probe its provider for limits it was asked not to test. The
   retry rules of [section 10.1](concept/client.md#101-rate-limiting) assume no
   `Retry-After` and back off with jitter, which is the right behaviour whether
   or not the header is there, so nothing is waiting on the answer.
8. ~~Whether an API key can be generated inside a 30-day test account.~~
   **Answered 2026-08-20:** yes, and it works against the production endpoints.
   See [section 11.1](concept/data-and-secrets.md#111-test-environment).

**Nothing is left that a test account could answer.** Questions 2 and 6 were
measured on 2026-08-21 and 5 was closed against the documentation the same
day. Question 7 is closed by decision rather than by measurement, see above.
The one 429 that did occur while measuring question 6 came back without a
`Retry-After` worth reading, and that remains the only observation there is.
