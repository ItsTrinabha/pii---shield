"""PERSON detection: names are the hardest class, so evidence is layered and every layer is explainable.

Layers (strongest first):
  1. context patterns: Name (EMP-1234), Ms Name, Name, <job title>, 'approved by Name', 'Owner: Name'
  2. spaCy NER (via Presidio) after rule-based filtering (business vocabulary, organisation allow-list, single tokens)
  3. e-mail derived surnames (t.lindqvist@ -> Lindqvist)
  4. stand-alone name-like lines (table cells) scored on first-name gazetteer + NER agreement
  5. document lexicon: once a person is established, every other spelling of them is found
     ('R. E. Duarte', 'Duarte', 'Rafael Duarte', 'Rafael'), so one strong sighting protects the whole document.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from dataclasses import dataclass, field
from functools import lru_cache

from ..settings import allowlist
from .ner import NBlock
from .patterns import Cand

_CAP = r"[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+(?:[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+)*"
_WORD = rf"{_CAP}(?:['’]{_CAP})?(?:-{_CAP})*"
_INIT = r"[A-Z]\.(?:-?[A-Z]\.)?"
_PART = r"(?:van|von|de|del|della|der|den|di|da|bin|ibn|al|el|le|la)"
_NAME_A = rf"{_WORD}(?:[ \t]+(?:{_INIT}|{_WORD})){{0,2}}?(?:[ \t]+{_PART})?[ \t]+{_WORD}"
_NAME_B = rf"(?:(?:{_INIT}[ \t]*){{1,3}}|[A-Z]{{2}}[ \t]+){_WORD}"
NAME = rf"(?:{_NAME_B}|{_NAME_A})"

_TITLES = (r"(?:(?:Group|Deputy|Chief|Head|Senior|Vice|Executive|Regional|Local|Interim|Lead|Principal|Associate)[ \t]+)*"
           r"(?:CEO|CFO|CRO|COO|CIO|CPO|CISO|DPO|CTO|VP|SVP|EVP|Director|Manager|Officer|Engineer|Counsel|Secretary|Chair(?:man|woman|person)?|"
           r"Analyst|Head|Lead|Partner|President|Administrator|Associate|Consultant|Specialist|Controller|Treasurer|Auditor|Developer|"
           r"Architect|Owner|Supervisor|Coordinator|Representative|Assessor|Reviewer|Adjuster)\b")
_CUES = (r"(?:approved by|reviewed by|prepared by|authored by|signed by|issued by|raised by|managed by|attested by|booked by|chaired by|"
         r"owned by|owner|author|reviewer|approver|signatory|sponsor|attn|attention|contact|contacts|queries|per|c/o|cc|bcc|dear|"
         r"hi|hello|thanks|regards|sincerely|administrator|handler|manager|challenger|incident manager|case handler|"
         r"led by|reported by|escalated to|assigned to|submitted by)")

P_ID = re.compile(rf"(?P<n>{NAME})(?=[ \t]*[(,\u2013\u2014\-]?[ \t]*(?:(?:EMP|DIR|EID)[ \t]?[\-\u2013]|[A-Z]{{3}}-[A-Z]{{2}}-\d{{4}}))")
P_HONORIFIC = re.compile(rf"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Sir|Dame)\.?[ \t]+(?P<n>{_WORD}(?:[ \t]+{_WORD}){{0,2}})")
P_TITLE_AFTER = re.compile(rf"(?P<n>{NAME})(?=[ \t]*[,\u2013\u2014\-(][ \t]*{_TITLES})")
P_CUE = re.compile(rf"(?i:\b{_CUES})[ \t]*[:\-]?[ \t]*(?P<n>{NAME})")
P_LABEL = re.compile(rf"\b(?:Name|Owner|Author|Approver|Reviewer|Contact|Manager|Attendee|Requester|Signatory)[ \t]*:[ \t]*(?P<n>{NAME})")
P_NAME_ANY = re.compile(rf"(?<![A-Za-z])(?P<n>{NAME})(?![A-Za-z])")
_NAME_LINE = re.compile(rf"^\s*(?P<n>{NAME})\s*$")
_TOKEN = re.compile(r"[A-Za-zÀ-ÿ]+(?:[\-'’][A-Za-zÀ-ÿ]+)*\.?")

_AMBIGUOUS = {
    "park", "bell", "hall", "lane", "young", "king", "long", "white", "brown", "green", "hill", "wood", "ward", "west", "north",
    "south", "east", "price", "cook", "mark", "will", "grace", "hope", "rose", "june", "april", "august", "may", "summer", "joy",
    "faith", "art", "rich", "frank", "sue", "pat", "dawn", "reed", "reid", "case", "major", "little", "stone", "field", "fields",
    "bank", "page", "chase", "wells", "cross", "hunter", "baker", "carter", "cooper", "fisher", "gardner", "mason", "porter",
    "rivers", "walker", "marshall", "bishop", "knight", "sharp", "strong", "swift", "wise", "bond", "brook", "brooks", "church",
}


@lru_cache(maxsize=1)
def _vocab() -> frozenset[str]:
    return frozenset(w.lower() for w in allowlist()["business_vocabulary"])


@lru_cache(maxsize=1)
def _orgs() -> frozenset[str]:
    return frozenset(o.lower() for o in allowlist()["organisations"])


@lru_cache(maxsize=1)
def first_name_gazetteer() -> frozenset[str]:
    """Latin-script first names from Faker's locale data (used only as a boost, never as sole evidence)."""
    import faker.providers.person as pp

    names: set[str] = set()
    for m in pkgutil.iter_modules(pp.__path__):
        try:
            mod = importlib.import_module(f"faker.providers.person.{m.name}")
        except Exception:  # noqa: BLE001
            continue
        prov = getattr(mod, "Provider", None)
        if prov is None:
            continue
        for attr in dir(prov):
            if attr.startswith("first_names"):
                v = getattr(prov, attr)
                items = list(v.keys()) if isinstance(v, dict) else (list(v) if isinstance(v, (list, tuple)) else [])
                names.update(x.lower() for x in items if isinstance(x, str) and re.fullmatch(r"[A-Za-z][a-z'’\-]+", x))
    return frozenset(names - _AMBIGUOUS)


