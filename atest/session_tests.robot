*** Settings ***
Documentation       Opening, selecting and closing endpoints, and sharing an HTTP session.

Resource            resources/local.resource

Suite Teardown      Delete All Graphql Sessions
Test Teardown       Delete All Graphql Sessions


*** Test Cases ***
Two Endpoints Can Be Open At Once
    Create Graphql Session    ${GRAPHQL_URL}    alias=first
    Create Graphql Session    ${GRAPHQL_URL}    alias=second
    ${aliases}    List Graphql Sessions
    Should Be Equal    ${aliases}    ${{ ['first', 'second'] }}
    Get Active Graphql Session    ==    second

Keywords Use The Active Session Unless Given An Alias
    Create Graphql Session    ${GRAPHQL_URL}    alias=first
    Create Graphql Session    ${GRAPHQL_URL}    alias=second
    ${previous}    Switch Graphql Session    first
    Should Be Equal    ${previous}    second
    ${response}    Execute Query    { ping }
    Should Be Equal    ${response.data.ping}    pong
    ${response}    Execute Query    { ping }    alias=second
    Should Be Equal    ${response.data.ping}    pong

Deleting One Session Leaves The Other Working
    Create Graphql Session    ${GRAPHQL_URL}    alias=first
    Create Graphql Session    ${GRAPHQL_URL}    alias=second
    Delete Graphql Session    first
    Graphql Session Should Exist    second
    ${response}    Execute Query    { ping }    alias=second
    Should Be Equal    ${response.data.ping}    pong

Using A Session That Was Never Opened Says How To Open One
    Run Keyword And Expect Error    *Create Graphql Session*    Execute Query    { ping }

Headers Can Be Set After The Session Was Opened
    Create Graphql Session    ${GRAPHQL_URL}
    ${headers}    Set Graphql Headers    ${{ {'X-Tenant': 'acme'} }}
    Should Be Equal    ${headers}[X-Tenant]    acme
    ${response}    Execute Query    { ping }
    Should Be Equal    ${response.data.ping}    pong

An Existing Requests Session Can Be Shared
    [Documentation]    The interop hook: cookies and adapters configured elsewhere are reused,
    ...    and the session stays open after the GraphQL session is deleted.
    ${http_session}    Evaluate    __import__('requests').Session()
    Create Graphql Session    ${GRAPHQL_URL}    http_session=${http_session}
    ${response}    Execute Query    { ping }
    Should Be Equal    ${response.data.ping}    pong
    Delete All Graphql Sessions
    ${still_open}    Evaluate    bool($http_session.adapters)
    Should Be True    ${still_open}
    Call Method    ${http_session}    close
