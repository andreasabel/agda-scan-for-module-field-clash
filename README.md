# Agda module–field clashes

This scanner finds Agda record fields that share a name with a module declared in the same record. It reports module definitions, module applications, and applications written with `open module`. A nonempty named `where` module also counts when its name is bound in the record. For example, `R.foo` clashes with a field of the same name in `R`, while a module declared as `R.M.foo` has a separate namespace.

## Usage

Requires Python 3.7 or later. Run the executable with one or more files or directories.

```sh
./module-field-clash.py --column "$HOME/bin/src/agda"
```

With no paths, the scan starts in the current directory. It searches directories recursively for `.agda` and `.lagda[.md|.rst|.tex|.org|.tree|.typ]` sources and skips hidden directories and known build directories. `--files` lists the selected files, `--quiet` shows only the summary, and `--column` adds columns to the module and field locations. Matches use editor-friendly `FILE:LINE[:COLUMN]` locations and include the record and the corresponding field location. The exit status indicates whether the scan ran successfully, so a completed scan with matches still exits successfully.

## Scope and limitations

The scanner uses source layout and declaration syntax and works without an Agda installation or project dependencies. It skips comments, including nested block comments, and treats contents of pragmas, literals, holes, and literate prose as opaque. It collects fields and modules across the whole record body, so it also catches modules declared before their corresponding fields.

It reports a **possible clash** when a matching name is found through an anonymous module's implicit open or when recovering uncertain declaration syntax. The scan compares names introduced in the source file. Resolving names brought into scope by imports, explicit opens, or renaming directives requires Agda's scope checker. The clashes reported here are same-name field/module pairs, which Agda can currently accept.

The file discovery and literate preprocessing are adapted from `agda-scan-for-named-where-modules`. Run the regression tests with `python3 test/test_scanner.py`. The [survey](survey.txt) lists the matches and file counts from the scan of `~/bin/src/agda`.
