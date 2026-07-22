SearchOne
=========

SearchOne is a search gateway based on SearXNG.  It keeps the SearXNG search
experience while adding an administration console, client API keys, provider
credentials, a shared proxy pool, and additional search providers.

The project currently integrates Tavily, Exa, Metaso, and Zhihu.  Search,
administration, and API access share the same HTTP service and port.

Features
========

- SearXNG metasearch with HTML and JSON output.
- Versioned ``/api/v1/search`` endpoint for upstream agents.
- Client API keys with channel, rate, result-count, and timeout limits.
- Encrypted provider credential storage.
- Shared HTTP, HTTPS, SOCKS4, and SOCKS5 proxy pool with hot updates.
- Paste/file proxy import and concurrent health testing.
- Lightweight administration console at ``/admin``.

Docker Compose
==============

The recommended deployment uses the published
``docker.io/foxtwobao/searchone:latest`` image::

   cd container
   cp .env.example .env
   mkdir -p core-config
   docker compose up -d

The image is built entirely from this repository on top of the official
``python:3.14-slim-bookworm`` base image.  It does not inherit from or require
the SearXNG container images.

Open ``http://127.0.0.1:8888`` for search and
``http://127.0.0.1:8888/admin`` for administration.  The first start generates
the administrator password and persistent encryption keys.  Read the generated
credentials from the initial container log::

   docker compose logs searchone

The following data survives container replacement:

- ``./core-config``: SearXNG settings.
- ``searchone-data``: SearchOne SQLite database and runtime secrets.
- ``core-data``: SearXNG cache data.
- ``valkey-data``: Valkey data.

To update the deployment::

   docker compose pull
   docker compose up -d

Configuration
=============

Edit ``container/.env`` before starting the stack.  Provider credentials are
optional because they can be entered later in ``/admin/providers``.

Important variables include:

- ``SEARCHONE_HOST`` and ``SEARCHONE_PORT``: published host address and port.
- ``SEARCHONE_VERSION``: Docker image tag, normally ``latest``.
- ``SEARCHONE_ADMIN_USERNAME`` and ``SEARCHONE_ADMIN_PASSWORD``: optional
  first-start administrator override.
- ``TAVILY_API_KEY``, ``EXA_API_KEY``, ``METASO_API_KEY``, and
  ``TIKHUB_TOKEN``: optional provider credentials.

Runtime secrets supplied on the first start are stored in the
``searchone-data`` volume.  Later environment changes do not replace the stored
secrets automatically.

Local Development
=================

For a source checkout::

   cp config/searchone/.env.example config/searchone/.env
   ./manage-searchone run

The local service listens on port ``8888`` by default.

API Example
===========

Create a client key in the administration console, then call::

   curl -H 'Authorization: Bearer sone_...' \
     'http://127.0.0.1:8888/api/v1/search?q=OpenAI&format=json'

Container Publishing
====================

``.github/workflows/searchone-container.yml`` builds and smoke-tests the image
after changes to ``main`` or ``master``.  Successful builds are pushed to
Docker Hub as:

- ``foxtwobao/searchone:latest``
- ``foxtwobao/searchone:sha-<12 character commit>``

The workflow accepts ``DOCKERHUB_USERNAME`` / ``DOCKERHUB_TOKEN`` and remains
compatible with the existing ``DOCKER_USER`` / ``DOCKER_TOKEN`` secret names.

Upstream Synchronization
========================

SearchOne tracks SearXNG upstream, but its container and control-plane files
must not be overwritten during routine upstream synchronization.  See
``UPSTREAM_SYNC.md`` for the human-readable merge policy and ``AGENTS.md`` for
the repository instructions automatically consumed by coding agents.

Upstream and License
====================

SearchOne is derived from `SearXNG <https://github.com/searxng/searxng>`_.  The
project remains licensed under the GNU Affero General Public License
(AGPL-3.0-or-later).  See ``LICENSE`` for details.
