# DDrum4 Backend Notes

`ddrum4edit` 1.3.0 is the current backend. Its read-only `-p` inspection has
been demonstrated locally on a copied reference sound and reports the encoded
block count (for example, 38 blocks for one reference snare). This is useful
for measuring final user-created sounds, not a licence to reuse factory audio.

The configuration-to-sound command line has not yet been demonstrated with a
reproducible, non-factory fixture. A binary-string inspection reveals
configuration and input/output options, but the obvious combinations did not
generate an exported configuration on this installation. The bank builder
therefore fails closed for `build()` rather than guessing an encoded format or
creating a possibly malformed transfer file.

To remove this block, perform one manual reference export/build using
ddrum4UI/ddrum4edit on a disposable synthetic sound after the settings backup
is verified. Record the exact successful command line and files, then add it
as a regression fixture before enabling bulk builds.
