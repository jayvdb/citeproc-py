
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
from citeproc.py2compat import *


import glob
import io
import json
import os
import sys
import traceback

from codecs import utf_8_encode
from functools import reduce
from optparse import OptionParser

from citeproc import CitationStylesStyle, CitationStylesBibliography
from citeproc.source import Citation, CitationItem, Locator
from citeproc.source.json import CiteProcJSON


if sys.version_info[0] < 3:
    str = unicode


TESTS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                          os.path.pardir, os.path.pardir,
                                          'citeproc-test', 'processor-tests',
                                          'machines'))

# The results of the following tests are ignored, since they don't test CSL
# features, but citeproc-js specific features

IGNORED_RESULS = {
    'date_Accessed': 'raw date',
    'date_LoneJapaneseMonth': 'raw date',
    'date_LopsidedDataYearSuffixCollapse': 'raw date',
    'date_RawParseSimpleDate': 'raw date',
    'date_RawSeasonRange1': 'raw date',
    'date_RawSeasonRange2': 'raw date',
    'date_RawSeasonRange3': 'raw date',
    'date_String': 'raw date',
}


class ProcessorTest(object):
    bib_prefix = '<div class="csl-bib-body">'
    bib_suffix = '</div>'
    item_prefix = '  <div class="csl-entry">'
    item_suffix = '</div>'

    def __init__(self, filename):
        with open(filename, 'rt', encoding='UTF-8') as f:
            self.json_data = json.load(f)

        csl_io = io.BytesIO(utf_8_encode(self.json_data['csl'])[0])
        self.style = CitationStylesStyle(csl_io)
        self._fix_input(self.json_data['input'])
        self.references = [item['id'] for item in self.json_data['input']]
        self.references_dict = CiteProcJSON(self.json_data['input'])
        self.bibliography = CitationStylesBibliography(self.style,
                                                       self.references_dict)
        self.expected = self.json_data['result'].splitlines()

    @staticmethod
    def _fix_input(input_data):
        for i, ref in enumerate(input_data):
            if 'id' not in ref:
                ref['id'] = i
            if 'type' not in ref:
                ref['type'] = 'book'

    def execute(self):
        if self.json_data['citation_items']:
            citations = [self.parse_citation(item)
                         for item in self.json_data['citation_items']]
        elif self.json_data['citations']:
            citations = []
            for cit in self.json_data['citations']:
                cit = cit[0]
                citation_items = [self.parse_citation_item(cititem)
                                  for cititem in cit['citationItems']]
                citation = Citation(citation_items)
                citation.key = cit['citationID']
                citation.note_index = cit['properties']['noteIndex']
                citations.append(citation)
        elif self.json_data['bibentries']:
            citation_items = [self.parse_citation_item({'id': entry})
                              for entry in self.json_data['bibentries'][-1]]
            citations = [Citation(citation_items)]
        else:
            citation_items = [self.parse_citation_item({'id': ref})
                              for ref in self.references]
            citations = [Citation(citation_items)]

        for citation in citations:
            self.bibliography.register(citation)

        if self.style.has_bibliography():
            self.bibliography.sort()

        results = []
        do_nothing = lambda x: None     # callback passed to cite()
        if self.json_data['mode'] == 'citation':
            if self.json_data['citations']:
                for i, citation in enumerate(citations):
                    if i == len(citations) - 1:
                        dots_or_other = '>>'
                    else:
                        dots_or_other = '..'
                    results.append('{}[{}] '.format(dots_or_other, i) +
                                   self.bibliography.cite(citation, do_nothing))
            else:
                for citation in citations:
                    results.append(self.bibliography.cite(citation, do_nothing))
        elif self.json_data['mode'] in ('bibliography', 'bibliography-nosort'):
            results.append(self.bib_prefix)
            for entry in self.bibliography.bibliography():
                text = self.item_prefix + str(entry) + self.item_suffix
                results.append(text)
            results.append(self.bib_suffix)

        return results

    def parse_citation(self, citation_data):
        citation_items = []
        for item in citation_data:
            citation_item = self.parse_citation_item(item)
            citation_items.append(citation_item)

        return Citation(citation_items)

    def parse_citation_item(self, citation_item_data):
        options = {}
        for key, value in citation_item_data.items():
            python_key = key.replace('-', '_')
            if python_key == 'id':
                reference_key = str(value)
                continue
            elif python_key == 'locator':
                try:
                    options['locator'] = Locator(citation_item_data['label'],
                                                 value)
                except KeyError:
                    # some tests don't specify the label
                    options['locator'] = Locator('page', value)
            elif python_key == 'label':
                pass
            else:
                options[python_key] = value

        return CitationItem(reference_key, **options)


