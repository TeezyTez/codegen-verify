"""Small statement grammar layered over the existing lexical/boundary guard.

This is deliberately not a general Dafny parser. In particular, body-less loops
and aggregate statements must not become trusted assumptions during verification.
Expressions are token-restricted, then type-checked by Dafny, never evaluated here.
"""
import re

from generation.task import body_check
from repair.task import BoundaryError

TOKEN = re.compile(r'\s+|[A-Za-z_][A-Za-z0-9_]*|[0-9]+|<==>|==>|<=|>=|==|!=|&&|\|\||:=|::|[{}()\[\];,:+*/%<>=!|\-]')
CONTROL = {'var', 'if', 'else', 'while', 'invariant', 'decreases', 'assert', 'return'}
FORBIDDEN = {'ghost', 'opaque', 'reveal', 'hide', 'modify', 'for', 'calc', 'by',
             'break', 'continue', 'match', 'case', 'label', 'export', 'static',
             'constructor', 'iterator', 'twostate', 'refines', 'abstract', 'least', 'greatest'}


def validate_body(text):
    body_check(text)  # existing declaration, bypass, ASCII and brace checks
    tokens, position = [], 0
    for match in TOKEN.finditer(text):
        if match.start() != position:
            raise BoundaryError('unsupported lexical token')
        position = match.end()
        if not match[0].isspace():
            tokens.append(match[0])
    if position != len(text) or any(t in FORBIDDEN for t in tokens):
        raise BoundaryError('outside statement profile')
    Parser(tokens).parse()


class Parser:
    def __init__(self, tokens):
        self.tokens, self.i = tokens, 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self, expected=None):
        token = self.peek()
        if token is None or (expected is not None and token != expected):
            raise BoundaryError('incomplete or unsupported statement')
        self.i += 1
        return token

    def expression(self, stops):
        start, stack = self.i, []
        while self.peek() is not None:
            token = self.peek()
            if not stack and token in stops:
                break
            if token in CONTROL or token in {'{', '}', ';', ':='}:
                raise BoundaryError('statement or block inside expression')
            if token in {'(', '['}:
                stack.append(token)
            elif token in {')', ']'}:
                if not stack or stack.pop() != {')':'(', ']':'['}[token]:
                    raise BoundaryError('unbalanced expression')
            self.i += 1
        if stack or self.i == start:
            raise BoundaryError('missing or unbalanced expression')

    def block(self):
        self.take('{')
        self.parse(nested=True)
        self.take('}')

    def parse(self, nested=False):
        while self.peek() is not None and self.peek() != '}':
            token = self.peek()
            if token == 'while':
                self.take()
                self.expression({'invariant', 'decreases', '{'})
                while self.peek() in {'invariant', 'decreases'}:
                    clause = self.take()
                    if clause == 'decreases' and self.peek() == '*':
                        raise BoundaryError('termination bypass')
                    self.expression({'invariant', 'decreases', '{'})
                self.block()  # never permit body-less while ... ;
            elif token == 'if':
                self.take()
                self.expression({'{'})
                self.block()
                if self.peek() == 'else':
                    self.take()
                    self.block()  # explicit blocks only; nested if fits in block
            elif token in {'assert', 'return'}:
                self.take()
                if token == 'assert' or self.peek() != ';':
                    self.expression({';'})
                self.take(';')
            elif token == '{':
                self.block()
            else:
                if token == 'var':
                    self.take()
                # Initialized local declaration or assignment; no standalone
                # forall, method calls, havoc, proof blocks, or uninitialized var.
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', self.peek() or ''):
                    raise BoundaryError('expected assignment')
                self.expression({':='})
                self.take(':=')
                self.expression({';'})
                self.take(';')
        if not nested and self.peek() is not None:
            raise BoundaryError('escaped implementation region')
