"""
10-K text: find a company's annual report for a fiscal year, pull the prose
out of its HTML, and cut it into passages the agent can search and quote.

Only three sections are kept — the ones qualitative questions are about:
  1   Business
  1A  Risk Factors
  7   Management's Discussion and Analysis

Text is evidence for what a company SAID. Financial figures still come from
get_financials: tables are dropped here on purpose, and the number guardrail
does not accept a number just because it appears in a passage.

Fiscal year follows edgar.py: the calendar year the report period ends in.
The parsed filing is cached, not the multi-megabyte HTML.
"""
import json
import re
from html.parser import HTMLParser

from . import edgar

SUBMISSIONS_URL = 'https://data.sec.gov/submissions/{name}'
DOCUMENT_URL = 'https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{document}'
SECTIONS = {'1': 'Business', '1A': 'Risk Factors', '7': "Management's Discussion and Analysis"}

MAX_PASSAGE_CHARS = 1200
MIN_PROSE_WORDS = 8
# "Item 1A. Risk Factors" at the start of a line, but not "Item 7 of this report".
_HEADING = re.compile(r'^(?:Item|ITEM)\s+(\d{1,2}[A-Ca-c]?)(?:\s*[.:—–-]|\s+[A-Z]|$)')
_SENTENCE_END = re.compile(r'(?<=[.;!?])\s+(?=[A-Z“"(])')
_BLOCK_TAGS = {'p', 'div', 'tr', 'br', 'li', 'table', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
_HIDDEN_TAGS = {'script', 'style', 'head', 'ix:header'}      # ix:header holds raw XBRL


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        self.hidden += tag in _HIDDEN_TAGS
        if tag in _BLOCK_TAGS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        self.hidden -= tag in _HIDDEN_TAGS
        if tag in _BLOCK_TAGS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            # A newline in the source is just spacing; only tags break lines.
            self.parts.append(data.replace('\n', ' '))


def to_lines(html):
    """Visible text, one line per block element, whitespace collapsed."""
    parser = _TextExtractor()
    parser.feed(html)
    lines = (' '.join(line.split()) for line in ''.join(parser.parts).split('\n'))
    return [line for line in lines if line]


def split_sections(lines):
    """{item: body lines} for the items in SECTIONS.

    Every item heading appears at least twice — in the table of contents and
    in the body — so the candidate with the most text is the real section.
    A section ends at the next heading for a DIFFERENT item: some filings
    repeat "Item 1A" as a running header on every page.
    """
    heads = [(i, m[1].upper()) for i, line in enumerate(lines) if (m := _HEADING.match(line))]
    starts = [h for n, h in enumerate(heads) if n == 0 or h[1] != heads[n - 1][1]]
    ends = [i for i, _ in starts[1:]] + [len(lines)]
    best = {}
    for (start, item), end in zip(starts, ends):
        body = lines[start + 1:end]
        if item in SECTIONS and sum(map(len, body)) > sum(map(len, best.get(item, []))):
            best[item] = body
    return best


def _is_prose(line):
    # Drops table rows, page footers and bare sub-headings.
    words = line.split()
    return (len(words) >= MIN_PROSE_WORDS
            and sum(w[0].isalpha() for w in words) / len(words) >= 0.8)


def _chunks(paragraph):
    """A long paragraph cut at sentence ends into pieces a tool result can carry."""
    chunks, current = [], ''
    for sentence in _SENTENCE_END.split(paragraph):
        if current and len(current) + len(sentence) >= MAX_PASSAGE_CHARS:
            chunks.append(current)
            current = sentence
        else:
            current = f'{current} {sentence}'.strip()
    return chunks + [current]


def passages(lines):
    return [chunk for line in lines if _is_prose(line) for chunk in _chunks(line)]


def find_10k(cik, year):
    """The 10-K whose report period ends in `year`."""
    name = f'CIK{cik:010d}.json'
    index = edgar._get_json(SUBMISSIONS_URL.format(name=name), f'submissions_{cik}.json')
    # Heavy filers (banks) push older filings out of "recent" into extra files.
    pages = [index['filings']['recent']] + index['filings'].get('files', [])
    for page in pages:
        if 'form' not in page:
            page = edgar._get_json(SUBMISSIONS_URL.format(name=page['name']), page['name'])
        for form, period, accn, document, filed in zip(
                page['form'], page['reportDate'], page['accessionNumber'],
                page['primaryDocument'], page['filingDate']):
            if form == '10-K' and period.startswith(str(year)):
                return {'company': index.get('name'), 'period_end': period, 'filed': filed,
                        'source': DOCUMENT_URL.format(cik=cik, accn=accn.replace('-', ''),
                                                      document=document)}
    raise edgar.EdgarError(f'no 10-K found for fiscal year {year}')


def load(ticker, year):
    """A filing as {ticker, company, fiscal_year, period_end, filed, source,
    text, sections: {item: [{id, text}]}}. `text` is the whole document, for
    checking quotes; passage ids look like AAPL-2023-1A-p017."""
    ticker = ticker.upper()
    cik = edgar.resolve_cik(ticker)
    cached = edgar.CACHE_DIR / f'filing_{cik}_{year}.json'
    if cached.exists():
        return json.loads(cached.read_text())

    filing = find_10k(cik, year)
    lines = to_lines(edgar.fetch(filing['source']).text)
    sections = {item: [{'id': f'{ticker}-{year}-{item}-p{n:03d}', 'text': text}
                       for n, text in enumerate(passages(body), 1)]
                for item, body in split_sections(lines).items()}
    filing = {'ticker': ticker, **filing, 'fiscal_year': year,
              'text': '\n'.join(lines), 'sections': sections}
    edgar.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(filing))
    return filing


def section(filing, item):
    """Passages of one section, or an error naming what the filing does have."""
    found = filing['sections'].get(item)
    if not found:
        have = sorted(k for k, v in filing['sections'].items() if v)
        raise edgar.EdgarError(
            f'section {item} not found in the fiscal {filing["fiscal_year"]} 10-K '
            f'(it may be incorporated by reference); available: {have}')
    return found
