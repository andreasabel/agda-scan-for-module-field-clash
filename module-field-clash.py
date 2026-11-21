#!/usr/bin/env python3
"""Find Agda record fields with the same name as a module declaration."""

import argparse
from dataclasses import dataclass, field
import os
import re
import sys


# File discovery and literate preprocessing adapted from named-where.py.
LITERATE_EXTS = ['.lagda', '.lagda.rst', '.lagda.tex', '.lagda.md',
                 '.lagda.org', '.lagda.tree', '.lagda.typ']
AGDA_EXTS = ['.agda'] + LITERATE_EXTS

SKIP_DIRS = {'.git', '.svn', '.hg', '_build', 'dist-newstyle', 'MAlonzo',
             '.stack-work', 'node_modules'}


def agda_kind(path):
    """Return the recognised Agda extension of PATH, or None."""
    base = os.path.basename(path)
    # Longest extension first, so that `.lagda.md` beats `.lagda`.
    for ext in sorted(AGDA_EXTS, key=len, reverse=True):
        if base.endswith(ext) and len(base) > len(ext):
            return ext
    return None


def find_files(root, *, onerror=None):
    """Yield Agda files under ROOT (a file or a directory)."""
    if os.path.isfile(root):
        if agda_kind(root):
            yield root
        return
    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in SKIP_DIRS and not d.startswith('.'))
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if agda_kind(path):
                yield path


# ---------------------------------------------------------------------------
# Literate preprocessing: blank out everything that is not Agda code,
# preserving line and column numbers (cf. Agda's `illiterate`).
# ---------------------------------------------------------------------------

def _bleach(line):
    return ''.join(c if c == '\n' else ' ' for c in line)


def _illiterate_generic(lines, is_begin, is_end):
    out, in_code = [], False
    for line in lines:
        if in_code:
            if is_end(line):
                in_code = False
                out.append(_bleach(line))
            else:
                out.append(line)
        else:
            if is_begin(line):
                in_code = True
            out.append(_bleach(line))
    return out


_MD_AGDA = re.compile(r'```(?:agda)?\s*$')
_MD_OTHER = re.compile(r'^\s*```[a-zA-Z0-9-]+\s*$')
_MD_END = re.compile(r'^\s*```\s*$')
_TEX_BEGIN = re.compile(r'^(?:[^\\%]|\\.)*\\begin\{code\}')
_TREE_BEGIN = re.compile(r'^(?:[^\\%]|\\.)*\\agda\{')
_ORG_BEGIN = re.compile(r'#\+begin_src agda2(?:\s|$)', re.I)
_ORG_END = re.compile(r'^\s*#\+end_src(?:\s|$)', re.I)


def _illiterate_md(lines):
    """Markdown/Typst: ``` and ```agda blocks are code, other tags are not."""
    out, in_code, in_other = [], False, False
    for line in lines:
        if in_code:
            if _MD_END.match(line):
                in_code = False
                out.append(_bleach(line))
            else:
                out.append(line)
        elif in_other:
            if _MD_END.match(line):
                in_other = False
            out.append(_bleach(line))
        else:
            if _MD_AGDA.search(line):
                in_code = True
            elif _MD_OTHER.match(line):
                in_other = True
            out.append(_bleach(line))
    return out


_RST_CODE = re.compile(r'^(.*)::\s*$')
_RST_COMMENT = re.compile(r'^\s*\.\.(\s.*)?$')


def _illiterate_rst(lines):
    """reStructuredText: an indented block after a line ending in `::`."""
    out = []
    state = 'text'     # 'text' | 'seek' (looking for the indent) | 'code'
    indent = ''
    for line in lines:
        if state == 'code':
            if line.strip() == '' or line.startswith(indent):
                out.append(line)
                continue
            state = 'text'
        if state == 'seek':
            if line.strip() == '':
                out.append(_bleach(line))
                continue
            ws = re.match(r'[ \t]*', line).group(0)
            if ws:
                indent, state = ws, 'code'
                out.append(line)
                continue
            state = 'text'
        # state == 'text'
        out.append(_bleach(line))
        if not _RST_COMMENT.match(line) and _RST_CODE.match(line):
            state = 'seek'
    return out


def illiterate(text, ext):
    """Blank out non-code parts of a literate file, keeping positions."""
    if ext == '.agda':
        return text
    lines = text.splitlines(keepends=True)
    if ext in ('.lagda', '.lagda.tex'):
        return ''.join(_illiterate_generic(
            lines,
            _TEX_BEGIN.match,
            lambda l: re.match(r'^[ \t]*\\end\{code\}', l)))
    if ext in ('.lagda.md', '.lagda.typ'):
        return ''.join(_illiterate_md(lines))
    if ext == '.lagda.rst':
        return ''.join(_illiterate_rst(lines))
    if ext == '.lagda.org':
        return ''.join(_illiterate_generic(
            lines,
            _ORG_BEGIN.search,
            _ORG_END.match))
    if ext == '.lagda.tree':
        return ''.join(_illiterate_generic(
            lines,
            _TREE_BEGIN.match,
            lambda l: re.match(r'^[ \t]*\}', l)))
    return text


