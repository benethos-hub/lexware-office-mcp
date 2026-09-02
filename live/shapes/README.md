# API response shapes

One file per run of [`../api_shape.py`](../api_shape.py), named for the moment
it was taken. Each records the shape of every readable endpoint: field names,
their JSON types, and the values of a short list of closed vocabularies.

## Why these files exist

The offline suite mocks HTTP completely, so it stays green through any change
in Lexware's field names or response shapes. `smoke.py` closes part of that
gap by asking whether the calls still work. It cannot close the rest, because
this server drops every null and empty field on the way to the client: a field
that disappeared upstream looks identical downstream, and a field that
appeared is invisible by construction.

So the answers are recorded before any of that happens, and the check for
drift becomes a `diff` between two files rather than a reading of dated prose
in [SPECS.md](../../SPECS.md) section 5.

## Comparing two runs

```
git diff --no-index live/shapes/shape-<older>.txt live/shapes/shape-<newer>.txt
```

A removed line is a field the API stopped sending. An added line is a new one.
A changed line is a type or a vocabulary that moved — the last of those is how
`voucherStatus: unchecked` stopped being accepted between two Thursdays in
August 2026.

**Not every difference is drift.** These are shapes of one account, so a
difference can also mean the account changed: an optional field that no record
happened to fill, a document type nobody had created yet, a list that has
grown. Read a diff for what it says about the API, and check the account
before concluding anything.

## What may go in a file

Field names, JSON types, and the values of the closed vocabularies
`api_shape.py` names. **Nothing else** — no id, no name, no address, no
amount, no date. `../../tests/test_api_shapes.py` enforces the first half of
that mechanically and the docstring of `api_shape.py` states the rule in full.
