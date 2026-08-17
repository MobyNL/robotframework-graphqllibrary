*** Settings ***
Documentation       Endpoint the suites run against, and the setup steps they share.
...
...                 Defaults to the server in ``atest/server``, started by ``run_atest.sh``.
...                 Override it to run the suites against another endpoint:
...                 ``robot -v GRAPHQL_URL:http://elsewhere/graphql atest``.

Library             String
Library             GraphQLLibrary    query_path=${CURDIR}/../queries
Library             RequestsLibrary


*** Variables ***
${GRAPHQL_URL}      http://localhost:8099/graphql


*** Keywords ***
Open A Session
    [Documentation]    Opens the default session and resets the server's counters.
    Create Graphql Session    ${GRAPHQL_URL}
    Reset The Server

Reset The Server
    [Documentation]    Puts the server back in its starting state, for the retrying suite.
    ${reset_url}    Replace String    ${GRAPHQL_URL}    /graphql    /reset
    POST    ${reset_url}    json=${{ {} }}
