"""First-page layouts the local-copy matcher must recognise, and near misses it must refuse.

Every work, author and journal here is invented. The layouts are the families
found when the matcher was measured against a real library on 2026-11-25
(database cover sheets, journal first pages, author-above-title pages); the
real files are not in the repository and no text from them is reproduced.
"""
import hashlib
import unittest

import local_sources as ls

TITLE = 'Copper Lanterns and Silent Rivers'
FIELDS = dict(title=TITLE, authors='Mina Vale', lastNames=['Vale'], journal='Imaginary L. Rev.',
              volume='12', first='41', year='2024', pattern='article')
TWO = dict(FIELDS, authors='Mina Vale & Oscar Reed', lastNames=['Vale', 'Reed'])
BODY = '\n'.join('Invented body line %d about lanterns, rivers and the law of both.' % i for i in range(12))
ARTICLE = 'COPPER LANTERNS AND SILENT RIVERS\nMina Vale*\n' + BODY + '\n41\n'

HEIN_NEW = ('DATE DOWNLOADED: Mon Jan 5 10:00:00 2026\nSOURCE: Content Downloaded from HeinOnline\nCitations:\n'
            'Please note: citations are provided as a general guideline.\nBluebook 21st ed.\n'
            'Mina Vale, Copper Lanterns and Silent Rivers, 12 IMAGINARY L. REV. 41\n(2024).\nALWD 7th ed.\n'
            'Mina Vale, Copper Lanterns and Silent Rivers, 12 Imaginary L. Rev. 41 (2024).\nAPA 7th ed.\n'
            'Vale, M. (2024). Copper lanterns and silent rivers. Imaginary Law Review, 12(1), 41-90.\n')
HEIN_SITE = ('https://heinonline.org | holsupport@wshein.com\nCITATIONS:\nBluebook 22nd ed.\n'
             'Mina Vale, Copper Lanterns and Silent Rivers, 12 IMAGINARY L. REV. 41 (January 2024).\nALWD 7th ed.\n'
             'Mina Vale, Copper Lanterns and Silent Rivers, 12 Imaginary L. Rev. 41 (2024).\n')
HEIN_OLD = ('+(,121/,1(\nCitation: 12 Imaginary L. Rev. 41 2024\nContent downloaded/printed from\n'
            'HeinOnline (http://heinonline.org)\nMon Jan 5 10:00:00 2015\n'
            "-- Your use of this HeinOnline PDF indicates your acceptance\nof HeinOnline's Terms and Conditions\n")
JSTOR = ('Copper Lanterns and Silent Rivers\nAuthor(s): Mina Vale\n'
         'Source: Imaginary Law Review, Vol. 12, No. 1 (Jan., 2024), pp. 41-90\n'
         'Published by: Imaginary Law Review\nStable URL: https://www.jstor.org/stable/0000000\n'
         'JSTOR is a not-for-profit service that helps scholars discover content.\n')
JSTOR_GLUED = JSTOR.replace('Rivers\nAuthor(s):', 'RiversAuthor(s):')
REPOSITORY = ('Imaginary Law Review\nVolume 12 | Issue 1\nWinter 2024\nCopper Lanterns and Silent Rivers\nMina Vale\n'
              'Follow this and additional works at: https://scholarship.example.edu/ilr\nRecommended Citation\n'
              'Mina Vale, Copper Lanterns and Silent Rivers, 12 Imaginary L. Rev. 41 (2024).\n'
              'Available at: https://scholarship.example.edu/ilr/vol12/iss1/2\n')


def entry(text):
    return dict(readable=True, firstPages=text.split('\f')[:3], fileName='copy.txt',
                fileSha256=hashlib.sha256(text.encode()).hexdigest())


