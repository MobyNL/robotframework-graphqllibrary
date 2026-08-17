# Handoff — robotframework-graphql

State as of 2026-08-13. Everything described here runs green locally. The repository is
`git init`-ed but has **no commits yet**; nothing has been pushed, and no GitHub repository
or PyPI project exists.

## What this is, and why it exists

A Robot Framework library for testing GraphQL APIs, modelled on
`/home/moby/git/robotframework-mongodblibrary` (use that one; `robotframework-mongodblibrary-1`
is a stale clone).

The case for it, from the research that preceded the build:

- **Nothing comparable exists.** No `robotframework-graphql*` package on PyPI. A GitHub
  search for `graphql robotframework` returns two repositories: one abandoned single-commit
  repo (last push 2021-03-02) and one personal Shopify suite. Greenfield, but with no proven
  demand either — that is the main risk in this project.
- **Current practice has a correctness bug.** Per the
  [GraphQL over HTTP spec](https://github.com/graphql/graphql-over-http/blob/main/spec/GraphQLOverHTTP.md),
  a server answering `application/json` returns **HTTP 200 even when the operation failed**.
  Every forum and blog example of GraphQL-over-RequestsLibrary asserts `Status Should Be 200`
  and therefore passes on requests that returned nothing. None of them check the `errors`
  array. Making that check the default is the library's reason to exist.
- **Robot Framework's syntax fights GraphQL.** Runs of spaces inside a cell get collapsed, so
  multi-line queries break. The workaround everyone lands on — a `.json` file holding the
  query as one escaped line — is neither readable nor reviewable. Documented on the RF forum
  since 2020 ([#316](https://forum.robotframework.org/t/graphql-support/316),
  [#3787](https://forum.robotframework.org/t/can-not-send-api-using-graphql/3787)), never
  solved.

**Contributing this to `robotframework-requests` was considered and rejected**: its stable
release is 0.9.7 (2024-04), the 1.0 line has been alpha since 2024 with its last alpha in
2024-11, and landing this there would push `gql`/`graphql-core` onto every plain-HTTP user.
Interop is handled instead by accepting a caller-supplied `requests.Session`.

## Layout

```
GraphQLLibrary/
├── __init__.py          GraphQLLibrary(DynamicCore); the class docstring is the user manual
├── _types.py            conditional Secret typing + reveal()
├── errors.py            GraphQLResponseError
├── response.py          build_response / resolve_path / describe_errors / normalise_errors
├── session_pool.py      SessionManager + GraphQLSession
└── keywords/
    ├── connection.py    ConnectionKeywords  — sessions, aliases, headers
    ├── query.py         QueryKeywords       — execute, load, validate, check-with-retry
    ├── response.py      ResponseKeywords    — getters and assertions
    └── schema.py        SchemaKeywords      — introspection: operations and deprecations
utest/                   125 pytest tests, 98% coverage
atest/                   42 Robot tests, .graphql query files, and server/graphql_server.py
.github/workflows/       ci.yml (4 jobs), release.yml (trusted publishing on v* tags)
run_atest.sh             starts the server, runs the suites, stops it again
```

28 keywords. Three names differ deliberately, following the MongoDB library: PyPI
`robotframework-graphql`, import name `GraphQLLibrary`, repository
`robotframework-graphqllibrary`.

## How to run it

```
poetry install                     # installs the project itself, which the suites need
poetry run pytest utest --cov
./run_atest.sh
poetry run ruff check . && poetry run mypy && poetry run robocop check atest
poetry run libdoc GraphQLLibrary GraphQLLibraryKeywords.html
```

Current results: ruff/robocop/mypy clean, 106 unit tests passing at 99% coverage, 34
acceptance tests passing, libdoc generating.

The decisive end-to-end check lives in `atest/error_tests.robot`: the server answers HTTP 200
with a non-empty `errors` array, `Execute Query` fails on it, and the same call with
`expect_errors=True` returns the response so the error's `path` and `extensions.code` can be
asserted.

## Decisions worth knowing before changing anything

**Dependency choice.** `gql[requests]` (4.x, MIT, actively maintained) plus `graphql-core`
directly. `sgqlc` was rejected — its model is to generate a typed Python module per schema,
which is the wrong shape for a library whose job is to accept a query string.
`python-graphql-client` (last release 2021, hard-pins aiohttp) and `qlient` (dead since 2022)
are both abandoned. Transports are gql extras, so nothing pulls in aiohttp or websockets.

**gql reconnects on every `Client.execute`.** That would discard the connection pool and any
cookie per request, and it rejects an already-connected transport outright. Sessions therefore
call `connect_sync()` once at creation, and `GraphQLSession.execute` runs on the persistent
`client.session`. Do not "simplify" this back to `client.execute`.

**gql raises `TransportQueryError` as soon as a response carries errors**, which is exactly
the case this library must be able to hand back intact. `QueryKeywords._execute` catches it
and rebuilds the response from the exception's `data`, `errors` and `extensions`. Nothing is
lost, and no private gql API is touched.

**The caller-supplied `requests.Session` cannot be set before connect** —
`RequestsHTTPTransport.connect` raises `TransportAlreadyConnected` when it finds one. It is
swapped in after connect, and detached before close on teardown so the caller's session stays
open. Covered by a unit test and an acceptance test; verify both if this area is touched.

**`validate_queries=False` does not skip parsing.** gql parses every document it sends. The
flag governs only this library's own checks: the syntax error with line and column, operation
selection by name, and the refusal to send a mutation through `Execute Query`. The libdoc and
the changelog say so; keep them honest if the behaviour changes.

**Queries are normalised on the wire.** gql reprints the parsed document, so the server sees
the standard layout rather than the text a suite wrote. Tests assert against the normalised
form (`NORMALISED` in `utest/test_query_keywords.py`).

**Retrying belongs to `Check Query Result`, not to the response assertions.** Retrying an
assertion against an already-fetched response would loop over an object that cannot change.
`Check Query Result` re-sends the query on each attempt and treats server errors and
not-yet-present fields as retryable. This deviates from the original plan, which had put
retry on the assertion keywords.

**The acceptance server is stdlib plus graphql-core**, not strawberry/FastAPI/uvicorn.
graphql-core is already a dependency, so the server costs no new ones. It deliberately
exposes a field that fails outright (`boom`), a field that fails while its siblings resolve
(`user.avatar`, the partial-data case), a field with an `extensions.code` (`restricted`), a
deprecated field, and a field that answers wrongly twice before succeeding (`eventually`,
for the retrying keyword). `POST /reset` puts it back to its starting state — the suites call
it, which is what keeps a rerun against a still-running server behaving like the first run.

**Robocop is configured to ignore the rules that push suites onto RF 7 `VAR` syntax.** The
suites have to stay runnable on 6.1.1, the declared floor.

## Scope: what was deliberately left out

Subscriptions, file uploads (the multipart request spec), request batching and persisted
queries/APQ. These are named in the library docstring under "Beyond These Keywords", and
`Execute Raw Request` is the escape hatch.

Schema introspection was on this list and is now implemented, in `keywords/schema.py`. Two
details there are deliberate and easy to break. Introspection omits deprecated fields unless
the query asks with `fields(includeDeprecated: true)`, so dropping that argument would make
`Get Deprecated Fields` answer with an empty list forever rather than fail. And only object
and interface `fields` are requested: `inputFields(includeDeprecated:)` and
`enumValues(includeDeprecated:)` are later spec additions that older servers reject outright,
which would turn every keyword in the module into an error against them. Deprecated input
fields and enum values are therefore not reported, and the docstring says so. They are the natural 1.x work once there is evidence anyone wants this. gql already
supports uploads, batching and every WebSocket sub-protocol, so adding them is mostly keyword
surface rather than protocol work.

## Next steps

1. Decide whether this ships at all. It works, but nothing has been published and no user has
   asked for it. That is the honest state.
2. First commit and a GitHub repository under `MobyNl`. Conventional commits, matching the
   MongoDB library.
3. Publish keyword documentation via GitHub Pages: `GraphQLLibraryKeywords.html` and
   `index.html` are committed, and `.nojekyll` is present because Jekyll would otherwise eat
   libdoc's `{{ }}` sequences.
4. Set up PyPI trusted publishing for the `pypi` environment, then tag `v0.1.0`.
   `release.yml` checks the tag against `poetry version --short` before building.
5. Try it against a real API before 1.0 — a public one such as countries.trevorblades.com,
   and ideally one real project's endpoint. Transport and header behaviour against a real
   server is the part local tests cannot prove.

## Files a newcomer should read first

- `GraphQLLibrary/__init__.py` — the class docstring is the whole user manual.
- `GraphQLLibrary/keywords/query.py` — `_execute` and `_resolve_query` hold the two ideas the
  library is built on.
- `atest/error_tests.robot` — what the library is for, stated as tests.
