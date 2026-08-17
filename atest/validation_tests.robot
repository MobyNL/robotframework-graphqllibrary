*** Settings ***
Documentation       Checking queries against the endpoint's own schema before they are sent.
...
...                 Every failure here would otherwise have been a round trip to the server, and
...                 `Validate Query` alone would have passed all of them: it parses and nothing
...                 more, so it cannot know which fields exist.

Resource            resources/local.resource

Suite Setup         Open A Session
Suite Teardown      Delete All Graphql Sessions


*** Test Cases ***
A Valid Query Is Sent As Usual
    ${response}    Execute Query    { ping }
    Should Be Equal    ${response.data.ping}    pong

An Unknown Root Field Is Caught Before Anything Is Sent
    Run Keyword And Expect Error
    ...    ValueError: The query does not match the schema. 1 problem(s) found:*Cannot query field 'nope' on type 'Query'.*
    ...    Execute Query    { nope }

An Unknown Field On A Type Is Caught, With A Suggestion
    ${error}    Run Keyword And Expect Error    ValueError: *
    ...    Execute Query    { user(id: "1") { nickname } }
    Should Contain    ${error}    Cannot query field 'nickname' on type 'User'
    Should Contain    ${error}    Did you mean 'name'

A Missing Required Argument Is Caught
    ${error}    Run Keyword And Expect Error    ValueError: *    Execute Query    { user { name } }
    Should Contain    ${error}    argument 'id' of type 'ID!' is required

A Missing Sub Selection Is Caught
    ${error}    Run Keyword And Expect Error    ValueError: *    Execute Query    { user(id: "1") }
    Should Contain    ${error}    must have a selection of subfields

Every Problem Is Reported At Once
    [Documentation]    graphql-core validates the whole document, so one run names both faults.
    ${error}    Run Keyword And Expect Error    ValueError: *
    ...    Execute Query    { nope alsoNope }
    Should Contain    ${error}    2 problem(s) found
    Should Contain    ${error}    'nope'
    Should Contain    ${error}    'alsoNope'

A Mutation Is Checked The Same Way
    ${error}    Run Keyword And Expect Error    ValueError: *
    ...    Execute Mutation    mutation { createUser(name: "Ada") { nickname } }
    Should Contain    ${error}    Cannot query field 'nickname' on type 'User'

The Explicit Keyword Checks Without Sending
    Query Should Be Valid Against Schema    { user(id: "1") { name } }
    Run Keyword And Expect Error    ValueError: *
    ...    Query Should Be Valid Against Schema    { user(id: "1") { nickname } }

The Explicit Keyword Accepts A Query File
    Query Should Be Valid Against Schema    get_user.graphql

Validate Query Still Only Checks Syntax
    [Documentation]    The distinction the two keywords exist to draw: this one passes a query
    ...    naming a field the schema does not have, because it never contacts the server.
    Validate Query    { user(id: "1") { nickname } }
    Run Keyword And Expect Error    ValueError: The query could not be parsed.*
    ...    Validate Query    { user(id: "1"

Execute Raw Request Is Not Validated
    [Documentation]    Documented as unchecked, so a query the schema rejects still goes out and
    ...    the server's own error comes back.
    ${response}    Execute Raw Request    { nope }
    Should Not Be Empty    ${response.errors}

Refreshing The Schema Is Harmless And Keeps Validation Working
    Refresh Graphql Schema
    ${response}    Execute Query    { ping }
    Should Be Equal    ${response.data.ping}    pong
    Run Keyword And Expect Error    ValueError: *    Execute Query    { nope }
