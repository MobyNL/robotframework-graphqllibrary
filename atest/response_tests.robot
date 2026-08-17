*** Settings ***
Documentation       Reading values out of a response, and the retrying assertion.

Resource            resources/local.resource

Suite Setup         Open A Session
Suite Teardown      Delete All Graphql Sessions


*** Test Cases ***
A Field Is Read By Path
    ${variables}    Create Dictionary    id=1
    ${response}    Execute Query    get_user.graphql    variables=${variables}
    Get Graphql Data    ${response}    user.name    ==    Alice

A List Position Is A Number In The Path
    ${response}    Execute Query    user_document.graphql    operation_name=GetUsers
    Get Graphql Data    ${response}    users.0.name    ==    Alice

Fields Are Also Reachable With A Dot On The Response
    ${response}    Execute Query    { ping }
    Should Be Equal    ${response.data.ping}    pong

A Missing Field Reports What The Query Did Return
    ${response}    Execute Query    { ping }
    Run Keyword And Expect Error    ValueError: 'pong' is not in 'data'.*    Get Graphql Data    ${response}    pong

Assertion Operators Work On Read Values
    ${response}    Execute Query    user_document.graphql    operation_name=GetUsers
    Get Graphql Data    ${response}    users.0.name    !=    Bob
    Get Graphql Data    ${response}    users.1.name    ^=    Bo
    Get Graphql Data    ${response}    users    validate    len(value) >= 2

A Query Is Re-Sent Until The Assertion Holds
    [Documentation]    The server answers "pending" twice before "ready", standing in for a
    ...    read model that is filled in asynchronously.
    Reset The Server
    Check Query Result    { eventually }    eventually    ==    ready    retry_timeout=10s    retry_pause=100ms

A Retried Assertion Still Fails At The Timeout
    Reset The Server
    Run Keyword And Expect Error
    ...    GraphQL data 'eventually'*
    ...    Check Query Result    { eventually }    eventually    ==    never    retry_timeout=1s    retry_pause=100ms