def main():
    usage = ('usage: %prog [options] glob_pattern\n\n'
             'glob_pattern limits the tests that are executed, for example:\n'
             '  %prog *Sort*\n'
             'runs only test fixtures that have "Sort" in the filename')
    parser = OptionParser(usage)
    parser.add_option('-m', '--max', dest='max', default=-1,
                      help='run maximally MAX tests', metavar='MAX')
    parser.add_option('-r', '--raise', dest='catch_exceptions', default=True,
                      action='store_false',
                      help='exceptions are not caught (aborts program)')
    parser.add_option('-f', '--file', dest='file', default=None,
                      help='write output to FILE', metavar='FILE')
    (options, args) = parser.parse_args()

    try:
        destination = open(options.file, 'wt', encoding='utf-8')
        class UnicodeWriter(object):
            def write(self, s):
                destination.write(str(s))
        sys.stderr = UnicodeWriter()
    except TypeError:
        destination = sys.stdout
    def out(*args):
        if not args:
            destination.write('\n')
        else:
            print(*args, file=destination)

    try:
        glob_pattern = args[0]
        filter_tests = False
    except IndexError:
        glob_pattern = '*'
        filter_tests = True

    test_file_glob = os.path.join(TESTS_PATH,
                                  '{0}.json'.format(glob_pattern))

    test_files = glob.glob(test_file_glob)

    total_count = {}
    passed_count = {}
    failed = []
    max_tests = int(options.max)

    count = 0

    for filename in sorted(test_files):
        test_name = os.path.basename(filename).split('.json')[0]
        category = os.path.basename(filename).split('_')[0]
        passed_count.setdefault(category, 0)
        if count == max_tests:
            break

        try:
            if test_name not in IGNORED_RESULS:
                total_count[category] = total_count.get(category, 0) + 1
                count += 1
            t = ProcessorTest(filename)
            if filter_tests and (t.json_data['mode'] == 'bibliography-header' or
                                 t.json_data['bibsection']):
                continue
            out('>>> Testing {}'.format(os.path.basename(filename)))
            out('EXP: ' + '\n     '.join(t.expected))

            results = t.execute()
            results = reduce(lambda x, y: x+y,
                             [item.split('\n') for item in results])
            results = [item.replace('&amp;', '&#38;')
                       for item in results]
            out('RES: ' + '\n     '.join(results))
            if results == t.expected:
                if test_name not in IGNORED_RESULS:
                    passed_count[category] += 1
                out('<<< SUCCESS\n')
                continue
            else:
                out('<<< FAILED\n')
            del t
        except Exception as e:
            out('Exception in', os.path.basename(filename))
            if options.catch_exceptions:
                traceback.print_exc()
            else:
                raise
        if test_name not in IGNORED_RESULS:
            failed.append(test_name)

    if sum(total_count.values()) == 0:
        print('<no tests found>: check README.md file for instructions')
    else:
        def print_result(name, passed, total):
            out(' {:<13} {:>3} / {:>3} ({:>4.0%})'.format(name, passed, total,
                                                          passed / total))

        out('Failed tests:')
        for test_name in sorted(failed):
            out(' ' + test_name)

        out()
        out('Summary:')
        for category in sorted(total_count.keys()):
            print_result(category, passed_count[category], total_count[category])
        out()
        print_result('total', sum(passed_count.values()), sum(total_count.values()))
    try:
        destination.close()
    except AttributeError:
        pass


if __name__ == '__main__':
    main()
