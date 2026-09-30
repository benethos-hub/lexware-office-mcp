"""How a client reaches this server: stdio, or HTTP behind a bearer token.

``stdio`` is the default and what a local client uses. ``http`` serves the
same tools on a port, with the guards a port needs, and ``watch`` ends the
process when its settings change, for a deployment that restarts it. See
SPECS.md section 6.
"""