@lru_cache(maxsize=1)
def surname_gazetteer() -> frozenset[str]:
    import faker.providers.person as pp

    names: set[str] = set()
    for m in pkgutil.iter_modules(pp.__path__):
        try:
            mod = importlib.import_module(f"faker.providers.person.{m.name}")
        except Exception:  # noqa: BLE001
            continue
        prov = getattr(mod, "Provider", None)
        if prov is None:
            continue
        for attr in dir(prov):
            if attr.startswith("last_names"):
                v = getattr(prov, attr)
                items = list(v.keys()) if isinstance(v, dict) else (list(v) if isinstance(v, (list, tuple)) else [])
                names.update(x.lower() for x in items if isinstance(x, str) and re.fullmatch(r"[A-Za-z][a-z'’\-]+", x))
    return frozenset(names)


@lru_cache(maxsize=65536)
def zipf(word: str) -> float:
    from wordfreq import zipf_frequency

    return zipf_frequency(word.lower(), "en")


_COMMON_SUFFIX = re.compile(r"(?:tion|tional|sion|ity|ment|ness|ical|ative|ious|ous|ible|able|ology|ships?|ance|ence|ings?|ized?|ised?|ally)$")


def looks_common(word: str) -> bool:
    """Everyday-word test: frequent in English, or carrying a derivational suffix names almost never have."""
    w = ln(word)
    if len(w) <= 1 or w in first_name_gazetteer() or w in surname_gazetteer():
        return False
    return zipf(w) >= 3.0 or (len(w) >= 7 and bool(_COMMON_SUFFIX.search(w)) and zipf(w) >= 1.5)


