"""Pure domain core of the Roller Shutter Suite.

Purity rule: nothing in this package imports from ``homeassistant`` or from the
rest of the integration. The core is plain Python. It receives the time, the
sun position and every other input through its ports and never reads a clock
itself, so it can be unit-tested and run in a time-lapse simulation.
"""
