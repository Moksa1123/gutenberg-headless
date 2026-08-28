#!/usr/bin/env python3
"""Block markup: parse and serialize WordPress block comments, faithfully.

This is a Python port of the grammar in WP's class-wp-block-parser.php and the
serializer in blocks.php (serialize_blocks / serialize_block_attributes), so a
tree can round-trip:  markup -> parse() -> serialize() -> byte-identical markup.

A block node is a dict shaped exactly like WP_Block_Parser_Block:
    {
      "blockName":    "core/paragraph",     # None for freeform HTML between blocks
      "attrs":        {...},                # the comment JSON (never the sourced attrs)
      "innerBlocks":  [...],
      "innerHTML":    "<p>...</p>",         # concatenated own HTML
      "innerContent": ["<div>", None, "</div>"]   # None marks an inner block's slot
    }
"""
import json
import re

# The delimiter pattern from WP_Block_Parser::next_token(), translated.
TOKEN = re.compile(
    r"<!--\s+(?P<closer>/)?wp:(?P<namespace>[a-z][a-z0-9_-]*/)?(?P<name>[a-z][a-z0-9_-]*)"
    r"\s+(?P<attrs>{(?:(?!}\s+/?-->).)*?}\s+)?(?P<void>/)?-->",
    re.S,
)


def _full_name(m):
    ns = m.group("namespace") or "core/"
    return ns + m.group("name")


def _parse_attrs(m):
    raw = m.group("attrs")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid attrs JSON in {_full_name(m)}: {e}") from None


def parse(markup):
    """Parse serialized block markup into a list of block nodes.

    Freeform HTML between top-level blocks becomes {"blockName": None} nodes,
    same as parse_blocks() in PHP (whitespace-only freeform is kept there too).
    """
    output = []
    stack = []  # (node, start_of_inner_content_offset)
    offset = 0

    def add_freeform(html):
        if html:
            output.append({"blockName": None, "attrs": {}, "innerBlocks": [],
                           "innerHTML": html, "innerContent": [html]})

    def add_inner_html(parent, html):
        if html:
            parent["innerHTML"] += html
            parent["innerContent"].append(html)

    for m in TOKEN.finditer(markup):
        leading = markup[offset:m.start()]
        if stack:
            add_inner_html(stack[-1][0], leading)
        else:
            add_freeform(leading)
        offset = m.end()

        if m.group("void"):
            node = {"blockName": _full_name(m), "attrs": _parse_attrs(m),
                    "innerBlocks": [], "innerHTML": "", "innerContent": []}
            if stack:
                stack[-1][0]["innerBlocks"].append(node)
                stack[-1][0]["innerContent"].append(None)
            else:
                output.append(node)
        elif m.group("closer"):
            if not stack:
                raise ValueError(f"closer without opener: {m.group(0)!r}")
            node, _ = stack.pop()
            expected = node["blockName"]
            got = _full_name(m)
            if got != expected:
                raise ValueError(f"mismatched closer: opened {expected}, closed {got}")
            if stack:
                stack[-1][0]["innerBlocks"].append(node)
                stack[-1][0]["innerContent"].append(None)
            else:
                output.append(node)
        else:
            node = {"blockName": _full_name(m), "attrs": _parse_attrs(m),
                    "innerBlocks": [], "innerHTML": "", "innerContent": []}
            stack.append((node, offset))

    if stack:
        raise ValueError(f"unclosed block: {stack[-1][0]['blockName']}")
    add_freeform(markup[offset:])
    return output


# ---- serializer ------------------------------------------------------------

def serialize_attrs(attrs):
    """serialize_block_attributes(): JSON with the characters that could break
    an HTML comment (or get mangled by kses) escaped as unicode, and a space
    padding convention that WP's own serializer uses."""
    s = json.dumps(attrs, ensure_ascii=False, separators=(",", ":"))
    s = s.replace("--", "\\u002d\\u002d")
    s = s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    # WP also escapes the quote when it would end the comment; it escapes " as "
    # only in `--` proximity cases; the four above are what core does.
    return s


def serialize_block(node):
    if node["blockName"] is None:
        return node["innerHTML"]

    name = node["blockName"]
    short = name[5:] if name.startswith("core/") else name
    attrs = node.get("attrs") or {}
    comment_attrs = f" {serialize_attrs(attrs)}" if attrs else ""

    inner = []
    idx = 0
    for chunk in node.get("innerContent", []):
        if chunk is None:
            inner.append(serialize_block(node["innerBlocks"][idx]))
            idx += 1
        else:
            inner.append(chunk)

    if not node.get("innerBlocks") and not node.get("innerHTML") and not inner:
        return f"<!-- wp:{short}{comment_attrs} /-->"
    return f"<!-- wp:{short}{comment_attrs} -->{''.join(inner)}<!-- /wp:{short} -->"


def serialize(nodes):
    return "".join(serialize_block(n) for n in nodes)


def walk(nodes):
    """Yield every real block node, depth-first (skips freeform)."""
    for n in nodes:
        if n["blockName"] is not None:
            yield n
        yield from walk(n.get("innerBlocks", []))


if __name__ == "__main__":
    import sys
    src = sys.stdin.read() if len(sys.argv) < 2 else open(sys.argv[1], encoding="utf-8").read()
    tree = parse(src)
    json.dump(tree, sys.stdout, ensure_ascii=False, indent=1)
