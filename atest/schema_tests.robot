*** Settings ***
Documentation       Reading a schema through introspection, against a real server.
...
...                 This is what the GraphiQL page at a ``/graphql`` URL shows: the operations an
...                 endpoint offers, and what it has deprecated.

Resource            resources/local.resource

Suite Setup         Open A Session
Suite Teardown      Delete All Graphql Sessions


*** Test Cases ***
The Schema's Queries Are Listed
    ${queries}    Get Schema Queries
    Should Contain    ${queries}    ping
    Should Contain    ${queries}    user
    Get Schema Queries    contains    users

The Schema's Mutations Are Listed
    Get Schema Mutations    ==    ${{ ['createUser', 'deleteUser'] }}

A Deprecated Field Is Reported With Its Type
    [Documentation]    The server deprecates User.email, and nothing else.
    Get Deprecated Fields    ==    ${{ ['User.email'] }}

The Introspection Types Are Not Reported As Schema
    [Documentation]    Every server carries __Type and friends; they are not what a suite asks about.
    ${deprecated}    Get Deprecated Fields
    FOR    ${field}    IN    @{deprecated}
        Should Not Start With    ${field}    __
    END

A Current Field Passes The Deprecation Check
    Field Should Not Be Deprecated    User.name

A Deprecated Field Fails The Deprecation Check With Its Reason
    Run Keyword And Expect Error
    ...    Field 'User.email' is deprecated: Use contact instead.
    ...    Field Should Not Be Deprecated    User.email

An Unknown Field Is Reported As A Bad Call
    Run Keyword And Expect Error
    ...    ValueError: Type 'User' has no field 'nope'.*
    ...    Field Should Not Be Deprecated    User.nope

Introspection Runs On The Session It Is Given
    [Documentation]    The alias argument reaches the same session pool the other keywords use.
    Create Graphql Session    ${GRAPHQL_URL}    alias=second
    Get Schema Queries    contains    ping    alias=second
    Delete Graphql Session    second
