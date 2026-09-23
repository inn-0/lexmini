# src/lexmini/spacy_detector.py
"""Supplement privacy screening without changing source text or its offsets.

Use pinned installed models. Serialise inference and retain one language model
to bound memory. Missing models fail explicitly; never download during upload.
"""

import threading

MODELS = {language: f"{language}_core_news_lg" for language in ("de", "fr", "it")}
MODELS["en"] = "en_core_web_lg"
LABELS = {
  "PER": ("person_name", "personal-private"),
  "ORG": ("organisation_name", "professional-secrecy"),
  "LOC": ("address", "professional-secrecy"),
  "PERSON": ("person_name", "personal-private"),
  "GPE": ("address", "professional-secrecy"),
  "FAC": ("address", "professional-secrecy"),
  "DATE": ("date", "personal-private"),
}
_lock = threading.RLock()
_model = None
_name = None


def detect(texts: list[str], languages: list[str]) -> list[list[dict]]:
  import spacy
  global _model, _name
  output = [[] for _ in texts]
  with _lock:
    for language in languages:
      if language not in MODELS:
        raise ValueError("Choose a supported spaCy language: German, French, Italian or English")
      name = MODELS[language]
      if _name != name:
        _model, _name = None, None
        try:
          model = spacy.load(name, exclude=["parser", "lemmatizer", "attribute_ruler", "morphologizer", "tagger"])
        except OSError as exc:
          raise ValueError(f"Required spaCy model {name} is missing. Install the locked project dependencies.") from exc
        if "ner" not in model.pipe_names:
          raise ValueError(f"Required spaCy model {name} has no entity detector")
        from .legal_references import add_spacy_ruler
        add_spacy_ruler(model)
        _model, _name = model, name
      # Current PDF input is bounded to 200,000 characters; do not truncate pages.
      for index, doc in enumerate(_model.pipe(texts, batch_size=4)):
        if doc.text != texts[index]:
          raise ValueError("spaCy changed source text; findings cannot be mapped safely")
        for reference in doc.spans.get('legal_references', []):
          output[index].append(dict(start=reference.start_char,end=reference.end_char,
            field_type='case_reference',level='public',subcategory='legal_reference',
            detector='spacy/legal-reference-ruler',reason='Configured spaCy legal-reference pattern matched; verify the source.'))
        for entity in doc.ents:
          if entity.label_ not in LABELS:
            continue
          field_type, level = LABELS[entity.label_]
          output[index].append(dict(start=entity.start_char, end=entity.end_char,
            field_type=field_type, level=level, subcategory="named_entity",
            detector=f"spacy/{name}@{_model.meta['version']}",
            reason=f"spaCy found a {entity.label_} entity. Review its relevance to this matter."))
  return output
