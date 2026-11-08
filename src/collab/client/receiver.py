"""Background receiver for server messages.

The connection-level receiving loop is integrated directly into
`collab.client.connection.ClientConnection._receive_loop` to manage
frame reading, pending request correlation, and event dispatching.
"""

