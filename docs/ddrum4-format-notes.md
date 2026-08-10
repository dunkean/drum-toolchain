# DDrum4 Backend Notes

`ddrum4edit` 1.3.0 is the current backend. Both directions were demonstrated
locally with the disposable `KICK_999` click fixture:

1. `ddrum4edit -e -i KICK_999.mid -n ignored.cfg` exports
   `KICK_999.cfg` and `KICK_999_s1.smp` in the working directory. The output
   name is derived from the input name; the `-n` argument does not control it.
2. Copy/modify that configuration and its sample files, then run
   `ddrum4edit -c ROUNDTRIP_999.cfg`. The destination comes from the
   `-Begin-Sound-File-Out-` section of the configuration.
3. The round-trip generated a non-empty 11-block sound that `-p` parses
   successfully. It is not byte-identical to the input because file/path
   metadata is encoded, which is expected.

`Ddrum4EditBackend.build()` now follows exactly that verified command. It
requires the requested output path to equal the configuration's declared path,
refuses to overwrite an existing file, and verifies the newly generated file
with `-p` before returning. This is useful for creating original user samples;
it is not a licence to reuse factory audio.

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
