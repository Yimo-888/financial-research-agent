"""
Evidence UI server: ask a question in the browser and see how the answer was
built, or build a comparison report.

    python -m finagent.ui                 # then open http://127.0.0.1:8000

Standard library http.server, one process, no JavaScript. It listens on
localhost only, because every question spends your API key.
"""
import argparse
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import agent, evidence, report
from .pages import evidence_page, home_page, report_page


def respond(method, path, form):
    """(status, html) for one request; `form` maps field names to strings."""
    try:
        if (method, path) == ('GET', '/'):
            return 200, home_page()
        if (method, path) == ('POST', '/ask') and form.get('question', '').strip():
            question = form['question'].strip()
            return 200, evidence_page(evidence.build(question, agent.run(question)))
        if (method, path) == ('GET', '/report') and form.get('tickers') and form.get('year'):
            tickers = re.findall(r'[A-Za-z.\-]+', form['tickers'])
            return 200, report_page(report.build(tickers, int(form['year'])))
    except Exception as exc:              # show the failure instead of a blank page
        return 500, home_page(f'{type(exc).__name__}: {exc}')
    return 404, home_page('Nothing here. Ask a question or build a comparison below.')


class Handler(BaseHTTPRequestHandler):
    def _serve(self, method):
        url = urlparse(self.path)
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode() if method == 'POST' else ''
        form = {k: v[0] for k, v in parse_qs(body or url.query).items()}
        # Another site's page must not be able to make this server spend the API key.
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            status, page = 403, home_page('Cross-site request refused.')
        else:
            status, page = respond(method, url.path, form)
        data = page.encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._serve('GET')

    def do_POST(self):
        self._serve('POST')


def main():
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(prog='finagent.ui')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Evidence UI on http://127.0.0.1:{args.port}  (Ctrl-C to stop)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
