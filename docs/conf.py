# conf.py — the settings file that turns this folder of Markdown into a website.
#
# Read the Docs runs a tool called Sphinx, and Sphinx will not do anything until
# it finds this file. Out of the box Sphinx only reads reStructuredText, which is
# a different markup language from Markdown. Every document we have is Markdown,
# so the important line below is the one that loads `myst_parser` — that is the
# piece that teaches Sphinx to read `.md` files at all. Without it the build
# fails and nothing publishes.
#
# The other job this file does is decide what gets published. The old handoff
# documents are still sitting in this folder while we move their content into the
# new structure, so they are excluded on purpose (see EXCLUDE below). When they
# are finally retired, delete them from that list too.

project = "Edge Athlete"
copyright = "2026, Edge Athlete"
author = "Devin Walton"

# ── what Sphinx can read ────────────────────────────────────────────────────
# myst_parser is the Markdown reader. Everything else here is standard Sphinx.
extensions = [
    "myst_parser",
    "sphinxcontrib.mermaid",   # draws the ```mermaid diagrams as pictures
    "sphinx_design",           # collapsible {dropdown} blocks
]

# Treat a ```mermaid fence as the mermaid directive rather than code to highlight.
# Without this Sphinx looks for a "mermaid" syntax highlighter, fails, and warns.
myst_fence_as_directive = ["mermaid"]

# Accept both, so a future `.rst` page would still work.
source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
}

# The page Sphinx starts from.
root_doc = "index"

# ── Markdown features we actually use ───────────────────────────────────────
# MyST keeps most extras switched off by default. These are the ones worth
# having: real tables with colons, ~~strikethrough~~, and auto-linked URLs.
myst_enable_extensions = [
    "colon_fence",      # ::: fenced blocks, easier than backticks inside tables
    "deflist",          # definition lists, used by the glossary
    "linkify",          # bare URLs become links
    "strikethrough",
    "tasklist",         # - [ ] checkboxes
]

# Give every heading an anchor so pages can deep-link into each other
# (e.g. `journal/real-time.md#why-qos-1`). Depth 3 covers ##, ###.
myst_heading_anchors = 3

# ── what NOT to publish ─────────────────────────────────────────────────────
# The underscore-prefixed files are the OLD documents. Their content is being
# moved into the new structure; until that is done they stay on disk but out of
# the site, so the build has no "document isn't in any table of contents"
# warnings. Remove these entries as each file is retired.
exclude_patterns = [
    "_build",
    # The local preview toolchain (see serve.sh) installs into docs/venv. Without
    # this, Sphinx parses every Markdown file inside every installed package.
    "venv",
    "Thumbs.db",
    ".DS_Store",
    # Still on disk, still NOT absorbed into the site. Excluded until their content
    # has a home here — see the retirement note in the repo README.
    "_HANDOFF.md",
    "_PATCH_NOTES.md",
    "_NAMING_CHANGES.md",
    # Braydon's design docs for the BLE rack agent, merged 2026-08-07.
    #
    # The ADR's REASONING now lives in journal/rack-tablet.md, rewritten in that
    # page's voice: why a host program owns the radio instead of the browser, why
    # each sensor carries its own transport so the two coexist, why sensors are
    # chosen at the rack, and why broadcasts carry a revision number rather than
    # state. These three files stay out of the build because they are working
    # design documents — formal, dense, and written for the person implementing
    # them, which is a different job from the journal's. They remain the reference
    # for exact thresholds, message shapes and the validation checklist, and the
    # journal points here for that.
    "_ADR_RACK_BLE_LIVE_WORKFLOW.md",
    "_RACK_BLE_LIVE_WORKFLOW_SPEC.md",
    "_LIVE_ROOM_INVALIDATIONS_SPEC.md",
]

# ── how it looks ────────────────────────────────────────────────────────────
# `furo` is a clean, readable theme with a working dark mode and a sidebar that
# handles nested sections well. To switch to the classic Read the Docs look,
# change this to "sphinx_rtd_theme" and swap the matching line in
# requirements.txt — nothing else needs to change.
html_theme = "furo"
html_title = "Edge Athlete — Developer Journal"

# Furo's stock palette is low contrast in dark mode — dull grey text on near-black,
# with the sidebar almost the same shade as the page. custom.css replaces it with a
# neutral grey palette with the contrast pushed up, in both modes.
html_static_path = ["_static"]
html_css_files = ["custom.css"]

# Match the syntax highlighting to the theme; without the second line code blocks
# keep a light background on a dark page.
pygments_style = "default"
pygments_dark_style = "github-dark"
