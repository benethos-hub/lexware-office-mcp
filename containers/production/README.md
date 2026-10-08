# The server in operation

The published image from the GitHub container registry, run with
Compose. Nothing is built, and no clone of the repository is needed:
this folder is enough.

| File | What it is |
|---|---|
| `compose.yaml` | the server, and the configuration interface behind the profile `setup` |
| `.env.example` | template of `.env`: the version of the image, the ports |
| `README.md` | this |

## Get the folder

Into an empty folder, from the repository at `main`:

```sh
mkdir lexware-office-mcp && cd lexware-office-mcp
for file in compose.yaml .env.example README.md; do
  curl -fsSL -o "$file" "https://raw.githubusercontent.com/benethos-hub/lexware-office-mcp/main/containers/production/$file"
done
cp .env.example .env
```

In a clone, `containers/production/` is the same folder.

## The first start

```sh
docker compose up -d                      # the server, on 127.0.0.1:8770
docker compose --profile setup up -d      # the configuration interface
```

Open <http://127.0.0.1:8771/>, enter the API key, tick the tools. The
server notices the changed settings and restarts itself. The page shows
the bearer token the server made on its first start, which is what a
client sends. Then take the interface away again, because nothing else
will:

```sh
docker compose rm -f -s setup
```

Not `docker compose --profile setup down`: that is the whole project and
takes the server with it.

A client then connects to `http://127.0.0.1:8770/mcp` with that token.
For Claude Code:

```sh
claude mcp add --transport http lexware http://127.0.0.1:8770/mcp \
  --header "Authorization: Bearer <bearer token>"
```

## Settings

`.env` beside `compose.yaml` holds what Compose reads, and nothing of the
server's own:

| Variable | Default | What it is |
|---|---|---|
| `LXO_VERSION` | none, required | the image's tag: an exact release, or the minor line, which follows its patch releases |
| `LXO_PORT` | `8770` | the server's port on the host, on `127.0.0.1` |
| `LXO_SETUP_PORT` | `8771` | the configuration interface's port on the host, on `127.0.0.1` |

The server's settings - the API key, the token, the limits - and the
tools it offers live in the volume `config`, and the configuration
interface writes them. The transport, the bind address, the port inside
the container and the allowed hosts are pinned in `compose.yaml`
instead, as real environment variables, so the volume cannot change
them.

## Operation

```sh
docker compose ps
docker compose logs -f

# update: set LXO_VERSION in .env to the new version, then
docker compose pull && docker compose up -d
```

Docker keeps at most five log files of 10 MB per container, the oldest
dropped first.

## From the Compose file before

Until this folder, `compose.yaml` sat in the repository root and built
the image from the checkout. This one has the same project name,
`benethos-lexware-office-mcp`, and the same volumes, so the key, the
token and the tools stay. In the clone:

```sh
cd containers/production
cp .env.example .env
docker compose up -d
```

Compose replaces the container and keeps the volumes. To build from the
checkout instead, `containers/development/` does that, under a project
and with volumes of its own.