def ln(tok: str) -> str:
    """letters-only lowercase form: 'Okonkwo-Bell' -> 'okonkwobell', 'T.' -> 't'."""
    return re.sub(r"[^a-zà-ÿ]", "", tok.lower())


def _tokens(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in _TOKEN.finditer(text)]


@dataclass
class Person:
    pid: str  # f"{last}|{first_initial}"
    last: str  # letters-only
    first: str = ""  # letters-only full first name if known else single initial
    mid: str = ""  # first letter of a middle name/initial if known
    strong: bool = True
    hits: int = 0


@dataclass
class Registry:
    persons: dict[str, Person] = field(default_factory=dict)
    by_last: dict[str, list[Person]] = field(default_factory=dict)

    def add(self, first: str, mid: str, last: str, strong: bool = True) -> Person:
        first, mid, last = ln(first), ln(mid)[:1], ln(last)
        if len(first) > 1 and looks_common(first):
            first = first[:1]  # an everyday word is not a first name; keep only the initial
        pid = f"{last}|{first[:1]}"
        p = self.persons.get(pid)
        if p is None:
            p = Person(pid=pid, last=last, first=first, mid=mid, strong=strong)
            self.persons[pid] = p
            self.by_last.setdefault(last, []).append(p)
        else:
            if len(first) > len(p.first):
                p.first = first
            if mid and not p.mid:
                p.mid = mid
            p.strong = p.strong or strong
        return p

    def resolve_last(self, last: str, first_initial: str = "") -> Person | None:
        cands = self.by_last.get(ln(last), [])
        if first_initial:
            for p in cands:
                if p.first[:1] == first_initial:
                    return p
            return None
        return cands[0] if len(cands) == 1 else None


def parse_name(text: str) -> tuple[str, str, str] | None:
    """-> (first, middle, last) letters-only; first may be a single initial."""
    toks = [ln(t) for _, _, t in _tokens(text)]
    toks = [t for t in toks if t and t not in {"van", "von", "de", "del", "della", "der", "den", "di", "da", "bin", "ibn", "al", "el", "le", "la"}] or toks
    if len(toks) < 2:
        return None
    return toks[0], (toks[1] if len(toks) == 3 else ""), toks[-1]


def _vocab_hit(text: str) -> bool:
    v = _vocab()
    return any(ln(t) in v for _, _, t in _tokens(text))


def _plausible_name(text: str) -> bool:
    """Shape and vocabulary screen shared by every PERSON source."""
    if any(ch.isdigit() or ch in "@/\\_%&" for ch in text):
        return False
    if text.strip().lower() in _orgs():
        return False
    toks = _tokens(text)
    if not (2 <= len(toks) <= 5):
        return False
    if _vocab_hit(text):
        return False
    if any(ln(t) in _orgs() for _, _, t in toks):
        return False
    return True


def accept_tokens(text: str, known_last: set[str] | frozenset[str] = frozenset()) -> bool:
    """Does this capitalised phrase behave like a personal name rather than a common phrase?

    Evidence for: first name in the first-name gazetteer, surname in the surname gazetteer, an already-established
    person, or every word being rare (proper-noun-like). Evidence against: the last word is an everyday word."""
    raw = [ln(t[2]) for t in _tokens(text)]
    toks = [t for t in raw if len(t) > 1]
    if not toks:
        return False
    first, last = toks[0], toks[-1]
    if len(raw) >= 2 and len(toks) == 1 and last not in surname_gazetteer() and last not in known_last:
        return False  # 'W Howlong': an initial plus an unknown word is not enough on its own
    fg, sg = first_name_gazetteer(), surname_gazetteer()
    if last in known_last:
        return True
    if zipf(last) >= 5.2 and last not in sg:
        return False
    if first in fg or last in sg:
        return True
    return all(zipf(t) < 4.5 for t in toks)