class CoverSheets(unittest.TestCase):
    def test_database_cover_sheets_identify_the_article(self):
        for name, cover in (('hein', HEIN_NEW), ('hein', HEIN_SITE), ('hein_citation_line', HEIN_OLD),
                            ('jstor', JSTOR), ('jstor', JSTOR_GLUED), ('repository', REPOSITORY)):
            with self.subTest(cover=cover[:30]):
                found = ls.identity(FIELDS, entry(cover + '\f' + ARTICLE))
                self.assertTrue(found['strong'], found)
                self.assertEqual(found['evidence'][0]['basis'], name + ' cover sheet')

    def test_database_scan_is_the_published_version(self):
        for cover in (HEIN_NEW, HEIN_OLD, JSTOR):
            version = ls.version_evidence(FIELDS, entry(cover + '\f' + ARTICLE))
            self.assertEqual(version['kind'], 'published'); self.assertTrue(version['pinciteEligible'])
        # A repository hosts drafts and final copies alike; its cover proves identity only.
        self.assertFalse(ls.version_evidence(FIELDS, entry(REPOSITORY + '\fCopper Lanterns and Silent Rivers\nMina Vale\n' + BODY))['pinciteEligible'])

    def test_cover_year_that_differs_is_reported_not_fatal(self):
        cited = dict(FIELDS, year='2023')
        found = ls.identity(cited, entry(HEIN_NEW + '\f' + ARTICLE))
        self.assertTrue(found['strong']); self.assertEqual(found['evidence'][0]['cover_years'], ['2024'])
        self.assertIn('2024', ls.version_evidence(cited, entry(HEIN_NEW + '\f' + ARTICLE))['observedYears'])
        # The citation-line layout has no title or author, so every number must agree.
        self.assertFalse(ls.identity(cited, entry(HEIN_OLD + '\f' + ARTICLE))['strong'])

    def test_series_prefix_in_the_cited_title(self):
        cited = dict(FIELDS, title='The Imaginary Court, 2023 Term: Foreword: ' + TITLE)
        self.assertTrue(ls.identity(cited, entry(HEIN_NEW + '\f' + ARTICLE))['strong'])

    def test_cover_for_another_work_ends_the_search(self):
        other = HEIN_NEW.replace('Copper Lanterns and Silent Rivers', 'Amber Harbors at Dusk').replace('12 I', '13 I').replace('12 i', '13 i')
        # The cited title heads page two, yet the provider says the file is a different article.
        found = ls.identity(FIELDS, entry(other + '\f' + ARTICLE))
        self.assertFalse(found['strong']); self.assertIn('cover sheet cites a different work', found['reasons'])
        for change in (('12 IMAGINARY', '13 IMAGINARY'), ('L. REV. 41', 'L. REV. 410'), ('Mina Vale', 'Nora Moss')):
            wrong = HEIN_NEW.replace('Bluebook 21st ed.\nMina Vale, Copper Lanterns and Silent Rivers, 12 IMAGINARY L. REV. 41',
                                     'Bluebook 21st ed.\nMina Vale, Copper Lanterns and Silent Rivers, 12 IMAGINARY L. REV. 41'.replace(*change))
            with self.subTest(change=change):
                self.assertFalse(ls.identity(FIELDS, entry(wrong + '\fUnrelated heading\nNora Moss\n' + BODY))['strong'])

    def test_cover_tier_is_for_articles_only(self):
        book = dict(title=TITLE, authors='Mina Vale', lastNames=['Vale'], year='2024', pattern='book')
        review = ('Review: Lanterns Reconsidered\nReviewed Work(s): Copper Lanterns and Silent Rivers by Mina Vale\n'
                  'Review by: Nora Moss\nSource: Imaginary Law Review, Vol. 12, No. 1 (Jan., 2024), pp. 41-90\n'
                  'Stable URL: https://www.jstor.org/stable/0000001\n')
        self.assertFalse(ls.identity(book, entry(review + '\fLANTERNS RECONSIDERED\nNora Moss\n' + BODY))['strong'])
        # The review itself, cited as a review, is found.
        cited = dict(FIELDS, title='Lanterns Reconsidered', authors='Nora Moss', lastNames=['Moss'])
        self.assertTrue(ls.identity(cited, entry(review + '\fLANTERNS RECONSIDERED\nNora Moss\n' + BODY))['strong'])


