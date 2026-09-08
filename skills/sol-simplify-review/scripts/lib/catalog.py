#!/usr/bin/env python3
"""Carry a project's own review history back into its next round.

SKILL.md already asks every inventory item for a `catalog_candidate`, and already states
when one earns a standing entry: it "recurs in two independent changes or components".
Nothing collected them. Nine rounds on one PR emitted thirty-eight candidates -- including
one that said in its own words "this is the third time" -- and every round after the first
started from `PROJECT_CLASS_CATALOG_OR_NONE: none`, so the reviewer rediscovered the class
at a new site instead of sweeping it.

That is the difference between a tool that finds defects and a tool that improves by being
used. This closes it: candidates are harvested from the rounds a project has already run,
promoted by the rule the protocol already wrote down, and handed back as the next round's
project catalog.

  catalog.py <ledger-root> [--min-rounds N]

Reads every round-*/ARTIFACT.md under the ledger root; writes the catalog to stdout.
"""
import re
import sys
from pathlib import Path

CANDIDATE = re.compile(r'^- catalog_candidate:\s*(.+?)\s*$', re.M)
ITEM = re.compile(r'^### ([OGP]-\d+)\b', re.M)


def normalise(text):
    """A comparable form: quotes, backticks, emphasis and trailing prose stripped."""
    body = re.sub(r'[`*_"“”]', '', text).strip()
    # Candidates are written as "<class> -- <why it recurs>"; the class is the part before
    # the dash, and two rounds rarely explain a recurrence in the same words.
    body = re.split(r'\s+(?:--|—|–)\s+', body, maxsplit=1)[0]
    return re.sub(r'\s+', ' ', body).strip(' .').lower()


# A class recurs in substance, not in wording: nine rounds described one shape in nine
# different sentences, so counting identical text promotes nothing. The reviewer states the
# recurrence itself -- "this is the third time", "Recurrence: ..." -- and that claim is about
# rounds this host still holds, so it is checkable rather than taken on trust. Promotion by
# either basis, and the basis is printed, because a rule standing on one reviewer's sentence
# should be read as that and not as a count.
RECURRENCE = re.compile(r'\brecurs?\b|\brecurrence\b|\b(?:second|third|fourth|fifth) time\b'
                        r'|\bagain\b|\bhas now produced\b|\bkeeps? producing\b', re.I)


def harvest(root):
    """{normalised: (verbatim, {round names})} for every non-empty candidate."""
    found = {}
    for artifact in sorted(Path(root).glob('round-*/ARTIFACT.md')):
        for raw in CANDIDATE.findall(artifact.read_text(encoding='utf-8', errors='replace')):
            key = normalise(raw)
            if not key or key in {'none', 'n/a', 'not applicable'} or key.startswith('<'):
                continue
            verbatim, rounds = found.get(key, (raw.strip(), set()))
            found[key] = (verbatim, rounds | {artifact.parent.name})
    return found


def render(found, min_rounds):
    def basis(verbatim, rounds):
        if len(rounds) >= min_rounds:
            return 'raised independently in %d rounds: %s' % (len(rounds), ', '.join(sorted(rounds)))
        if RECURRENCE.search(verbatim):
            return 'the reviewer stated the recurrence itself, in %s' % ', '.join(sorted(rounds))
        return None
    standing = {k: v for k, v in found.items() if basis(*v)}
    once = {k: v for k, v in found.items() if not basis(*v)}
    out = []
    if standing:
        out.append('Standing project classes. Each is backed by recurrence across this project\'s own '
                   'rounds, which is the promotion rule this protocol states. Instantiate '
                   'each as an inventory item and sweep it as ONE class: the sweep is every site '
                   'where the class can hold, not the site that produced this round\'s symptom.\n'
                   '\nWhere a class recurred although the project had ALREADY written a rule against '
                   'it, the sweep is not whether the rule was followed -- it is where the rule does '
                   'not reach. Reported from a consumer: a repository carrying "negative control must '
                   'be able to fail" produced four more instances in one batch, and none of them was '
                   'a test. Three were re-check scripts living outside the test suite and outside the '
                   'guard set, and one was an exit-code comparison. The rule was written for tests, '
                   'and every escape was somewhere a test-shaped rule does not look. Name that gap in '
                   'the item; a rule that did not stop the recurrence is evidence about its reach, not '
                   'about the author.\n')
        for i, (_, (verbatim, rounds)) in enumerate(sorted(standing.items(), key=lambda kv: -len(kv[1][1])), 1):
            out.append('P-%02d — %s\n      (%s)\n' % (i, verbatim, basis(verbatim, rounds)))
    if once:
        out.append('\nRaised once, not yet standing. These are leads, not obligations: one isolated '
                   'mistake earns a regression test, not a standing rule.\n')
        for verbatim, rounds in sorted(once.values()):
            out.append('  - %s  [%s]\n' % (verbatim, ', '.join(sorted(rounds))))
    return ''.join(out) if out else 'none'


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    min_rounds = 2
    if '--min-rounds' in argv:
        min_rounds = int(argv[argv.index('--min-rounds') + 1])
    sys.stdout.write(render(harvest(argv[1]), min_rounds))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
