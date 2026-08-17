# robotframework-graphql

GraphQL test library for Robot Framework.

[Keyword documentation](https://mobynl.github.io/robotframework-graphqllibrary/)

## Why not just RequestsLibrary

A GraphQL endpoint is one HTTP POST, so a general HTTP library can send one. What it cannot
do is tell whether the operation worked.

A server answering `application/json` returns **HTTP 200 even when the operation failed**,
and reports the failure in an `errors` array in the body. This is what the
[GraphQL over HTTP specification](https://github.com/graphql/graphql-over-http/blob/main/spec/GraphQLOverHTTP.md)
calls for. A suite built on `Status Should Be    200` therefore passes on a request that
returned nothing at all:

```robotframework
# Passes even when the server returned {"data": null, "errors": [{"message": "..."}]}
${response}    POST On Session    api    /graphql    json=${body}
Status Should Be    200    ${response}
```

Every keyword here that sends an operation checks the `errors` array and fails on it,
including the partial case where `data` came back alongside errors because a nullable field
failed. That is the default, not something a suite has to remember.

The second problem is syntax. Robot Framework collapses runs of spaces inside a cell, so a
query written across several lines breaks. The usual workaround is a `.json` file holding
the query as one escaped line, which is neither readable nor reviewable. This library takes
queries from real `.graphql` files.

## Features

- Fails on GraphQL errors by default, including partial data, whatever the status code was
- Queries from `.graphql` files, by path or by name under a query directory
- Several named operations per document, chosen by name
- Inline queries as a list of lines, which survives Robot Framework's whitespace handling
- Queries parsed before they are sent, so a syntax error names its line and column
- Response getters with [assertion engine](https://github.com/MarketSquare/AssertionEngine)
  operators, as in `Get Graphql Data    ${response}    user.name    ==    Alice`
- Error assertions that speak GraphQL: `path`, `extensions.code`, partial data
- A retrying `Check Query Result` for read models that are filled in asynchronously
- Schema introspection: list an endpoint's queries and mutations, and assert on deprecations
- Session pool with aliases, sharing one connection pool per endpoint
- Interop: an existing `requests.Session` can be handed in, so cookies and adapters
  configured elsewhere are reused

## Installation

```
pip install robotframework-graphql
```

## Requirements

| Requirement | Version |
| --- | --- |
| Python | 3.10 or later |
| Robot Framework | 6.1.1 or later, below 8 |
| gql | 4.x, with the `requests` transport |
| graphql-core | 3.2.x |
| robotframework-assertion-engine | 5.x |

## Importing

```robotframework
*** Settings ***
Library    GraphQLLibrary    query_path=${CURDIR}/queries
```

- `query_path`: directory that queries given by file name are looked up in.
- `validate_queries`: whether queries are checked locally before they are sent. Default true.

## Usage

```robotframework
*** Settings ***
Library           GraphQLLibrary    query_path=${CURDIR}/queries
Suite Teardown    Delete All Graphql Sessions

*** Test Cases ***
A User Can Be Read Back
    Create Graphql Session    https://api.example.com/graphql    token=${API_TOKEN}
    ${variables}    Create Dictionary    id=1
    ${response}     Execute Query    get_user.graphql    variables=${variables}
    Get Graphql Data    ${response}    user.name    ==    Alice

A Denied Field Is Reported With Its Path And Code
    ${response}    Execute Query    get_user.graphql    expect_errors=True
    Response Should Have Partial Data    ${response}
    Error Should Exist At Path    ${response}    user.avatar    code=FORBIDDEN
```

### Writing queries

Three forms, all accepted wherever a query is:

```robotframework
# A file, under query_path or as a path
${response}    Execute Query    get_user.graphql

# One document, several named operations
${response}    Execute Query    user_document.graphql    operation_name=GetUsers

# Inline, as a list of lines
@{lines}       Create List    query {    ${SPACE*4}ping    }
${response}    Execute Query    ${lines}
```

The query reaching the server is the parsed document printed back out, so it arrives in the
standard layout rather than exactly as it was written.

### Sharing a session with RequestsLibrary

```robotframework
${http_session}    Evaluate    __import__('requests').Session()
Create Graphql Session    ${GRAPHQL_URL}    http_session=${http_session}
```

The supplied session is left open when the GraphQL session is deleted, because this library
did not open it.

## Deliberately not wrapped

Subscriptions, file uploads, request batching and persisted queries. Schema introspection
covers object and interface fields, so deprecated input fields and enum values are not
reported. `Execute Raw Request` sends an operation with no checking at all, for cases this
library does not model.

## Development

```
poetry install
poetry run pytest utest
./run_atest.sh                     # starts the test server, runs the acceptance suites
poetry run ruff check . && poetry run mypy && poetry run robocop check atest
```

## License

MIT
