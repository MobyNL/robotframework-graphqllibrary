*** Settings ***
Documentation       What a general HTTP library cannot check.
...
...                 Every response in this suite arrives with status 200. A suite built on
...                 `Status Should Be    200` passes on all of them, including the ones where
...                 nothing was returned at all.

Resource            resources/local.resource

Suite Setup         Open A Session
Suite Teardown      Delete All Graphql Sessions


*** Test Cases ***
A Failed Operation Fails The Test Despite Status Two Hundred
    ${error}    Run Keyword And Expect Error    GraphQLResponseError: *    Execute Query    { boom }
    Should Contain    ${error}    Everything is broken.
    Should Contain    ${error}    code INTERNAL_ERROR

A Failed Operation Can Be Inspected Instead
    ${response}    Execute Query    { boom }    expect_errors=True
    Response Should Have Errors    ${response}    count=1
    Get Graphql Error Codes    ${response}    ==    ${{ ['INTERNAL_ERROR'] }}

Partial Data Fails By Default
    [Documentation]    Name resolved, avatar did not, and the server answered 200 with both.
    ${variables}    Create Dictionary    id=1
    Run Keyword And Expect Error
    ...    GraphQLResponseError: *at path user.avatar*
    ...    Execute Query    partial_user.graphql    variables=${variables}

Partial Data Can Be Asserted On
    ${variables}    Create Dictionary    id=1
    ${response}    Execute Query    partial_user.graphql    variables=${variables}    expect_errors=True
    Response Should Have Partial Data    ${response}
    Get Graphql Data    ${response}    user.name    ==    Alice
    Get Graphql Data    ${response}    user.avatar    ==    ${None}
    Error Should Exist At Path    ${response}    user.avatar    code=AVATAR_UNAVAILABLE

An Error Is Matched On Its Path And Code
    ${response}    Execute Query    { restricted }    expect_errors=True
    ${error}    Error Should Exist At Path    ${response}    restricted    code=FORBIDDEN
    Should Be Equal    ${error}[message]    You may not read this.

An Error At Another Path Does Not Match
    ${response}    Execute Query    { restricted }    expect_errors=True
    Run Keyword And Expect Error
    ...    No GraphQL error at path 'ping'.*
    ...    Error Should Exist At Path    ${response}    ping

A Clean Response Has No Errors
    ${response}    Execute Query    { ping }
    Response Should Have No Errors    ${response}
    Get Graphql Data    ${response}    ping    ==    pong
