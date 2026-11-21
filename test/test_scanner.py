import subprocess
import tempfile
from pathlib import Path
import unittest


SCANNER = Path(__file__).resolve().parents[1] / 'module-field-clash.py'


class ScannerTest(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)

    def write(self, name, code):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding='utf-8')
        return name

    def run_scanner(self, *args):
        return subprocess.run(
            [str(SCANNER), *args], cwd=self.root, encoding='utf-8',
            check=True, capture_output=True,
        ).stdout.splitlines()

    def test_record_scopes(self):
        path = self.write('Cases.agda', """record R where
  field foo : Set
  field
    bar : Set
  module foo where
  module bar = foo

record S where
  field quux : Set
  module M where
    module quux where
  record T where
    field quux : Set
    module quux where
  module quux′ where
  auxiliary : Set₁
  auxiliary = let module quux = M in Set
  helper : Set₁
  helper = Set
    where
      module quux where
  open import quux

module quux where
record Other where
  field other : Set
  module quux where
""")
        self.assertEqual(self.run_scanner('-c', path), [
            'Cases.agda:5:3: clash: R.foo (module definition, field at Cases.agda:2:9)',
            'Cases.agda:6:3: clash: R.bar (module application, field at Cases.agda:4:5)',
            'Cases.agda:14:5: clash: T.quux (module definition, field at Cases.agda:13:11)',
            'Scanned 1 Agda files. Found 3 clashes and 0 possible clashes.',
        ])

    def test_field_and_module_forms(self):
        path = self.write('Forms.agda', """module Source where
  X = Set
record R (A : Set)
         : Set₁ where
  private module foo
            (B : Set) {x : B}
            where
            n = A
  open module bar = Source
  module baz = Source
  field
    @0 {foo} bar .baz : Set
    overlap ⦃ inst ⦄ : Set
    instance
      inst′ : Set
    semicolon : Set; afterSemi : Set
  module inst where
  module inst′ where
  module afterSemi where
  module @0 semicolon
    = Source

record Split : Set₁
record Split where
  field f : Set
  module f where
""")
        lines = self.run_scanner(path)
        self.assertEqual([line.split('clash: ')[1].split()[0] for line in lines[:-1]], [
            'R.foo', 'R.bar', 'R.baz', 'R.inst', 'R.inst′', 'R.afterSemi',
            'R.semicolon', 'Split.f',
        ])

    def test_comments_and_other_lexical_decoys(self):
        path = self.write('Comments.agda', """record R where
  -- field decoy : Set
  module decoy where
  field ghost : Set
  {- outer
     {- module ghost where -}
     module ghost = No
  -}
  postulate
    Whatever : Set
  ignored = "module ghost where {-"
  hole = {! { module ghost where !}
  {-# FOREIGN GHC "unpaired quote #-}
  field _--_ : Set
  module{- comment -} _--_ where
""")
        self.assertEqual(self.run_scanner('-c', path), [
            'Comments.agda:15:3: clash: R._--_ (module definition, field at Comments.agda:14:9)',
            'Scanned 1 Agda files. Found 1 clashes and 0 possible clashes.',
        ])

    def test_named_where_and_anonymous_module(self):
        path = self.write('Where.agda', """record R where
  field f g h : Set
  module _ where
    module f where
      A = Set
    module M where
      module h where
  rhs = Set module g where
    A = Set
  empty = Set module h where
""")
        self.assertEqual(self.run_scanner(path), [
            'Where.agda:4: possible clash: R.f (module definition, field at Where.agda:2)',
            'Where.agda:8: clash: R.g (named where module, field at Where.agda:2)',
            'Scanned 1 Agda files. Found 1 clashes and 1 possible clashes.',
        ])

    def test_recovery_keeps_plausible_matches(self):
        path = self.write('Recovery.agda', """record Brace where { field { f : Set; g : Set }; module f where {}; module g = M }
record Semi where field f : Set; module f where
record Unknown where
  field f : Set
  unfamiliar where
    module f where
""")
        lines = self.run_scanner(path)
        self.assertEqual([line.split('possible clash: ')[1].split()[0] for line in lines[:-1]], [
            'Brace.f', 'Brace.g', 'Semi.f', 'Unknown.f',
        ])

    def test_literate_files_and_discovery(self):
        code = '  record R where\n    field f : Set\n    module f where\n'
        patterns = {
            'A.lagda': ('\\begin{code}', '\\end{code}'),
            'B.lagda.md': ('```agda', '```'),
            'C.lagda.org': ('#+BEGIN_SRC agda2', '#+END_SRC'),
            'D.lagda.rst': ('::', ''),
            'E.lagda.tex': ('\\begin{code}', '\\end{code}'),
            'F.lagda.tree': ('\\agda{', '}'),
            'G.lagda.typ': ('```', '```'),
        }
        for name, (start, end) in patterns.items():
            self.write(name, 'record Decoy where\n  field p : Set\n  module p where\n'
                       + f'{start}\n{code}{end}\n')
        self.write('.hidden/H.agda', code)
        self.write('_build/H.agda', code)
        self.write('H.agdai', code)
        self.assertEqual(self.run_scanner('--files', '.', 'A.lagda'), [
            f'./{name}' for name in patterns
        ])
        lines = self.run_scanner('-c')
        self.assertEqual(lines[:-1], [
            f'./{name}:7:5: clash: R.f (module definition, field at ./{name}:6:11)'
            for name in patterns
        ])
        self.assertEqual(self.run_scanner('-q'), [
            'Scanned 7 Agda files. Found 7 clashes and 0 possible clashes.',
        ])

    def test_inactive_literate_blocks(self):
        code = 'record Decoy where\n  field f : Set\n  module f where\n'
        for name, start, end in [
            ('Comment.lagda', '% \\begin{code}', '\\end{code}'),
            ('Comment.lagda.tree', '% \\agda{', '}'),
            ('Language.lagda.md', '```haskell', '```'),
            ('Language.lagda.org', '#+begin_src agda2-other', '#+end_src'),
        ]:
            self.write(name, f'{start}\n{code}{end}\n')
        self.assertEqual(self.run_scanner(), [
            'Scanned 4 Agda files. Found 0 clashes and 0 possible clashes.',
        ])


if __name__ == '__main__':
    unittest.main()
