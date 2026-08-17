"""A small GraphQL server for the acceptance suites.

Built on graphql-core and ``http.server``, both of which are already available: graphql-core
is a dependency of the library, and the standard library provides the rest. A framework
would have added a dependency for a server whose whole job is to answer in the shapes the
suites assert on.

The schema is deliberately unhelpful in specific ways, because those are the cases plain
HTTP testing cannot see:

- ``boom`` fails outright, and the server still answers HTTP 200.
- ``user.avatar`` fails while its siblings resolve, producing partial data.
- ``restricted`` fails with an ``extensions.code``.
- ``eventually`` answers wrongly the first few times, for the retrying keyword.

Run it with ``python atest/server/graphql_server.py [port]``.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from graphql import build_schema, graphql_sync, GraphQLError

SCHEMA = build_schema(
    """
    type User {
        id: ID!
        name: String!
        avatar: String
        email: String @deprecated(reason: "Use contact instead.")
    }

    type Query {
        ping: String!
        user(id: ID!): User
        users: [User!]!
        boom: String
        restricted: String
        eventually: String
    }

    type Mutation {
        createUser(name: String!): User!
        deleteUser(id: ID!): Boolean!
    }
    """
)

INITIAL_USERS = {
    "1": {"id": "1", "name": "Alice"},
    "2": {"id": "2", "name": "Bob"},
}

USERS = dict(INITIAL_USERS)

STATE = {"attempts": 0, "next_id": 3}


def reset() -> None:
    """Put the server back in its starting state.

    Called from the suites, so that a suite asserting on the number of users is not broken
    by a mutation another suite ran, and so a rerun against a still-running server behaves
    like the first run.
    """
    USERS.clear()
    USERS.update({key: dict(value) for key, value in INITIAL_USERS.items()})
    STATE["attempts"] = 0
    STATE["next_id"] = 3


def resolve_avatar(user, info):
    """Fail for one field while its siblings resolve, which is the partial data case."""
    raise GraphQLError("Avatars are not available.", extensions={"code": "AVATAR_UNAVAILABLE"})


def resolve_boom(root, info):
    raise GraphQLError("Everything is broken.", extensions={"code": "INTERNAL_ERROR"})


def resolve_restricted(root, info):
    raise GraphQLError("You may not read this.", extensions={"code": "FORBIDDEN"})


def resolve_eventually(root, info):
    """Answer wrongly twice, then correctly, standing in for a lagging read model."""
    STATE["attempts"] += 1
    return "ready" if STATE["attempts"] > 2 else "pending"


def resolve_create_user(root, info, name):
    user = {"id": str(STATE["next_id"]), "name": name}
    STATE["next_id"] += 1
    USERS[user["id"]] = user
    return user


def resolve_delete_user(root, info, id):
    return USERS.pop(id, None) is not None


SCHEMA.query_type.fields["ping"].resolve = lambda root, info: "pong"
SCHEMA.query_type.fields["user"].resolve = lambda root, info, id: USERS.get(id)
SCHEMA.query_type.fields["users"].resolve = lambda root, info: list(USERS.values())
SCHEMA.query_type.fields["boom"].resolve = resolve_boom
SCHEMA.query_type.fields["restricted"].resolve = resolve_restricted
SCHEMA.query_type.fields["eventually"].resolve = resolve_eventually
SCHEMA.mutation_type.fields["createUser"].resolve = resolve_create_user
SCHEMA.mutation_type.fields["deleteUser"].resolve = resolve_delete_user
SCHEMA.type_map["User"].fields["avatar"].resolve = resolve_avatar


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - the name http.server requires
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/reset":
            reset()
            return self._respond({"reset": True})
        result = graphql_sync(
            SCHEMA,
            body.get("query", ""),
            variable_values=body.get("variables"),
            operation_name=body.get("operationName"),
        )
        payload: dict = {"data": result.data}
        if result.errors:
            payload["errors"] = [error.formatted for error in result.errors]
        # Sent on every response so the suites have something to read out of extensions.
        payload["extensions"] = {"cost": {"actual": len(body.get("query", "")) // 10}}
        # Status 200 even when the operation failed. That is what the specification calls for
        # with the application/json media type, and the reason a status check proves nothing.
        self._respond(payload)

    def _respond(self, payload: dict) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:
        """Silence the per-request logging, which would drown the Robot Framework output."""


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f"GraphQL test server listening on http://localhost:{port}/graphql", flush=True)
    ThreadingHTTPServer(("localhost", port), Handler).serve_forever()
