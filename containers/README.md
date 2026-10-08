# Containers

The image, and the places it runs in, each in a folder of its own.

```
containers/
  images/
    lexware-office-mcp/
      Dockerfile          # the image, built with the repository root as context
  production/             # in operation, the published image:
    compose.yaml          #   the server, the configuration interface behind
                          #   the profile setup
    .env.example          #   template of .env: the version, the ports
    README.md             #   how to get the folder, set it up and update it
  development/            # for development, built from this checkout
    compose.yaml          #   the same two services, a project, ports and
                          #   volumes of their own
```

| Folder | For | Image | Ports on 127.0.0.1 | Compose project |
|---|---|---|---|---|
| `production/` | running the server, without a clone of the repository | from the GitHub container registry, the version named in `.env` | 8770, 8771 | `benethos-lexware-office-mcp` |
| `development/` | trying a change in a container | built from this checkout | 8780, 8781 | `benethos-lexware-office-mcp-dev` |

The two run side by side. Each has its own volumes, so a trial in
`development/` never reaches the key, the token or the tools of the
installation in `production/`.

## For development

From `development/`:

```sh
docker compose up -d --build             # build and start the server, on 127.0.0.1:8780
docker compose --profile setup up -d     # the configuration interface, on 127.0.0.1:8781
docker compose rm -f -s setup            # take the interface away again
docker compose down -v                   # stop, and forget the volumes
```

The server makes its bearer token on the first start, as the published
image does, and the configuration interface shows it. `LXO_PORT` and
`LXO_SETUP_PORT` move the two ports, from the environment or from an
`.env` beside the file, which is not versioned.

## The image

`ghcr.io/benethos-hub/benethos-lexware-office-mcp`, for `linux/amd64` and
`linux/arm64`, built by `.github/workflows/publish.yml` with the same
version as the package on PyPI:

| Event | Tags |
|---|---|
| release `v1.2.3` | `1.2.3`, `1.2`, `latest` |
| pre-release `v1.3.0-rc.1` | `1.3.0-rc.1` only: neither the minor line nor `latest`, which a pull without a tag gets |
| started by hand from `main` (Actions, Publish, Run workflow) | `edge` |

Built from the repository root:

```sh
docker build -f containers/images/lexware-office-mcp/Dockerfile -t benethos-lexware-office-mcp:local .
```

- It holds the package installed from `uv.lock`, without the development
  tools, and runs as user `appuser` (uid 10001).
- Its settings live in the volume `/config`, documents fetched from the
  API in `/downloads`. The configuration interface writes the first one.
- Its health check connects to the transport port.
- Both Compose files run it with a read-only root file system, `/tmp`
  in memory, no Linux capabilities and `no-new-privileges`. It writes
  nothing but its two volumes and `/tmp`.
- Both Compose files cap the log Docker keeps of each container at five
  files of 10 MB, the oldest dropped first.

`ci.yml` builds the image on every pull request and every push to
`main`, for arm64 as well. It checks that both Compose files are valid,
keep every port on the loopback address and start the configuration
interface only with its profile, and it starts the image once: it makes
its own token, refuses a request without it, and offers no tools while
no policy file names one.