# Tokenization

_WORD = r'[^\s(){};@."⦃⦄⦇⦈⦉⦊]+'
_LEXEME = re.compile(
    r"""[^\S\n]+|\n|\{-#|\{-|\{!|--[^\n]*|"(?:\\[^\n]|[^"\\\n])*"?"""
    r"""|'(?:\\(?:[a-zA-Z0-9]+|[^\n])|[^'\\\n])'|\.\.+|[(){};@.⦃⦄⦇⦈⦉⦊]|"""
    rf'{_WORD}(?:\.{_WORD})*'
)
_PRAGMA_END = re.compile(r'"(?:\\.|[^"\\])*"|\{-#|#-}', re.S)
_FOREIGN_PRAGMA = re.compile(r'\s*(?:COMPILE|FOREIGN)\b')
_FOREIGN_PRAGMA_END = re.compile(r'\{-#|#-}')
_COMMENT_EDGE = re.compile(r'\{-|-\}')
_HOLE_EDGE = re.compile(r'\{!|!\}')
_DELIMITERS = {'(': ')', '{': '}', '⦃': '⦄', '⦇': '⦈', '⦉': '⦊'}
_LAYOUT = {
    'abstract', 'do', 'field', 'instance', 'let', 'macro', 'mutual',
    'opaque', 'postulate', 'primitive', 'private', 'variable', 'where',
}
_MODIFIERS = _LAYOUT - {'do', 'field', 'let', 'where'}
_NON_NAMES = _LAYOUT | {
    '=', ':', '→', '->', '.', '..', '...', ',', '_', '@', '|', 'in', 'open',
    'module', 'record', 'data', 'overlap', 'constructor', 'using', 'hiding',
    'renaming', '"', '{-#',
}


@dataclass(frozen=True)
class Token:
    text: str
    line: int
    col: int


def skip_nested(source, start, edges, opening):
    depth = 1
    for edge in edges.finditer(source, start):
        if edge[0] == opening:
            depth += 1
        elif not edge[0].startswith('"'):
            depth -= 1
            if depth == 0:
                return edge.end()
    return len(source)


def tokenize(source):
    start = line_start = 0
    line = 1
    while start < len(source):
        match = _LEXEME.match(source, start)
        word = match[0]
        end = match.end()
        if word == '{-':
            end = skip_nested(source, end, _COMMENT_EDGE, '{-')
        elif word == '{!':
            end = skip_nested(source, end, _HOLE_EDGE, '{!')
            yield Token('"', line, start - line_start + 1)
        elif word == '{-#':
            edges = _FOREIGN_PRAGMA_END if _FOREIGN_PRAGMA.match(source, end) else _PRAGMA_END
            end = skip_nested(source, end, edges, '{-#')
            yield Token('{-#', line, start - line_start + 1)
        elif not word.isspace() and not word.startswith('--'):
            if word.startswith('"') or (word.startswith("'") and word.endswith("'")):
                word = '"'
            yield Token(word, line, start - line_start + 1)
        newlines = source.count('\n', start, end)
        if newlines:
            line += newlines
            line_start = source.rfind('\n', start, end) + 1
        start = end


@dataclass
class Block:
    keyword: str
    column: int
    tentative: bool = False
    explicit: bool = False
    recovered: bool = False
    declarations: list = field(default_factory=list)
    new_declaration: bool = True

    def append(self, item):
        if self.new_declaration:
            self.declarations.append([])
            self.new_declaration = False
        self.declarations[-1].append(item)


@dataclass
class Group:
    closing: str
    items: list = field(default_factory=list)

    def append(self, item):
        self.items.append(item)


