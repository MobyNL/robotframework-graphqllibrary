# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