def trim_span(text: str, s: int, e: int) -> tuple[int, int] | None:
    """Strip leading/trailing everyday words that a greedy capitalised-phrase match swallowed
    ('Annual Ananya V. Chatterjee' -> 'Ananya V. Chatterjee'). Gazetteer names and initials are never stripped.
    Returns None when fewer than two tokens survive."""
    toks = [(a + s, b + s, t) for a, b, t in _tokens(text[s:e])]
    fg, sg, v = first_name_gazetteer(), surname_gazetteer(), _vocab()

    def junk(t: str) -> bool:
        w = ln(t)
        if len(w) <= 1 or w in fg or w in sg:
            return False
        if w in v or w in _AMBIGUOUS:
            return True
        if len(w) > 2 and t.isupper() and "." not in t:
            return True  # SHOUTED words ('RCSA', 'BOARD') are headings/acronyms, not names
        return looks_common(w)

    lo, hi = 0, len(toks)
    while hi - lo > 2 and junk(toks[lo][2]):
        lo += 1
    while hi - lo > 2 and junk(toks[hi - 1][2]):
        hi -= 1
    if hi - lo < 2:
        return None
    return toks[lo][0], toks[hi - 1][1]


@dataclass
class NameResult:
    cands: dict[int, list[Cand]]
    registry: Registry
    stats: dict[str, int]