def declaration_blocks(tokens):
    """Group delimiters and layout blocks, retaining declaration boundaries."""
    root = Block('file', 0)
    stack = [root]
    pending = None
    previous_line = 0
    after_semi = False
    for token in tokens:
        word, line, column = token.text, token.line, token.col
        new_line = line != previous_line
        previous_line = line
        if root.column == 0:
            root.column = column

        if new_line and pending is None:
            for frame in reversed(stack):
                if not isinstance(frame, Block) or not frame.tentative:
                    break
                frame.tentative = False

        if pending:
            keyword, pending = pending, None
            if word == '{' and keyword != 'field':
                block = Block(keyword, 0, explicit=True)
                stack[-1].append(block)
                stack.append(block)
                after_semi = False
                continue
            # A delimiter or explicit block isolates its contents from outer
            # indentation. Inline layout nested in inline layout can be tentative.
            baseline = 0
            for frame in reversed(stack):
                if isinstance(frame, Group) or frame.explicit:
                    break
                if not frame.tentative:
                    baseline = frame.column
                    break
            block = Block(keyword, column, tentative=not new_line)
            stack[-1].append(block)
            if column > baseline and word not in (')', '}', '⦄', ';', 'in'):
                stack.append(block)
                new_line = False
                if not block.tentative:
                    limit = column
                    for frame in reversed(stack[:-1]):
                        if not isinstance(frame, Block) or not frame.tentative or frame.column >= limit:
                            break
                        frame.tentative = False
                        limit = frame.column

        if word == 'in':
            for index in range(len(stack) - 1, 0, -1):
                frame = stack[index]
                if isinstance(frame, Group):
                    break
                if frame.keyword == 'let':
                    del stack[index:]
                    new_line = False
                    break

        if word in _DELIMITERS.values():
            for index in range(len(stack) - 1, 0, -1):
                frame = stack[index]
                if isinstance(frame, Group):
                    if frame.closing == word:
                        del stack[index:]
                        break
                elif frame.explicit and word == '}':
                    del stack[index:]
                    break
            after_semi = False
            continue

        if new_line:
            while len(stack) > 1:
                frame = stack[-1]
                if not isinstance(frame, Block) or frame.explicit or column >= frame.column:
                    break
                stack.pop()
            if stack[-1] is root and column < root.column:
                # Literate chunks sometimes change their baseline indentation.
                root.column = column
            frame = stack[-1]
            if isinstance(frame, Block) and not frame.explicit and column == frame.column:
                frame.new_declaration = True

        # Recover common compact spellings where a semicolon followed by a
        # module/field declaration terminates an inline field block.
        if after_semi and word in {'field', 'module', 'open', 'record'}:
            while len(stack) > 1 and isinstance(stack[-1], Block) and stack[-1].keyword == 'field':
                stack.pop().recovered = True
                if isinstance(stack[-1], Block):
                    stack[-1].new_declaration = True
        after_semi = word == ';'

        frame = stack[-1]
        if word == ';' and isinstance(frame, Block):
            frame.new_declaration = True
        elif word in _DELIMITERS:
            group = Group(_DELIMITERS[word])
            frame.append(group)
            stack.append(group)
        else:
            frame.append(token)
            if word in _LAYOUT:
                pending = word
    if pending:
        stack[-1].append(Block(pending, 0))
    return root


# Record and module declarations

@dataclass(frozen=True)
class Module:
    name: str
    location: Token
    kind: str
    possible: bool


@dataclass(frozen=True)
class Clash:
    record: str
    module: Module
    fields: tuple
    possible: bool


@dataclass
class Record:
    name: str
    fields: dict = field(default_factory=dict)
    modules: list = field(default_factory=list)


def spelling(item):
    return item.text if isinstance(item, Token) else ''


def after_attributes(items, start):
    while start < len(items) and spelling(items[start]) == '@':
        start += 2
    return start


def field_names(block):
    for declaration in block.declarations:
        if spelling(declaration[0]) == 'instance':
            if len(declaration) > 1 and isinstance(declaration[1], Block):
                yield from field_names(declaration[1])
        elif len(declaration) == 1 and isinstance(declaration[0], Group) and declaration[0].closing == '}':
            # Recover braced field blocks without confusing them with a hidden
            # field binder, whose type annotation follows the closing brace.
            start = 0
            items = declaration[0].items
            for end, item in enumerate(items + [None]):
                if item is None or spelling(item) == ';':
                    yield from signature_names(items[start:end], possible=True)
                    start = end + 1
        else:
            yield from signature_names(declaration, possible=block.recovered)


def signature_names(items, *, possible):
    for end, item in enumerate(items):
        if spelling(item) == ':':
            start = 1 if spelling(items[0]) == 'overlap' else 0
            for token in binding_names(items[start:end]):
                yield token, possible
            break


def binding_names(items):
    index = 0
    while index < len(items):
        index = after_attributes(items, index)
        if index >= len(items):
            break
        item = items[index]
        if isinstance(item, Group) and item.closing in {'}', '⦄'}:
            yield from binding_names(item.items)
        elif isinstance(item, Token) and item.text not in _NON_NAMES:
            yield item
        index += 1


def module_header(items, start):
    index = after_attributes(items, start + 1)
    if index >= len(items) or not isinstance(items[index], Token):
        return None
    name = items[index]
    if (name.text in _NON_NAMES and name.text != '_') or '.' in name.text:
        return None
    for i in range(index + 1, len(items)):
        word = spelling(items[i])
        if word == '=':
            return name.text, 'application', None
        if word == 'where':
            body = items[i + 1] if i + 1 < len(items) else None
            return name.text, 'definition', body
        if word in {'.', ':', 'module', 'record'}:
            break
    return None


