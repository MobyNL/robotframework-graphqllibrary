# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- The keyword documentation is now generated on publish and served per version, at
  `/<version>/GraphQLLibraryKeywords.html`, with `/latest` and `/dev` alongside them and a
  landing page listing everything. Reading the documentation for the version you have installed
  no longer means reading the documentation for whatever is newest. The rendered page is no
  longer committed to the repository: it records its own generation time, the path of the
  machine that produced it and the Robot Framework and Python versions used, none of which
  belongs in version control and all of which made a committed copy impossible to verify.

## [0.2.0] - 2026-08-17

### Added

- Queries are checked against the endpoint's own schema before they are sent, so a misspelled
  field, an argument that does not exist or a selection missing its subfields is reported with
  its line and column instead of being sent and rejected. Validation against a schema is part of
  the GraphQL specification rather than an extra, and graphql-core already implements all of it;
  this release simply uses it. On by default, `validate_against_schema=False` on import turns it
  off, and `validate_queries=False` turns it off along with the other local checks.

  A server that will not describe itself is not treated as a failure. Introspection is commonly
  disabled outside development, and it is sometimes behind authentication, so the first query on
  a session — often the login itself — cannot read the schema. The check is then skipped with a
  warning and tried once more after an operation succeeds, which is what makes a
  login-then-query suite work without any extra wiring. It is never retried indefinitely.

- `Query Should Be Valid Against Schema` checks a query without sending it, and *fails* when the
  schema cannot be read, since there a schema is what was asked for. `Validate Query` is
  unchanged and remains a syntax-only check that contacts nothing — its documentation now says so
  plainly, because the name invited the stronger reading.

- `Save Schema Snapshot`, `Get Schema Breaking Changes`, `Get Schema Dangerous Changes` and
  `Schema Should Have No Breaking Changes` compare a live endpoint against a committed snapshot.
  Snapshots are SDL rather than introspection JSON, because a snapshot is only worth committing if
  the diff is readable. Breaking and dangerous changes are reported apart: a removed field breaks
  a query outright, while a value added to an enum only breaks a suite that switches on it.

- `Refresh Graphql Schema` drops the schema held for a session, for a deployment that changes it
  mid-suite.

### Changed

- The schema is now introspected once per endpoint and held, where every schema keyword used to
  introspect on each call. A real schema runs to hundreds of kilobytes — 595 KB for the endpoint
  this was measured against — so caching is what makes any of this affordable. Sessions sharing
  connection parameters share the schema, as they already share the client.

- The schema keywords read graphql-core's own full introspection query rather than a hand-written
  one. The minimal query the 0.1.0 keywords used cannot build a schema object at all, so this was
  a precondition for everything above. Keyword names, arguments and return values are unchanged.

### Fixed

- Drift detection no longer reports a change that is not one. A snapshot compared against a live
  server built on graphql-js claimed `DIRECTIVE_DEFINITION was removed from deprecated`, because
  graphql-js describes `@deprecated` with four locations while graphql-core's built-in adds a
  fifth. Both sides are now built the same way, so only real differences are reported.

## [0.1.0] - 2026-08-17

### Added

- First release of the library. It sends GraphQL queries and mutations over the synchronous
  `requests` transport of gql, and holds endpoints in a session pool addressed by alias.

  The behaviour worth stating plainly: a response carrying a non-empty `errors` array fails
  the keyword, whatever the status code was. A GraphQL server answers a failed operation with
  HTTP 200, so a suite that checks the status code passes on requests that returned nothing.
  Partial data, where `data` arrives alongside errors because a nullable field failed, fails
  the same way. `expect_errors=True` returns the response instead, for tests about the errors.

- Queries can be given as text, as a `.graphql` file, by name under an import-time
  `query_path`, as one of several named operations in a document, or as a list of lines. The
  list form exists because Robot Framework collapses runs of spaces inside a cell, which is
  what has made multi-line queries awkward to write in suites.

- Queries are parsed before they are sent, so a syntax error names its line and column, an
  unknown `operation_name` is answered with the names the document does hold, and a mutation
  handed to `Execute Query` is refused before it leaves.

- Response keywords carry assertion engine operators: `Get Graphql Data` with a dotted path,
  `Get Graphql Errors`, `Get Graphql Error Messages`, `Get Graphql Error Codes` and
  `Get Graphql Extensions`, alongside `Response Should Have No Errors`,
  `Response Should Have Errors`, `Response Should Have Partial Data` and
  `Error Should Exist At Path`, which matches on the error's `path` and `extensions.code`.

- `Check Query Result` re-sends a query until an assertion holds, for read models that are
  filled in asynchronously.

- `Create Graphql Session` accepts an existing `requests.Session`, so cookies, authentication
  and adapters configured elsewhere are shared. It is left open on teardown, since the
  library did not open it.

- Schema keywords read an endpoint through introspection, which is what the GraphiQL page at a
  `/graphql` URL shows: `Get Schema Queries` and `Get Schema Mutations` list what is offered,
  and `Get Deprecated Fields` and `Field Should Not Be Deprecated` cover the deprecations. They
  ask for deprecated fields explicitly, since introspection omits them otherwise, and they
  report object and interface fields only — requesting deprecated input fields or enum values
  errors on older servers. A server with introspection disabled, which is the default outside
  development on Apollo Server, is reported as such rather than as an empty schema.
