# tests/test_selectable_pdf.py
# Rationale: shared PDFs must copy permitted text without restoring removed originals.
# Assumptions: text-containing source PDFs; image-only text still needs manual inspection.
# Constraints: rebuild from redacted text, exclude attachments, test all replacement styles.
import unittest
import pymupdf
from lexmini import pdf, rules
from lexmini.schemas import Context
from lexmini.tokens import TokenRegistry


class SelectablePDFTests(unittest.TestCase):
  def fixture(self):
    with pymupdf.open() as doc:
      page=doc.new_page()
      page.insert_text((40,70),'Public before SecretPerson public after.')
      page.insert_text((40,100),'Français: procédure, geprüft, più.')
      doc.set_metadata({'author':'SecretPerson'})
      page.add_text_annot((30,30),'SecretPerson')
      doc.embfile_add('secret.txt',b'SecretPerson')
      return doc.tobytes()

  def test_copy_keeps_surrounding_text_and_only_chosen_placeholder(self):
    for style,marker in [('tokens','[TERM_00001]'),('x','[X]'),('blank',None)]:
      with self.subTest(style=style):
        payload=self.fixture()
        pages=pdf.extract(payload).pages
        findings=[f for f in rules.findings_for_page('unit',pages[0],[],
          Context(confidential_terms=['SecretPerson'])) if f.field_type=='confidential_term']
        result=pdf.export_pdf(payload,findings,pages,TokenRegistry(),style)
        with pymupdf.open(stream=result,filetype='pdf') as doc:
          text=doc[0].get_text(sort=True)
          self.assertNotIn('SecretPerson',text)
          self.assertIn('Public before',text)
          self.assertIn('public after.',text)
          self.assertIn('Français',text)
          self.assertIn('geprüft',text)
          if marker:
            self.assertIn(marker,text)
            self.assertTrue(doc[0].search_for(marker))
            stream_text=doc[0].get_text()
            self.assertLess(stream_text.index('Public before'),stream_text.index(marker))
            self.assertLess(stream_text.index(marker),stream_text.index('public after'))
          else:
            self.assertNotIn('[',text)
          self.assertEqual(doc.embfile_count(),0)
          self.assertFalse(doc.metadata.get('author'))
          self.assertFalse(doc[0].first_annot)
          streams=b''.join(doc.xref_stream(x) or b'' for x in range(1,doc.xref_length()) if doc.xref_is_stream(x))
          self.assertNotIn(b'SecretPerson',streams)

  def test_selected_text_is_removed_when_no_characters_survive(self):
    with pymupdf.open() as source:
      page=source.new_page()
      page.insert_text((50,80),'SecretPerson')
      payload=source.tobytes()
    pages=pdf.extract(payload).pages
    findings=[f for f in rules.findings_for_page('unit',pages[0],[],
      Context(confidential_terms=['SecretPerson'])) if f.field_type=='confidential_term']
    result=pdf.export_pdf(payload,findings,pages,TokenRegistry(),'tokens')
    with pymupdf.open(stream=result,filetype='pdf') as doc:
      self.assertIn('[TERM_00001]',doc[0].get_text())
      self.assertNotIn('SecretPerson',doc[0].get_text())
