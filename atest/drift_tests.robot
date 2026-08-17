*** Settings ***
Documentation       Noticing that a schema changed under a suite.
...
...                 A snapshot is committed SDL, so the change shows up in review. These tests
...                 compare the live schema against snapshots written to ``${TEMPDIR}``, including
...                 hand-edited ones standing in for an earlier deployment.

Library             Collections
Library             OperatingSystem
Resource            resources/local.resource

Suite Setup         Open A Session
Suite Teardown      Delete All Graphql Sessions
Test Setup          Remove Snapshots


*** Variables ***
${SNAPSHOT}         ${TEMPDIR}/graphql_schema_snapshot.graphql


*** Test Cases ***
A Snapshot Round Trips With Nothing Changed
    Save Schema Snapshot    ${SNAPSHOT}
    File Should Exist    ${SNAPSHOT}
    Get Schema Breaking Changes    ${SNAPSHOT}    ==    ${{ [] }}
    Get Schema Dangerous Changes    ${SNAPSHOT}    ==    ${{ [] }}
    Schema Should Have No Breaking Changes    ${SNAPSHOT}

A Snapshot Is Readable SDL
    [Documentation]    The reason for choosing SDL over introspection JSON: a person reads it.
    Save Schema Snapshot    ${SNAPSHOT}
    ${sdl}    Get File    ${SNAPSHOT}
    Should Contain    ${sdl}    type User
    Should Contain    ${sdl}    ping: String!
    Should Contain    ${sdl}    @deprecated(reason: "Use contact instead.")

A Field The Live Schema No Longer Has Is Breaking
    [Documentation]    The snapshot claims a field the server does not have, which is what a
    ...    removal looks like from a suite's side.
    Save A Snapshot Claiming An Extra Query Field
    ${changes}    Get Schema Breaking Changes    ${SNAPSHOT}
    Should Not Be Empty    ${changes}
    Should Contain Match    ${changes}    *FIELD_REMOVED*wasHere*

Removing A Field Is Reported As A Failure By The Assertion Keyword
    Save A Snapshot Claiming An Extra Query Field
    ${error}    Run Keyword And Expect Error    *breaking change*
    ...    Schema Should Have No Breaking Changes    ${SNAPSHOT}
    Should Contain    ${error}    wasHere

A Field The Snapshot Did Not Have Is Neither Breaking Nor Dangerous
    [Documentation]    An added optional field cannot break an existing query.
    Save Schema Snapshot    ${SNAPSHOT}
    ${sdl}    Get File    ${SNAPSHOT}
    ${edited}    Replace String    ${sdl}    ping: String!\n    ${EMPTY}
    Create File    ${SNAPSHOT}    ${edited}
    Get Schema Breaking Changes    ${SNAPSHOT}    ==    ${{ [] }}
    Get Schema Dangerous Changes    ${SNAPSHOT}    ==    ${{ [] }}

A Missing Snapshot Is Reported As A Bad Call
    Run Keyword And Expect Error
    ...    ValueError: Schema snapshot *not found*Save Schema Snapshot*
    ...    Get Schema Breaking Changes    ${TEMPDIR}/no_such_snapshot.graphql

A Snapshot That Is Not SDL Is Reported As A Bad Call
    Create File    ${SNAPSHOT}    this is not a schema
    Run Keyword And Expect Error
    ...    ValueError: Schema snapshot *could not be read as SDL*
    ...    Get Schema Breaking Changes    ${SNAPSHOT}


*** Keywords ***
Remove Snapshots
    [Documentation]    Each test writes its own snapshot, so none inherits another's edits.
    Remove File    ${SNAPSHOT}

Save A Snapshot Claiming An Extra Query Field
    [Documentation]    Writes a snapshot of the live schema, then adds a query field the server
    ...    does not have, standing in for a field that was removed since the snapshot was taken.
    ...
    ...    The two spaces indenting the added field are escaped: unescaped they would be an
    ...    argument separator, which is the same whitespace rule that makes multi-line queries
    ...    awkward in a suite and the reason this library reads queries from files.
    Save Schema Snapshot    ${SNAPSHOT}
    ${sdl}    Get File    ${SNAPSHOT}
    ${edited}    Replace String    ${sdl}    ping: String!    ping: String!\n\ \ wasHere: String
    Create File    ${SNAPSHOT}    ${edited}
