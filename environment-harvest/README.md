# Iconic Environments 300

Execution-only image harvest for 300 instantly recognizable environments across games, films, television, western animation, anime, music videos, television/YouTube sets, and real-world/documentary locations.

## Curated allocation

- 70 video-game environments
- 70 film environments
- 50 television-series environments
- 30 western-animation environments
- 30 anime environments
- 15 music-video environments
- 15 television/YouTube sets
- 20 real-world and documentary locations

## Acceptance rules

The runner selects exactly one landscape image per catalog entry. It requires metadata evidence for both the work and location, rejects stock/social/fan-art/AI/merchandise sources, filters dominant faces and weak images, validates resolution, sharpness and entropy, and performs global SHA-256 plus perceptual-hash deduplication.

The output artifact is named `iconic-environments-300` and contains:

- `iconic-environments-300.zip`
- one numbered JPEG per accepted environment
- CSV and JSON manifests with source URLs and validation metrics
- failure report
- contact sheets for rapid visual review
- execution log

The five engine parts are concatenated in lexical order. The expected SHA-256 of the assembled `harvest.py` is `00a9bd4a171083b849df2476090c587a570587bc813b7fdf5727bc2341d32e27`.
