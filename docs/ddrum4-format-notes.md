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

## Nested compiler boundary

`compile-nested` is now the backend-neutral compilation step. It accepts a
declared layout, validates the DDrum4 ten-slot/ten-layer and Note P position
limits, and emits the matching `routing-contract.json` plus a coverage report.
With `--firmware-header`, it also invokes the existing firmware generator from
that generated contract, producing a non-overwriting Arduino mapping header.
It does not claim to encode a DDrum4 sound file; that remains blocked on one
verified ddrum4UI/ddrum4edit build fixture. See
`profiles/banks/nested-compiler-fixture.yaml` for the minimal safe example.

## Snare source selection

`select-snare` selects evenly distributed velocity levels from a captured
neutral library: up to seven head layers, two rim layers, then one captured
cross-stick or a clearly reported strongest-head fallback. It refuses planned,
unlicensed, or source-unattributed takes, and never creates encoded audio or
sends MIDI. The resulting JSON is an input record for the later verified
ddrum4edit build, not a transferable sound file.
