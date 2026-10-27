# Developer docs

`build-docs.cmd` builds the developer docs site into `CvGameCoreSource\BuildTemp\docs`. Beside each page is a Markdown copy, for coding models to search.

Three hand-written files in `docs\` add to it: `docs\task-guide.md` is the front page's guide, `docs\class-summaries.md` holds the class summaries, and `docs\function-notes.md` holds notes on single functions, one `## name` section per function, shown on that function's page. In all three, `[[name]]` links to a function, class or hand-placed hook by name, and `[[name|text]]` shows other text for the link; the build stops if a name does not match exactly one of them.
