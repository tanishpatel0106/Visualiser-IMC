# NVDA day-0 dataset

Lossless NVDA-only extraction from the two Git LFS files in source commit
`9414ecfe301ff3032ba0713fed714e47bcbb2947`.

- Price source SHA-256: `5a5946e0bc7c4ab2650e3d6f15f275a4e21b8c5d430a47fefa5c1e5e358377e3`
- Trade source SHA-256: `b43b1532e498e9ca12a5001f6880ef97c3c6e29c4c8277e579eb0839c407157e`
- 4,038,507 snapshots; 318,515 trades; 404 ranges.
- All NVDA records are retained. Other stocks are excluded. No downsampling,
  rounding, or duplicate removal is applied. Original timestamps are preserved.

The manifest records counts, boundaries, compressed sizes, and per-file SHA-256
checksums. Gzip chunks are ordinary Git files, not LFS pointers. The backend
loads a selected range on demand; see `docs/vercel.md` for deployment and
private Blob publishing. Regenerate with `scripts/prepare_nvda.py` using the
hydrated originals. Neither the full multi-stock input nor credentials are
bundled in this directory.
