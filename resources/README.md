# Frozen public suffix snapshot

`url-v2-suffix.dat` is the unmodified public suffix list obtained from
https://publicsuffix.org/list/public_suffix_list.dat during the v1 acquisition.
It is public domain-name metadata, not labelled research URLs or user content.
Its embedded notice licenses it under Mozilla Public License 2.0:
https://mozilla.org/MPL/2.0/ . Copyright and license notices remain intact.

Version: 2026-10-01_23-02-52_UTC; upstream commit
`6cd82aff889e3d64e5e03bc5c1f43da1934a960a`.
SHA-256: `e0fe072d26b0536525badea237953ff451c9f8e64c9d02c6daa81a4491d2fc66`.
This immutable snapshot makes offline tests and v2 reproduction independent of
ignored v1 files. Never update it during an experiment. The original v1 copy is preserved.
