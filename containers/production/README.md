# The server in operation

The published image from the GitHub container registry, run with
Compose. Nothing is built, and no clone of the repository is needed:
this folder is enough.

| File | What it is |
|---|---|
| `compose.yaml` | the server, the configuration interface behind the profile `setup`, and Caddy behind the profile `https` |
| `.env.example` | template of `.env`: the version of the image, the ports, HTTPS |
| `Caddyfile` | HTTPS for clients on the local network |
| `README.md` | this |

## Get the folder

Into an empty folder, from the repository at `main`:

```sh
mkdir lexware-office-mcp && cd lexware-office-mcp
for file in compose.yaml .env.example Caddyfile README.md; do
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

Open the address `docker compose logs setup` prints, start code included,
enter the API key, tick the tools. The server notices the changed
settings and restarts itself. The page shows the bearer token the server
made on its first start, which is what a client sends. Then take the
interface away again, because nothing else will: *Beenden* in its sidebar
ends it and leaves the stopped container behind, and this removes it:

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
| `COMPOSE_PROFILES` | empty | `https` starts Caddy with a plain `up` |
| `LXO_DOMAIN` | none, required with `https` | the name clients use, e.g. `lexware.lan` |
| `LXO_TLS` | `internal` | where the certificate comes from: `internal`, `files` or `acme` |
| `LXO_HTTPS_PORT` | `443` | Caddy's port on the host, on every address |

The server's settings - the API key, the token, the limits - and the
tools it offers live in the volume `config`, and the configuration
interface writes them. The transport, the bind address, the port inside
the container and the allowed hosts are pinned in `compose.yaml`
instead, as real environment variables, so the volume cannot change
them.

## HTTPS for the local network

For a client on another machine, Caddy goes in front of the server, on
port 443 of every address of this host. Set in `.env`:

```sh
COMPOSE_PROFILES=https
LXO_DOMAIN=lexware.lan
```

and make the name resolve to this host on the clients, through the local
DNS or a line in their hosts file. Then `docker compose up -d`.

Caddy passes `/mcp` on and nothing else: the configuration interface
stays on the loopback, every other path is a 404, and a request without
an `Authorization` header gets its 401 from Caddy before it reaches the
server. The server still checks the token itself.

**The certificate comes from Caddy's own CA**, `LXO_TLS=internal`, so each
client trusts that CA's root once. It is in the volume `caddy-data` and
stays across restarts:

```sh
docker compose exec caddy cat /data/caddy/pki/authorities/local/root.crt > lexware-root.crt
```

Then on each client, with the file copied over:

```sh
certutil -addstore -f Root lexware-root.crt                       # Windows, as administrator
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain lexware-root.crt          # macOS
sudo cp lexware-root.crt /usr/local/share/ca-certificates/ \
  && sudo update-ca-certificates                                  # Debian, Ubuntu
```

A client built on Node.js, Claude Code among them, does not read the
system's store but `NODE_EXTRA_CA_CERTS`, set to the path of that file in
the environment the client starts in. Then:

```sh
claude mcp add --transport http lexware https://lexware.lan/mcp \
  --header "Authorization: Bearer <bearer token>"
```

`LXO_TLS=files` takes a certificate of your own instead, a company CA's
for instance, as `secrets/tls/cert.pem` with its chain and
`secrets/tls/key.pem` in this folder. `acme` asks a public CA and needs
this host reachable from the internet, **which this server is not built
for**: one bearer token is all it knows of who is asking, and behind it
are tools that write to real books.

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
