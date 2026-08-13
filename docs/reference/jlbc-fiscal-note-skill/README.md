# The JLBC fiscal-note skill — vendored as a reference

Copied 2026-08-13 from Destin's personal skill library
(`GoogleDrive/Claude/Backup/personal/skills/jlbc-fiscal-note`) at his
direction, so this repo has a committed record of JLBC's actual house
writing style rather than an inferred one.

**This is REFERENCE MATERIAL. It does not run here, and it is not wired
into anything.**

## What it is

A Claude skill that drafts first-draft fiscal notes into the official
JLBC 2026 Word template. It expects a Claude-style harness: skill
frontmatter that a loader reads, an `ask_user_input_v0` widget tool for
its interview gates, and filesystem access to unpack a `.docx` and edit
`word/document.xml` by hand.

**AI Mode has none of those.** It is an in-process OpenRouter tool loop
with five tools (`retrieve`, `cite`, `cite_batch`, `list_filter_values`,
`create_document`), no skill loader, no widget tool, and no filesystem
reach — Invariant 7 is specifically about the last one. So the skill
cannot be dropped in and run.

## What it is FOR, here

Its **style rules** are the part worth borrowing, because they are real
JLBC conventions rather than a guess:

- number formatting — millions to one decimal keeping the trailing zero
  (`$6.0 million`), thousands with no decimal (`$400,000`), negatives in
  parentheses, percentages always numerals, `FY 2026` never `FY26`
- forbidden phrases — `"It is estimated that"`, `"note that"`,
  `"please note"`, `"it should be noted"`, `"on an annual basis"`
- voice — active, first-person plural (`"We estimate..."`), `"We
  believe"` to mark JLBC's own judgement against an agency's
- agency abbreviations — spell out on first use, then abbreviate
- length discipline — "one page maximum, trim aggressively"

Its **workflow** (intake interview, source sign-off gate, estimate
decision point, tiered research protocol) belongs to a human-in-the-loop
drafting tool and does NOT transfer to AI Mode, which answers a question
in one turn.

## Do not

- import from it, or read it at runtime
- copy its `.docx`-XML-editing approach — `memo/` builds documents with
  python-docx and is tested against the reference memo
- treat its fiscal-note section structure (Description / Estimated Impact
  / Analysis) as the shape for a research memo; that is the shape of a
  *fiscal note*, which is a different document with a legal purpose
