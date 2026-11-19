"""
Passage retrieval over 10-K text, and the year-over-year disclosure diff.

Ranking is BM25 on words — no embedding model, no vector store. One 10-K
section is a few hundred passages, risk-factor questions share vocabulary
with the filing ("supply chain", "tariffs", "cybersecurity"), and a lexical
ranker is deterministic, offline and small enough to read.

The diff answers "what changed in this section between two years": each
passage is matched to its closest passage in the other year by word overlap,
and is unchanged, revised, added or removed depending on how close that is.
"""
import math
import re
from collections import Counter

from . import edgar, filings

K1, B = 1.5, 0.75                 # standard BM25 constants
SAME, REVISED = 0.9, 0.5          # word-overlap thresholds for the diff


def tokenize(text):
    # Crude plural stripping so "suppliers" finds "supplier".
    return [w[:-1] if len(w) > 3 and w.endswith('s') else w
            for w in re.findall(r'[a-z0-9]+', text.lower())]


def rank(query, texts):
    """Indexes of `texts` that share a word with `query`, best match first."""
    docs = [Counter(tokenize(t)) for t in texts]
    average = sum(sum(d.values()) for d in docs) / max(len(docs), 1)
    scores = Counter()
    for term in set(tokenize(query)):
        containing = sum(term in d for d in docs)
        idf = math.log(1 + (len(docs) - containing + 0.5) / (containing + 0.5))
        for i, d in enumerate(docs):
            if term in d:
                norm = K1 * (1 - B + B * sum(d.values()) / average)
                scores[i] += idf * d[term] * (K1 + 1) / (d[term] + norm)
    return sorted(scores, key=lambda i: (-scores[i], i))


def _header(filing):
    return {k: filing[k] for k in ('fiscal_year', 'period_end', 'filed', 'source')}


def _known_section(item):
    if item not in filings.SECTIONS:
        raise edgar.EdgarError(f'unknown section {item!r}; choose from {sorted(filings.SECTIONS)}')
    return item


def search_filing(ticker, year, query, section=None, limit=5):
    """The passages of one 10-K that best match `query`."""
    filing = filings.load(ticker, year)
    if section:
        pool = {_known_section(section): filings.section(filing, section)}
    else:
        pool = filing['sections']
    candidates = [{**p, 'section': filings.SECTIONS[item]} for item, found in pool.items() for p in found]
    hits = [candidates[i] for i in rank(query, [p['text'] for p in candidates])[:limit]]
    return {'ticker': filing['ticker'], 'company': filing['company'], **_header(filing),
            'query': query, 'passages': hits}


def _overlap(a, b):
    return len(a & b) / len(a | b) if a | b else 1.0


def diff(old, new):
    """Sort passages into {added, removed, revised: [(new, old)], unchanged}."""
    old_words = [set(tokenize(p['text'])) for p in old]
    new_words = [set(tokenize(p['text'])) for p in new]

    def closest(words, others):
        scores = [_overlap(words, o) for o in others]
        best = max(range(len(scores)), key=scores.__getitem__, default=None)
        return (scores[best], best) if scores else (0.0, None)

    result = {'added': [], 'removed': [], 'revised': [], 'unchanged': 0}
    for passage, words in zip(new, new_words):
        score, match = closest(words, old_words)
        if score >= SAME:
            result['unchanged'] += 1
        elif score >= REVISED:
            result['revised'].append((passage, old[match]))
        else:
            result['added'].append(passage)
    result['removed'] = [p for p, words in zip(old, old_words)
                         if closest(words, new_words)[0] < REVISED]
    return result


def compare_filings(ticker, section, from_year, to_year, query=None, limit=5):
    """What changed in one section between two fiscal years' 10-Ks. Counts
    cover the whole section; the passages listed are the `limit` best matches
    for `query`, or the first `limit` in filing order."""
    old, new = filings.load(ticker, from_year), filings.load(ticker, to_year)
    changes = diff(filings.section(old, _known_section(section)), filings.section(new, section))

    def top(items, text_of):
        order = rank(query, [text_of(x) for x in items]) if query else range(len(items))
        return [items[i] for i in list(order)[:limit]]

    return {
        'ticker': new['ticker'], 'company': new['company'], 'section': filings.SECTIONS[section],
        'from': _header(old), 'to': _header(new), 'query': query,
        'unchanged_count': changes['unchanged'],
        'added_count': len(changes['added']),
        'removed_count': len(changes['removed']),
        'revised_count': len(changes['revised']),
        'added': top(changes['added'], lambda p: p['text']),
        'removed': top(changes['removed'], lambda p: p['text']),
        'revised': [{'new': n, 'old': o}
                    for n, o in top(changes['revised'], lambda pair: pair[0]['text'])],
    }
