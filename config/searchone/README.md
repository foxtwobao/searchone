# SearchOne control plane

This overlay adds Tavily, Exa, Metaso, MiniMax TokenPlan, Zhihu, and a curated
Chinese tender search channel plus a lightweight control plane without changing
the upstream `searx/settings.yml` file.

1. Create `config/searchone/.env` from `.env.example` and add any existing
   provider credentials.
2. Start the service with `./manage-searchone run`.
3. Open `/admin` on the same host and port as the search UI.

The first start creates `runtime-secrets.env` with the local encryption key,
session secret, and administrator credentials. Provider credentials are copied
from `.env` into encrypted SQLite storage when they are not already managed by
the console.

JSON searches require a client key created in the administration console:

```sh
curl -H 'Authorization: Bearer sone_...' \
  'http://127.0.0.1:8888/search?q=OpenAI&format=json'
```

The versioned endpoint `/api/v1/search` accepts the same query parameters and
also supports JSON POST bodies.

Provider credentials and proxy pool changes take effect immediately. Enabled
proxies are applied at runtime to all matching SearXNG outbound networks; a
proxy with no channel selection applies to every engine.

The `tender` channel reuses the managed `TAVILY_API_KEY`. It expands product and
procurement terms and restricts results to the bundled public-procurement source
catalog. Authorize `tender` separately on client API keys that need this channel.

## Docker Compose

The container image includes this overlay and starts
`searchone_control.app:app` on port `8888`. From the repository root:

```sh
cd container
cp .env.example .env
mkdir -p core-config
docker compose up -d
docker compose logs searchone
```

The `searchone-data` volume stores `searchone.db` and `runtime-secrets.env`.
Keep this volume when upgrading or recreating the container. The
`core-config` bind mount stores the generated SearXNG settings file.

The first container start prints the generated administrator username and
password once. Provider keys can be supplied through `container/.env` or added
later in the administration console.