class FirstPages(unittest.TestCase):
    def strong(self, text, fields=FIELDS):
        return ls.identity(fields, entry(text))['strong']

    def test_journal_first_page_layouts(self):
        pages = ['Imaginary Law Review\nVolume 12                         January 2024\nARTICLE\nCopper Lanterns and\nSilent Rivers\nMina Vale*\n' + BODY,
                 'MINA VALE\nCopper Lanterns and Silent Rivers\nabstract. ' + BODY,
                 'VALE 12 IMAGINARY L. REV. 41.DOC (DO NOT DELETE)          1/5/2024\nCOPPER LANTERNS AND\nSILENT RIVERS\nMina Vale*\nINTRODUCTION ............ 42\n' + BODY,
                 'Copper Lanterns and Silent Rivers\nBy\nMina Q. Vale\n' + BODY,
                 'Copper Lanterns and Silent Rivers1\nM. Vale\n' + BODY]
        for page in pages:
            with self.subTest(page=page[:40]): self.assertTrue(self.strong(page))
        # OCR reads a dagger after a surname as t. Allowed on a longer surname only: Valet is a name too.
        harrow = dict(FIELDS, authors='Mina Harrow')
        self.assertTrue(self.strong('COPPER LANTERNS AND SILENT RIVERS\nMINA       HARROWt\n' + BODY, harrow))
        self.assertFalse(self.strong('COPPER LANTERNS AND SILENT RIVERS\nMINA       VALEt\n' + BODY))
        self.assertFalse(self.strong('COPPER LANTERNS AND SILENT RIVERS\nMINA HARROWf\n' + BODY, harrow))

    def test_co_authors(self):
        for page in ('Copper Lanterns and Silent Rivers\nMina Vale*\n& Oscar Reed**\n' + BODY,
                     'MINA VALE                & OSCAR REED\nCopper Lanterns and Silent Rivers\n' + BODY,
                     'Copper Lanterns and Silent Rivers\nMina Vale and Oscar Reed\n' + BODY):
            with self.subTest(page=page[:40]): self.assertTrue(self.strong(page, TWO))
        self.assertFalse(self.strong('Copper Lanterns and Silent Rivers\nMina Vale\n' + BODY, TWO))
        et_al = dict(FIELDS, authors='Mina Vale et al.')
        self.assertTrue(self.strong('Copper Lanterns and Silent Rivers\nMina Vale\nOscar Reed\nNora Moss\n' + BODY, et_al))

    def test_near_misses_stay_unmatched(self):
        for page in ('Copper Lanterns and Silent Rivers\nOscar Vale\n' + BODY,                  # a relative, not the author
                     'Copper Lanterns and Silent Rivers\nMina Vale and Nora Moss\n' + BODY,     # an unlisted co-author
                     'Copper Lanterns and Silent Rivers\nINTRODUCTION\n' + BODY,                # no byline at all
                     'Syllabus\nWeek 3\nCopper Lanterns and Silent Rivers\nMina Vale\nAmber Harbors at Dusk\nNora Moss',
                     'Copper Lanterns and Silent Rivers\nBy Mina Vale\nImaginary Press, 2024. Pp. 300. $40.\nReviewed by Nora Moss\n' + BODY,
                     'A Reply to\nCopper Lanterns and Silent Rivers\nMina Vale\n' + BODY):
            with self.subTest(page=page[:40]): self.assertFalse(self.strong(page))

    def test_review_words_in_the_cited_title_are_not_a_refusal(self):
        cited = dict(FIELDS, title='A Reply to Professor Moss')
        self.assertTrue(self.strong('A Reply to Professor Moss\nMina Vale\n' + BODY, cited))

    def test_running_citation_line_needs_the_page_label_too(self):
        page = 'Copper Lanterns and Silent Rivers\nMina Vale\n' + BODY + '\n12 IMAGINARY L. REV. 41 (2024)\n'
        # The article's own citation in a running foot is a publication label, not a page label.
        self.assertEqual(ls.version_evidence(FIELDS, entry(page))['kind'], 'unknown')
        self.assertEqual(ls.version_evidence(FIELDS, entry(page + '41\n'))['kind'], 'published')
        self.assertEqual(ls.version_evidence(FIELDS, entry('Forthcoming, Imaginary Law Review\n' + page + '41\n'))['kind'], 'working_paper')
        other = page.replace('IMAGINARY L. REV.', 'INTERNATIONAL LINGUISTICS REV.') + '41\n'
        self.assertEqual(ls.version_evidence(FIELDS, entry(other))['kind'], 'unknown')


