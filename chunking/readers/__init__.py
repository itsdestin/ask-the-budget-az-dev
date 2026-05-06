"""Format-aware readers.

Each reader (ODL / MinerU / python-docx) consumes one extractor's output and
emits a uniform `ExtractedDocument` (see `types`). The chunk builders in
`chunking/builders/` consume `ExtractedDocument` and don't know which
extractor produced it — that's the whole point of the reader layer.
"""
