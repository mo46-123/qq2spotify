# Test fixtures

`qq_playlist_sample.json` is a hand-written sample shaped like QQ Music's
`fcg_ucc_getcdinfo_byids_cp.fcg` reply. It covers a repeated song, a song with
no ID, HTML entities, square brackets and a missing length.

To add a real reply, run:

```bash
qq2spotify inspect "<QQ playlist link>" --save-raw tests/fixtures/<name>.json
```

Then trim it to about 10 songs before committing it.
