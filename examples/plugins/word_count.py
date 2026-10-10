# Example NOVA plugin (sandboxed).  Copy it into the plugins folder to try it:
#     ~/Library/Application Support/NOVA/plugins/
# NOVA asks before loading it the first time, and again whenever the file changes.
#
# MANIFEST must be a plain dictionary (NOVA reads it WITHOUT running this file).
# "permissions" lists what the plugin may do; leave it empty for pure calculations:
#     "network"      use the internet
#     "read_files"   read Documents, Desktop, Downloads, Pictures, Music, Movies
#     "write_files"  create / change files in Documents, Desktop, Downloads
# A plugin can always read and write its own private folder (the current directory when it runs).
MANIFEST = {
    "name": "Word count",
    "description": "Counts words, characters and lines in a piece of text.",
    "permissions": [],
}


def count_words(text: str) -> str:
    words = text.split()
    return f"{len(words)} words, {len(text)} characters, {text.count(chr(10)) + 1} lines"


# One entry per tool the AI can call.  "params" uses JSON-schema property definitions.
TOOLS = [{
    "name": "count_words",
    "description": "Count the words, characters and lines in a text.",
    "params": {"text": {"type": "string", "description": "the text to measure"}},
    "required": ["text"],
    "function": count_words,
}]