def visit(block, record, hits, *, possible=False, fields_in_scope=True):
    possible = possible or block.explicit
    for declaration in block.declarations:
        items = declaration
        while items and spelling(items[0]) == '{-#':
            items = items[1:]
        if not items:
            continue
        head = spelling(items[0])
        nested = [item for item in items if isinstance(item, Block)]

        if head == 'record':
            name_at = after_attributes(items, 1)
            bodies = [body for body in nested if body.keyword == 'where']
            if name_at < len(items) and spelling(items[name_at]) and bodies:
                scan_record(spelling(items[name_at]), bodies[-1], hits)
            continue

        if head == 'field' and record is not None:
            if fields_in_scope:
                for body in nested:
                    if body.keyword == 'field':
                        for name, recovered in field_names(body):
                            record.fields.setdefault(name.text, []).append((name, possible or recovered))
            continue

        module_at = 0 if head == 'module' else 1 if head == 'open' else None
        named_where = False
        if module_at is None and head not in _MODIFIERS:
            # A named where clause binds its module in the enclosing scope.
            for index, item in enumerate(items[:-2]):
                if spelling(item) != 'module':
                    continue
                header = module_header(items, index)
                if header and header[1] == 'definition':
                    module_at = index
                    named_where = True
                    break
        if module_at is not None and module_at < len(items) and spelling(items[module_at]) == 'module':
            header = module_header(items, module_at)
            if header:
                name, kind, body = header
                if named_where:
                    kind = 'named where module'
                else:
                    kind = f'module {kind}'
                if record is not None and name != '_' and (
                    not named_where or isinstance(body, Block) and body.declarations
                ):
                    record.modules.append(Module(name, items[module_at], kind, possible))
                if isinstance(body, Block):
                    # Anonymous module bodies can expose members via an implicit
                    # open. A named body has its own namespace.
                    visit(body, record if name == '_' else None, hits,
                          possible=True, fields_in_scope=False)
                continue

        for body in nested:
            if body.keyword in _MODIFIERS:
                visit(body, record, hits, possible=possible, fields_in_scope=fields_in_scope)
            elif body.keyword == 'where':
                # A clause's where block and a data body have separate scopes.
                # If the header is unfamiliar, retain the possible record scope.
                local = head == 'data' or any(
                    spelling(item) in {'=', 'with', 'rewrite', '|', 'λ', '\\'}
                    for item in items
                )
                visit(body, None if local else record, hits, possible=True,
                      fields_in_scope=fields_in_scope)


def scan_record(name, body, hits):
    record = Record(name)
    visit(body, record, hits)
    for module in record.modules:
        fields = record.fields.get(module.name)
        if fields:
            hits.append(Clash(name, module, tuple(token for token, _ in fields),
                              module.possible or all(uncertain for _, uncertain in fields)))


def scan_file(path):
    with open(path, encoding='utf-8', errors='replace') as source:
        code = illiterate(source.read(), agda_kind(path))
    hits = []
    visit(declaration_blocks(tokenize(code)), None, hits)
    return sorted(hits, key=lambda hit: (hit.module.location.line, hit.module.location.col))


def location(path, token, column):
    result = f'{path}:{token.line}'
    return f'{result}:{token.col}' if column else result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='*', metavar='FILE_OR_DIR',
                        help='where to search (default: the current directory)')
    parser.add_argument('-c', '--column', action='store_true', help='include columns in locations')
    parser.add_argument('-q', '--quiet', action='store_true', help='print only the summary')
    parser.add_argument('-f', '--files', action='store_true', help='list files without scanning them')
    args = parser.parse_args(argv)
    files = {}
    discovery_errors = []
    for root in args.paths or ['.']:
        if not os.path.exists(root):
            parser.error(f'{root}: no such file or directory')
        for path in find_files(root, onerror=discovery_errors.append):
            files.setdefault(os.path.realpath(path), path)
    for error in discovery_errors:
        print(error, file=sys.stderr)
    if args.files:
        for path in files.values():
            print(path)
        return int(bool(discovery_errors))

    scanned = clashes = possible = 0
    errors = len(discovery_errors)
    for path in files.values():
        try:
            hits = scan_file(path)
        except OSError as error:
            print(error, file=sys.stderr)
            errors += 1
            continue
        scanned += 1
        for hit in hits:
            possible += hit.possible
            clashes += not hit.possible
            if not args.quiet:
                module = hit.module
                reason = 'possible clash' if hit.possible else 'clash'
                fields = ', '.join(location(path, token, args.column) for token in hit.fields)
                print(f'{location(path, module.location, args.column)}: {reason}: '
                      f'{hit.record}.{module.name} ({module.kind}, field at {fields})')
    print(f'Scanned {scanned} Agda files. Found {clashes} clashes and {possible} possible clashes.')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