def hein(citation):
    return 'HeinOnline\nBluebook 22nd ed.\n' + citation + '\nALWD 7th ed.\n'


CITE = 'Mina Vale, ' + TITLE + ', 12 Imaginary L. Rev. 41 (2024).'
PLAIN = TITLE + '\nMina Vale\n' + BODY


class Adversarial(unittest.TestCase):
    """Wrong documents that an independent review (2026-11-25) got past an earlier version."""

    def refused(self, text, fields=FIELDS):
        found = ls.identity(fields, entry(text))
        self.assertFalse(found['strong'], found['evidence'])

    def test_cover_evidence_must_come_from_one_citation(self):
        self.refused(hein('Nora Moss, Other Work, 12 Imaginary L. Rev. 41 (2024).\nMina Vale, ' + TITLE + ', 7 Other Journal 99 (2023).') + '\fOther Work\nNora Moss')
        self.refused(hein(CITE.replace('Mina Vale', 'Oscar Vale')) + '\f' + BODY)
        self.refused(hein(CITE.replace('Imaginary L. Rev.', 'Unrelated Medical Bulletin')) + '\f' + BODY)
        self.refused(hein(CITE.replace(TITLE, 'Erratum: ' + TITLE)) + '\f' + BODY)
        self.refused(hein('Mina Vale, ' + TITLE + '. Session 12 participants received 41 handouts in 2024.') + '\f' + BODY)
        self.refused(hein(CITE.replace('(2024)', '(2019)')) + '\f' + BODY)

    def test_a_reply_is_not_the_original_and_the_original_is_not_the_reply(self):
        reply = dict(FIELDS, title='A Reply to ' + TITLE)
        self.refused(hein(CITE) + '\f' + PLAIN, reply)
        self.refused(hein('Nora Moss, Reply to Mina Vale, ' + TITLE + ', 12 Imaginary L. Rev. 41 (2024).') + '\fReply to\n' + TITLE + '\nNora Moss')

    def test_jstor_review_does_not_identify_the_reviewed_article(self):
        review = ('Review: Lanterns Reconsidered\nReviewed Work(s): ' + TITLE + ' by Mina Vale\nReview by: Nora Moss\n'
                  'Source: Imaginary Law Review, Vol. 12, No. 1 (Jan., 2024), pp. 41-90\nStable URL: https://www.jstor.org/stable/0000001\n')
        self.refused(review + '\fLANTERNS RECONSIDERED\nNora Moss\n' + BODY)

    def test_citation_line_cover_needs_the_title_on_the_page(self):
        cover = 'HeinOnline\nCitation: 1 Imaginary L. Rev. 1 2024\nContent downloaded from HeinOnline\n'
        self.refused(cover + '\fForeword\nOscar Reed\n1', dict(FIELDS, title='Introduction', volume='1', first='1'))
        self.refused(cover + '\fForeword\nOscar Reed\n1', dict(FIELDS, title='Introduction', volume='1', first='1', authors=''))

    def test_a_mention_of_a_database_is_not_a_cover_sheet(self):
        self.refused('Other Work\nNora Moss\nThis article discusses HeinOnline.\f' + PLAIN)
        self.assertIsNone(ls.cover_sheet(entry('Other Work\nNora Moss\nThis article discusses HeinOnline and JSTOR.\f' + PLAIN)))

    def test_bylines_keep_each_given_name_with_its_surname(self):
        for byline in ('Mina Valen', 'For Mina Vale', 'Edited by Mina Vale', 'Translated by Mina Vale', 'Mina Vale\nReviewer: Nora Moss'):
            with self.subTest(byline=byline): self.refused(TITLE + '\n' + byline + '\n' + BODY)
        self.refused(TITLE + '\nMina Reed and Oscar Vale\n' + BODY, TWO)
        self.refused(TITLE + '\nFor Mina Vale and her many colleagues\n' + BODY, dict(FIELDS, authors='Mina Vale et al.'))

    def test_a_title_listed_under_another_heading_is_not_the_document(self):
        for heading in ('Contents', 'Symposium Contents', 'Constitutional Law: Cases and Materials', 'Course Schedule',
                        'Part II', 'Erratum', 'Correction to', 'In Reply to'):
            with self.subTest(heading=heading): self.refused(heading + '\n' + PLAIN)
        self.refused('Contents\n' + TITLE + '\nMina Vale\nOther Work\nNora Moss')
        self.refused(TITLE + '\nMina Vale\nOther Work\nNora Moss\nThird Piece\nOscar Reed')

    def test_stock_titles_need_the_page_to_show_where_it_was_published(self):
        for title in ('Introduction', 'Foreword', 'Comment'):
            cited = dict(FIELDS, title=title)
            with self.subTest(title=title):
                self.refused('Imaginary Law Review\nVolume 99 (2025)\n' + title + '\nMina Vale\n501', cited)
                self.refused(title + '\nMina Vale\n' + BODY, cited)
                self.assertTrue(ls.identity(cited, entry('Imaginary Law Review\nVolume 12 (2024)\n' + title + '\nMina Vale\n' + BODY + '\n41'))['strong'])
        self.refused('Mina Vale\n1\n' + BODY, dict(FIELDS, title='1'))

    def test_a_structural_heading_is_not_excused_by_the_cited_title(self):
        self.refused('References\nReferences and the Law\nMina Vale\nOther Books\nNora Moss', dict(FIELDS, title='References and the Law'))
        self.refused('Reply to\nReply to Silence\nMina Vale\n' + BODY, dict(FIELDS, title='Reply to Silence'))

    def test_another_script_in_the_title_is_not_discarded(self):
        self.refused('医学 Introduction and the Law of Rivers\nMina Vale\n' + BODY, dict(FIELDS, title='法律 Introduction and the Law of Rivers'))

    def test_database_copy_with_a_version_notice_is_not_published(self):
        for notice in ('Reprinted in Collected Essays, second edition (2025).', 'Early View: pagination is provisional.',
                       'Advance sheet: bound-volume pagination will differ.'):
            with self.subTest(notice=notice):
                version = ls.version_evidence(FIELDS, entry(hein(CITE) + '\f' + notice + '\n' + PLAIN + '\n1'))
                self.assertFalse(version['pinciteEligible'], version['note'])
        relabelled = hein(CITE) + '\f' + PLAIN + '\n301\f' + BODY + '\n302\f' + BODY + '\n303'
        self.assertFalse(ls.version_evidence(FIELDS, entry(relabelled))['pinciteEligible'])

    def test_drafts_with_a_running_citation_are_not_published(self):
        tail = '\n12 Imaginary L. Rev. 41 (2024)\n41'
        for notice in ('Draft for discussion', 'Uncorrected proof', 'Version: Accepted Manuscript',
                       'Electronic copy available at: https://ssrn.com/abstract=1234567'):
            with self.subTest(notice=notice):
                self.assertFalse(ls.version_evidence(FIELDS, entry(notice + '\n' + PLAIN + tail))['pinciteEligible'])
        self.assertFalse(ls.version_evidence(FIELDS, entry('Imaginary Law Review\nVolume 12 (2024), forthcoming\n' + PLAIN + '\n41'))['pinciteEligible'])
        late = TITLE + '\nMina Vale\n' + '\n'.join('Body line %d.' % i for i in range(11)) + '\nAccepted manuscript\n' + BODY + tail
        self.assertFalse(ls.version_evidence(FIELDS, entry(late))['pinciteEligible'])

    def test_long_runs_of_spaces_do_not_stall_the_cover_comparison(self):
        import time
        start = time.time()
        ls.identity(FIELDS, entry(hein('Mina Vale, ' + TITLE + ', 12 ' + ' ' * 6400 + 'x 99 (2024).') + '\f' + BODY))
        self.assertLess(time.time() - start, 1.0)

    def test_the_wrong_reply_cannot_outrank_the_right_manuscript(self):
        right = entry('Working paper\n' + PLAIN)
        wrong = entry(hein('Nora Moss, Reply to Mina Vale, ' + TITLE + ', 12 Imaginary L. Rev. 41 (2024).') + '\fReply to\n' + TITLE + '\nNora Moss')
        self.assertFalse(ls.identity(FIELDS, wrong)['strong'])
        chosen, candidates = ls.match(FIELDS, [right, wrong])
        # The reply's cover names the cited title, so it stays a listed candidate and nothing is chosen;
        # what must never happen is the reply being chosen as the published copy.
        self.assertTrue(chosen is None or chosen['fileSha256'] == right['fileSha256'])
        self.assertEqual(len(candidates), 2)


