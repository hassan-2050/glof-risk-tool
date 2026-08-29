"""Stage 1 data acquisition.

Everything in this package is DELIBERATELY OUTSIDE the reproduce path. It is
the only code allowed to touch the network, and it runs once, by hand, to
produce the committed contents of data/pinned/. `make reproduce` never imports
it - the offline guard would kill it if it did, which is the point.
"""
