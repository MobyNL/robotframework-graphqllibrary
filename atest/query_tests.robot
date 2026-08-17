*** Settings ***
Documentation       Sending queries and mutations, in each of the ways a query can be given.

Resource            resources/local.resource

Suite Setup         Open A Session
Suite Teardown      Delete All Graphql Sessions


*** Test Cases ***
A Query Can Be Written Inline
    ${response}    Execute Query    { ping }
    Should Be Equal    ${response.data.ping}    pong

A Query Can Be Written Across Several Lines
    [Documentation]    Robot Framework collapses runs of spaces in a cell, so the query is
    ...    given as a list of lines and joined with newlines.
    @{lines}    Create List    query {    ${SPACE*4}user(id: "1") {    ${SPACE*8}name    ${SPACE*4}}    }
    ${response}    Execute Query    ${lines}
    Should Be Equal    ${response.data.user.name}    Alice

A Query Can Come From A File
    ${variables}    Create Dictionary    id=2
    ${response}    Execute Query    get_user.graphql    variables=${variables}
    Should Be Equal    ${response.data.user.name}    Bob

A Query File Can Hold Several Named Operations
    ${operations}    Get Query Operations    user_document.graphql
    Should Be Equal    ${operations}    ${{ ['GetUser', 'GetUsers'] }}
    ${response}    Execute Query    user_document.graphql    operation_name=GetUsers
    Length Should Be    ${response.data.users}    2

Choosing No Operation From A Document With Several Fails
    Run Keyword And Expect Error
    ...    ValueError: This query holds 2 operations*
    ...    Execute Query    user_document.graphql

A Query Can Be Loaded And Sent Separately
    ${query}    Load Query    get_user.graphql
    Should Contain    ${query}    query GetUser
    ${variables}    Create Dictionary    id=1
    ${response}    Execute Query    ${query}    variables=${variables}
    Should Be Equal    ${response.data.user.id}    1

A Mutation Changes State And Is Read Back
    ${variables}    Create Dictionary    name=Dana
    ${created}    Execute Mutation    create_user.graphql    variables=${variables}
    ${id}    Set Variable    ${created.data.createUser.id}
    ${lookup}    Create Dictionary    id=${id}
    ${read_back}    Execute Query    get_user.graphql    variables=${lookup}
    Should Be Equal    ${read_back.data.user.name}    Dana

A Query Sent As A Mutation Is Refused Before It Leaves
    Run Keyword And Expect Error
    ...    ValueError: This is a query, but a mutation was expected.*
    ...    Execute Mutation    { ping }

A Mutation Sent As A Query Is Refused Before It Leaves
    Run Keyword And Expect Error
    ...    ValueError: This is a mutation, but a query was expected.*
    ...    Execute Query    mutation { deleteUser(id: "2") }

A Syntax Error Names Its Position
    Run Keyword And Expect Error    ValueError: *1:7*    Execute Query    { ping

A Missing Query File Is Reported As A Missing File
    Run Keyword And Expect Error    ValueError: Query file 'nope.graphql' was not found.*    Execute Query    nope.graphql

Validating A Query Does Not Send It
    Validate Query    get_user.graphql
    Run Keyword And Expect Error    ValueError: The query could not be parsed.*    Validate Query    { ping

Extensions Are Returned Alongside The Data
    ${response}    Execute Query    { ping }
    Get Graphql Extensions    ${response}    cost.actual    >=    ${0}

A Raw Request Skips Every Check
    ${response}    Execute Raw Request    { boom }
    Should Not Be Empty    ${response.errors}