def detect_people(nblocks: list[NBlock], ner: dict[int, list[Cand]], email_cands: dict[int, list[Cand]]) -> NameResult:
    reg = Registry()
    cands: dict[int, list[Cand]] = {}
    stats = {"pattern": 0, "ner": 0, "email": 0, "line": 0, "lexicon": 0, "rejected_ner": 0}
    gaz = first_name_gazetteer()

    def add(b: NBlock, s: int, e: int, conf: float, det: str, key: str = "") -> None:
        cands.setdefault(b.idx, []).append(Cand("PERSON", s, e, conf, det, key=key))

    strong_spans: dict[int, list[tuple[int, int]]] = {}

    def strong(b: NBlock, s: int, e: int) -> None:
        strong_spans.setdefault(b.idx, []).append((s, e))

    # ---- 1. context patterns -------------------------------------------------------------------------------
    for b in nblocks:
        t = b.text
        for rx, det, conf in ((P_ID, "pattern:name-before-id", 0.96), (P_HONORIFIC, "pattern:honorific", 0.9),
                              (P_TITLE_AFTER, "pattern:name-before-title", 0.88), (P_LABEL, "pattern:label", 0.9),
                              (P_CUE, "pattern:cue-word", 0.78)):
            for m in rx.finditer(t):
                s, e = m.start("n"), m.end("n")
                if det != "pattern:honorific":
                    tr = trim_span(t, s, e)
                    if tr is None:
                        continue
                    s, e = tr
                txt = t[s:e]
                if det == "pattern:honorific":
                    toks = _tokens(txt)
                    if _vocab_hit(txt) or any(ln(x) in _orgs() for _, _, x in toks) or any(ch.isdigit() for ch in txt):
                        continue
                elif not _plausible_name(txt):
                    continue
                elif det not in ("pattern:name-before-id",) and not accept_tokens(txt, reg.by_last.keys()):
                    continue
                add(b, s, e, conf, det)
                stats["pattern"] += 1
                strong(b, s, e)
                pn = parse_name(txt)
                if pn:
                    reg.add(*pn)
                elif det == "pattern:honorific":
                    toks = _tokens(txt)
                    if toks:
                        reg.add("", "", toks[-1][2])

    # ---- 3. e-mail derived surnames ------------------------------------------------------------------------
    hints: dict[str, set[str]] = {}
    for bidx, cs in email_cands.items():
        text = nblocks[bidx].text if bidx < len(nblocks) else ""
        for c in cs:
            local = text[c.start:c.end].split("@")[0].lower().strip("_.-")
            parts = [p for p in re.split(r"[._\-]+", local) if p]
            if len(parts) >= 2 and len(parts[-1]) >= 3 and parts[-1].isalpha():
                first = parts[0]
                if len(parts) == 2 and len(first) >= 1:
                    reg.add(first, "", parts[-1], strong=False)
                    hints.setdefault(ln(parts[-1]), set()).add(first[:1])
                    stats["email"] += 1
            elif len(parts) == 1 and parts[0].isalpha() and len(parts[0]) >= 5:
                reg.add(parts[0][:1], "", parts[0][1:], strong=False)
                hints.setdefault(ln(parts[0][1:]), set()).add(parts[0][:1])
                stats["email"] += 1

    # ---- 2. NER with rule-based filtering -------------------------------------------------------------------
    ner_kept: dict[int, list[Cand]] = {}
    for b in nblocks:
        for c in ner.get(b.idx, []):
            if c.type != "PERSON":
                continue
            txt = b.text[c.start:c.end]
            txt_clean = txt.strip(" \t.,;:()[]\"'")
            off = txt.find(txt_clean) if txt_clean else 0
            s, e = c.start + max(off, 0), c.start + max(off, 0) + len(txt_clean)
            if len(_tokens(txt_clean)) >= 2:
                tr = trim_span(b.text, s, e)
                if tr is None:
                    stats["rejected_ner"] += 1
                    continue
                s, e = tr
                txt_clean = b.text[s:e]
            toks = _tokens(txt_clean)
            single = len(toks) == 1
            ok = False
            if single:
                tn = ln(toks[0][2]) if toks else ""
                ok = bool(tn) and tn in reg.by_last and tn not in _vocab() and tn not in _AMBIGUOUS and len(tn) >= 4
            elif any(t[2].isupper() and len(ln(t[2])) >= 2 and "." not in t[2] and ln(t[2]) not in surname_gazetteer()
                     and ln(t[2]) not in gaz for t in toks):
                ok = False  # 'Completes RCSA', 'Hoh PS': shouted acronyms / OCR garbage are not names
            else:
                ok = (_plausible_name(txt_clean)
                      and not any(t[2].islower() for t in toks if ln(t[2]) not in {"van", "von", "de", "del", "der", "di", "da", "bin", "al", "el", "le", "la"})
                      and accept_tokens(txt_clean, reg.by_last.keys()))
            if not ok:
                stats["rejected_ner"] += 1
                continue
            conf = 0.62
            fn = ln(toks[0][2]) if toks else ""
            if not single and fn in gaz and len(fn) > 1:
                conf = 0.8
            ner_kept.setdefault(b.idx, []).append(Cand("PERSON", s, e, conf, c.detector))
            stats["ner"] += 1
    for bidx, cs in ner_kept.items():
        for c in cs:
            cands.setdefault(bidx, []).append(c)
            if c.conf >= 0.8:
                pn = parse_name(nblocks[bidx].text[c.start:c.end])
                if pn:
                    reg.add(*pn, strong=True)

    # ---- 4. stand-alone name-like lines (table cells, list items, lines inside OCR paragraphs) ----------------------
    for b in nblocks:
        pos = 0
        for line in b.text.split("\n"):
            ls = pos
            pos += len(line) + 1
            if not line.strip() or len(line) > 48:
                continue
            m = _NAME_LINE.match(line)
            if not m:
                continue
            txt = m.group("n")
            if not _plausible_name(txt) or not accept_tokens(txt, reg.by_last.keys()):
                continue
            toks = _tokens(txt)
            fn = ln(toks[0][2])
            ln_last = ln(toks[-1][2])
            score = 0.25  # shape alone is not evidence: below the review band unless something else agrees
            if fn in gaz:
                score += 0.30
            s0, e0 = ls + m.start("n"), ls + m.end("n")
            if any(c.type == "PERSON" and c.start <= s0 + 1 and c.end >= e0 - 1 for c in ner_kept.get(b.idx, [])):
                score += 0.25
            if ln_last in reg.by_last:
                score += 0.35
            if ln_last in surname_gazetteer():
                score += 0.15
            add(b, s0, e0, min(score, 0.95), "heuristic:name-line")
            stats["line"] += 1
            if score >= 0.8:
                pn = parse_name(txt)
                if pn:
                    reg.add(*pn, strong=True)

    # ---- 5. lexicon expansion: every spelling of every established person ------------------------------------
    index: dict[tuple[str, ...], tuple[str, float]] = {}
    for p in reg.persons.values():
        f, m, l = p.first, p.mid, p.last
        if len(l) < 4 and looks_common(l):
            continue
        if f and len(f) > 1:
            index[(f, l)] = (p.pid, 0.9)
            if m:
                index[(f, m, l)] = (p.pid, 0.92)
        if f:
            index[(f[:1], l)] = (p.pid, 0.8)
            if m:
                index[(f[:1], m, l)] = (p.pid, 0.85)
        # surname-only: only for distinctive surnames
        if len(l) >= 5 and l not in _AMBIGUOUS and l not in _vocab() and zipf(l) < 4.6:
            index[(l,)] = (p.pid, 0.7)
        elif len(l) >= 4 and l not in _AMBIGUOUS and l not in _vocab() and zipf(l) < 4.0 and not p.strong:
            index[(l,)] = (p.pid, 0.6)
        if f and len(f) >= 4 and f not in _AMBIGUOUS and f not in _vocab() and p.strong and zipf(f) < 4.6:
            index[(f,)] = (p.pid, 0.55)

    for b in nblocks:
        toks = _tokens(b.text)
        norm = [ln(t[2]) for t in toks]
        i = 0
        while i < len(toks):
            hit = None
            for n in (3, 2, 1):
                if i + n > len(toks):
                    continue
                win = norm[i:i + n]
                if n == 3:
                    key = (win[0], win[1][:1], win[2])
                else:
                    key = tuple(win)
                ent = index.get(key)
                if not ent:
                    continue
                # token-shape gates: a lexicon hit must still LOOK like a name in the text
                seg = b.text[toks[i][0]:toks[i + n - 1][1]]
                first_tok = toks[i][2]
                if n == 1:
                    if not (first_tok[0].isupper() and (first_tok[1:].islower() or first_tok.isupper() or "-" in first_tok)):
                        continue
                else:
                    if not all(t[2][0].isupper() for t in toks[i:i + n]):
                        continue
                hit = (n, ent, seg)
                break
            if hit:
                n, (pid, conf), seg = hit
                s = toks[i][0]
                e = toks[i + n - 1][1]
                if b.text[e - 1] == "." and len(toks[i + n - 1][2]) > 2:
                    e -= 1  # trailing sentence full-stop is not part of the name
                cands.setdefault(b.idx, []).append(Cand("PERSON", s, e, conf, "lexicon:variant", key=pid))
                reg.persons[pid].hits += 1
                stats["lexicon"] += 1
                i += n
                continue
            i += 1

    # attach identity keys to candidates that overlap a lexicon hit or can be parsed
    for bidx, cs in cands.items():
        b = nblocks[bidx]
        for c in cs:
            if c.key:
                continue
            pn = parse_name(b.text[c.start:c.end])
            if pn:
                first, _mid, last = pn
                p = reg.resolve_last(last, first[:1]) or reg.resolve_last(last)
                c.key = p.pid if p else f"{last}|{first[:1]}"
            else:
                toks = _tokens(b.text[c.start:c.end])
                if toks:
                    p = reg.resolve_last(toks[-1][2])
                    c.key = p.pid if p else f"{ln(toks[-1][2])}|"
    return NameResult(cands=cands, registry=reg, stats=stats)