HEIN_OLD_COVER = ('+(,121/,1(\nCitation: 12 Imaginary L. Rev. 41 2024\nContent downloaded/printed from\n'
                  'HeinOnline (http://heinonline.org)\nMon Jan 5 10:00:00 2015\n')
PUB = 'Imaginary Law Review\nVolume 12 (2024)\n' + PLAIN + '\n41'


class SecondReview(unittest.TestCase):
    """Cases from the second independent review (2026-11-25)."""

    def refused(self, text, fields=FIELDS):
        found = ls.identity(fields, entry(text))
        self.assertFalse(found['strong'], found['evidence'])

    def accepted(self, text, fields=FIELDS):
        found = ls.identity(fields, entry(text))
        self.assertTrue(found['strong'], found['reasons'])

    def test_citation_line_cover_needs_title_and_author_at_the_head(self):
        for page in ('Erratum: ' + TITLE + '\nMina Vale\n' + BODY + '\n41', TITLE + ' Reconsidered\nMina Vale\n' + BODY,
                     TITLE + '\nOscar Reed\n' + BODY, 'Contents\n' + TITLE + '\nMina Vale\n' + BODY):
            with self.subTest(page=page[:40]): self.refused(HEIN_OLD_COVER + '\f' + page)
        self.accepted(HEIN_OLD_COVER + '\f' + PLAIN)

    def test_names_are_matched_person_by_person(self):
        for cited, byline in (('Mina Vale', 'Mina Reed and Oscar Vale'), ('Mina de la Cruz', 'Mina Cruz'), ('Mina Van Kessel', 'Mina Kessel'),
                              ('Mina Dan-Cohen', 'Mina Cohen'), ('Mina Vale Jr.', 'Mina Vale Sr.'), ('Mina Vale', 'Mina Valet'),
                              ('Mina Vale', 'Mina Valef'), ('Mina Vale et al.', 'Mina Vale argues that copper matters')):
            with self.subTest(cited=cited, byline=byline): self.refused(TITLE + '\n' + byline + '\n' + BODY, dict(FIELDS, authors=cited))
        for cited, byline in (('Mina de la Cruz', 'Mina de la Cruz'), ('Mina Dan-Cohen', 'MINA DAN-COHEN*'), ('Mina Vale Jr.', 'Mina Vale, Jr.'),
                              ('Vale, Mina', 'Mina Vale'), ('Mina Vale Vale', 'Mina Vale Vale'), ('Mina Law', 'Mina Law'),
                              ('Mina Q. Vale', 'Mina Vale'), ('Mina Vale', 'Mina Quincy Vale'), ('Mina Vale & Oscar Reed', 'Mina Vale∗ Oscar Reed')):
            with self.subTest(cited=cited, byline=byline): self.accepted(TITLE + '\n' + byline + '\n' + BODY, dict(FIELDS, authors=cited))

    def test_reading_lists_and_unlisted_names(self):
        self.refused('Faculty Reading List\n' + TITLE + '\nMina Vale\nOTHER WORK\nOSCAR REED')
        self.refused('https://example.edu/syllabus spring readings for the seminar on rivers\n' + PLAIN)
        self.refused('Selected research papers\n' + PLAIN)
        for extra in ('O. Reed', 'OSCAR REED', 'Oscar Vale'):
            with self.subTest(extra=extra): self.refused(TITLE + '\nMina Vale\n' + extra + '\n' + BODY)
        for heading in ('Executive Summary', 'Legal Framework', 'Key Findings', 'INTRODUCTION', 'Abstract'):
            with self.subTest(heading=heading): self.accepted(TITLE + '\nMina Vale\n' + heading + '\n' + BODY)

    def test_text_that_quotes_a_cover_is_not_a_cover(self):
        quoting = ('Citation: database cover examples\nAn analysis of metadata in HeinOnline\nNora Moss\nBluebook 22nd ed.\n' + CITE + '\nALWD 7th ed.\n' + BODY)
        self.assertIsNone(ls.cover_sheet(entry(quoting))); self.refused(quoting)
        essay = 'An Essay on Citation Formats\nNora Moss\nRecommended Citation\n' + CITE + '\n' + BODY
        self.assertIsNone(ls.cover_sheet(entry(essay))); self.refused(essay)

    def test_cover_fields_are_delimited(self):
        self.refused(hein('Mina Vale Copper, Lanterns and Silent Rivers, 12 Imaginary L. Rev. 41 (2024).') + '\f' + BODY)
        self.refused(hein('Mina Vale (and Oscar Reed), ' + TITLE + ' (Part II), 12 Imaginary L. Rev. 41 (2024).') + '\f' + BODY)
        self.refused(hein(CITE) + '\f' + BODY, dict(FIELDS, title='Reply to the Foreword: ' + TITLE))
        self.refused(JSTOR.replace(TITLE + '\nAuthor', 'Law: ' + TITLE + '\nAuthor') + '\f' + BODY)
        self.refused(hein('Mina Vale, ' + TITLE + ', 12 Imaginary L. Rev. 41 (2019).\nNora Moss (2024), Other Work.') + '\f' + PLAIN)
        # A parenthetical subtitle the citation omits is the same piece at the same volume and page.
        self.accepted(hein('Mina Vale, ' + TITLE + ' (And Other Waters), 12 Imaginary L. Rev. 41 (2024).') + '\f' + BODY)

    def test_journal_names_must_agree_word_for_word(self):
        for cover in (hein(CITE.replace('Imaginary L. Rev.', 'International Linguistics Review')),
                      JSTOR.replace('Source: Imaginary Law Review', 'Source: International Linguistics Review')):
            with self.subTest(cover=cover[:30]): self.refused(cover + '\f' + BODY)
        self.assertTrue(ls.journals_agree('Va. L. Rev.', 'Virginia Law Review'))
        self.assertTrue(ls.journals_agree('N.Y.U. J.L. & Liberty', 'NYU Journal of Law and Liberty'))
        self.assertTrue(ls.journals_agree("Am. B. Found. Rsch. J.", 'American Bar Foundation Research Journal'))
        self.assertFalse(ls.journals_agree('Imaginary L. Rev.', 'International Linguistics Review'))

    def test_another_script_on_either_side(self):
        self.refused(hein(CITE.replace(TITLE, '医学 ' + TITLE)) + '\f' + BODY, dict(FIELDS, title='法律 ' + TITLE))
        self.refused('医学 ' + TITLE + '\nMina Vale\n' + BODY)

    def test_stock_title_needs_its_own_first_page(self):
        cited = dict(FIELDS, title='Introduction')
        self.refused('Imaginary Law Review\nVolume 12 (2024)\nIntroduction\nMina Vale\n' + BODY + '\n501', cited)
        for title in ('Faculty Tribute', 'Case Comment', 'Recent Cases'):
            with self.subTest(title=title): self.refused(title + '\nMina Vale\n' + BODY, dict(FIELDS, title=title))

    def test_version_notices_in_more_places(self):
        def eligible(text, fields=FIELDS): return ls.version_evidence(fields, entry(text))['pinciteEligible']
        after = lambda notice: PUB.replace('Mina Vale\n', 'Mina Vale\n' + notice + '\n', 1)
        self.assertTrue(eligible(PUB))
        for notice in ('This is an uncorrected proof', 'Version of record forthcoming', 'Accepted\nmanuscript',
                       'Reprinted from Imaginary Law Review with permission of the publisher and the author for use in this collected volume.'):
            with self.subTest(notice=notice): self.assertFalse(eligible(after(notice)))
        self.assertFalse(eligible(REPOSITORY + '\nAccepted manuscript\f' + PUB))
        # Prose that wraps onto a line beginning with a marker word is not a notice.
        self.assertTrue(eligible(PUB.replace(BODY, 'The author thanks readers of an earlier\ndraft. Their comments improved it.\n' + BODY)))
        # The work's own title is never a version notice, whatever its capitalisation.
        titled = dict(FIELDS, title='Working Paper Markets and Their Regulation')
        own = 'Imaginary Law Review\nVolume 12 (2024)\nWORKING PAPER MARKETS AND THEIR REGULATION\nMina Vale\n' + BODY + '\n41'
        self.assertTrue(eligible(hein(CITE.replace(TITLE, 'Working Paper Markets and Their Regulation')) + '\f' + own, titled))

    def test_database_copy_pagination(self):
        def eligible(text): return ls.version_evidence(FIELDS, entry(text))['pinciteEligible']
        self.assertFalse(eligible(hein(CITE)))                                             # a cover and nothing else
        self.assertFalse(eligible(hein(CITE) + '\f' + PLAIN + '\n44\f' + BODY + '\n45'))  # a run that starts elsewhere
        self.assertFalse(eligible(hein(CITE) + '\f' + PLAIN + '\n41\n301\f' + BODY + '\n42\n302'))
        self.assertTrue(eligible(hein(CITE) + '\f' + PLAIN + '\n41\f' + BODY + '\n42'))
        self.assertTrue(eligible(hein(CITE) + '\f' + PLAIN))                              # first pages often carry no number

    def test_publication_labels_must_cohere_on_the_first_page(self):
        split = PLAIN + '\nVolume 99 (2025)\n41\fImaginary Law Review\nVolume 12 (2024)\nSource citation\n' + BODY + '\n301'
        self.assertFalse(ls.version_evidence(FIELDS, entry(split))['pinciteEligible'])

    def test_cover_layout_variations_still_match(self):
        self.accepted(HEIN_NEW.replace('Bluebook 21st ed.\n', 'Bluebook 21st ed. ') + '\f' + ARTICLE)
        variant = ('Content downloaded/printed from      HeinOnline\nFri Jan 17 17:01:51 2020\nCitations:\nBluebook 20th ed.\n'
                   'Mina Vale, Copper Lanterns and Silent Rivers, 12 Imaginary L. Rev. 41 (2024).\nALWD 6th ed.\n')
        self.accepted(variant + '\f' + ARTICLE)
        older = ('+(,121/,1(\nCitation:\nMina Vale; Oscar Reed, Copper Lanterns and Silent\nRivers, 12 Imaginary L. Rev. 41 (2024)\nProvided by:\n'
                 'Imaginary University Law Library\nContent downloaded/printed from\nHeinOnline (http://heinonline.org)\n')
        self.accepted(older + '\f' + ARTICLE, TWO)


if __name__ == '__main__':
    unittest.main()
