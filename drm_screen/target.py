"""Target adapters — how a command batch reaches the service.

The composer (and any client) calls `target.submit(batch)`.  The transport is
abstracted so the same client code runs against an in-process service (debug) or
a remote daemon over a socket (production).
"""


class InProcessTarget:
    """Debug only — service runs in the same process. Direct enqueue."""

    def __init__(self, service):
        self.service = service

    def submit(self, commands):
        self.service.submit(commands)


class SocketTarget:
    """Production — drm_screen is a separate daemon. Commands cross the wire.

    Stub: real implementation serializes via commands.to_wire() over a unix
    socket / HTTP POST and returns on ack.  Not needed for the in-process
    prototype.
    """

    def __init__(self, address):
        self.address = address

    def submit(self, commands):
        raise NotImplementedError("SocketTarget transport not implemented yet")
