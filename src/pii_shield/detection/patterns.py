"""Deterministic detectors: regular expressions plus validators and context requirements.

Every detector works on NORMALISED text and returns Cand objects. Confidence reflects how specific the evidence is:
checksummed / strongly-shaped values score highest; shape + keyword context next; shape alone is low."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..settings import allowlist


@dataclass
class Cand:
    type: str
    start: int
    end: int
    conf: float
    detector: str
    note: str = ""
    key: str = ""  # identity key for stable tokens (e.g. one person, many spellings)

    def __len__(self) -> int:
        return self.end - self.start


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


# ------------------------------------------------------------------------------------------------ EMAIL
_EMAIL = re.compile(r"(?<![A-Za-z0-9.+\-])[A-Za-z0-9_.+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_EMAIL_OBF = re.compile(
    r"[A-Za-z0-9_.+\-]+\s*[\[(<{]\s*(?:at|AT)\s*[\])>}]\s*[A-Za-z0-9\-]+(?:\s*[\[(<{]\s*(?:dot|DOT)\s*[\])>}]\s*[A-Za-z0-9\-]+)+"
)
_EMAIL_SPACED = re.compile(
    r"[A-Za-z0-9_.+\-]{2,}(?:[ \t]@[ \t]?|@[ \t])[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}"
)  # OCR often inserts a space on either side of the @


def detect_email(t: str) -> list[Cand]:
    out = [Cand("EMAIL", m.start(), m.end(), 0.99, "regex:email") for m in _EMAIL.finditer(t)]
    out += [Cand("EMAIL", m.start(), m.end(), 0.9, "regex:email-obfuscated") for m in _EMAIL_OBF.finditer(t)]
    taken = [(c.start, c.end) for c in out]
    for m in _EMAIL_SPACED.finditer(t):
        if not any(s <= m.start() < e for s, e in taken):
            out.append(Cand("EMAIL", m.start(), m.end(), 0.85, "regex:email-ocr-space"))
    return out


# ------------------------------------------------------------------------------------------------ PHONE
_SEP = r"[ \t.–\-]"
_PHONE_INTL = re.compile(rf"(?<![\w+])\+\d{{1,3}}(?:{_SEP}?\(\d{{1,4}}\))?(?:{_SEP}?\d{{1,5}}){{1,5}}(?!\d)")
# NANP area codes never start with 0 or 1 ('123-456-7890' is an order/reference number, not a phone)
_PHONE_US = re.compile(r"(?<![\w+\-])(?:\([2-9]\d{2}\)[ \t]?|[2-9]\d{2}[\-. \t])\d{3}[\-. \t]\d{4}(?![\w\-])")
_PHONE_CTX = re.compile(
    r"(?i)\b(?:tel(?:ephone)?|phone|mobile|mob|cell|fax|whatsapp|direct line|direct dial|contact(?: number)?|call)\b\.?[ \t:]*"
    r"((?:\+\s?)?\(?\d[\d \t().\-]{6,18}\d)"
)
_YEAR_TAIL = re.compile(r"[ \t.\-](?:19|20|21)\d{2}$")


# A number wrapped onto the next line, e.g. "+1 (704)\n555-0166" or "+46 8\n5555 0121". The head before the newline
# must still be incomplete (< 8 digits), so a full number followed by an unrelated figure on the next line is not merged.
_WRAP = re.compile(r"((?<![\w+])\+\d{1,3}(?:[ \t.\-]?\(?\d{1,4}\)?){0,3}|(?<![\w(])\(\d{1,4}\))[ \t]*\n(?=[ \t]?\(?\d)")


def _unwrap(t: str) -> str:
    """Replace the line break inside a wrapped phone number with a space (same length, so offsets are unchanged)."""
    def fix(m: re.Match[str]) -> str:
        head = m.group(1)
        if len(_digits(head)) > 7:
            return m.group(0)
        return m.group(0).replace("\n", " ")
    return _WRAP.sub(fix, t)


def _nanp_trim(txt: str, s: int, e: int) -> tuple[str, int]:
    """+1 numbers have exactly 11 digits: a trailing 1-2 digit group belongs to the next table cell."""
    while txt.startswith("+1") and len(_digits(txt)) > 11 and re.search(r"[ \t.\-]\d{1,2}$", txt):
        cut = re.search(r"[ \t.\-]\d{1,2}$", txt).start()  # type: ignore[union-attr]
        txt, e = txt[:cut], s + cut
    return txt, e


# Prefix and continuation separated by layout: "+NN NN <neighbouring cell text>\nNNNN NNNN", or the prefix ends one OCR
# paragraph and the continuation starts the next. The head is exactly country code + one area group with nothing numeric
# after it on its line; the tail is digit groups at the very start of the next line.
_SPLIT_HEAD = re.compile(r"(?<![\w+])\+\d{1,3}(?:[ \t.\-]?\(\d{1,4}\)|[ \t.\-]\d{1,4})(?![\d%]|[ \t.\-]?\(?\d)")
_SPLIT_REST = re.compile(r"[^\n+@]{0,60}$")
_SPLIT_TAIL = re.compile(r"[ \t]*(\d{2,5}(?:[ \t.\-]\d{2,5}){0,3})(?![\w.\-]|[ \t]\d)")
_YEARISH = re.compile(r"(?:19|20)\d\d")


def split_phone_pair(a: str, b: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Head on the LAST line of `a`, tail at the start of the FIRST line of `b`. Returns ((hs, he), (ts, te)) as offsets
    into a and b, or None. Used within a block (consecutive lines) and across adjacent blocks on the same page."""
    line0 = a.rfind("\n") + 1
    last = a[line0:]
    head = None
    for m in _SPLIT_HEAD.finditer(last):
        # the rest of the line is the neighbouring cell: words or IDs ('VND-ABC-123') are fine, a bare number is not
        rest = last[m.end():]
        if _SPLIT_REST.fullmatch(rest) and not any(re.fullmatch(r"[\d\W]*\d[\d\W]*", w) for w in rest.split()):
            head = m
    if head is None:
        return None
    first = b.split("\n", 1)[0]
    tm = _SPLIT_TAIL.match(first)
    if tm is None:
        return None
    hd = _digits(head.group(0))
    nanp = hd.startswith("1") and len(hd) <= 4
    groups = re.findall(r"\d+", tm.group(1))
    seps = [g.end() for g in re.finditer(r"\d+", tm.group(1))]
    # drop trailing groups that belong to the next cell ('555-0147 03/14/2026' -> '555-0147')
    while len(groups) > 1 and (len(hd) + sum(map(len, groups)) > (11 if nanp else 15)):
        groups.pop()
        seps.pop()
    if all(_YEARISH.fullmatch(g) for g in groups):
        return None  # "2025 2026" is a pair of years, not a subscriber number
    td = "".join(groups)
    n = len(hd) + len(td)
    if len(td) < 6 or not 8 <= n <= 15 or (nanp and n != 11):
        return None
    return (line0 + head.start(), line0 + head.end()), (tm.start(1), tm.start(1) + seps[-1])


def _split_cands(t: str) -> list[Cand]:
    out: list[Cand] = []
    starts = [0] + [i + 1 for i, ch in enumerate(t) if ch == "\n"]
    for i in range(len(starts) - 1):
        a = t[starts[i]:starts[i + 1] - 1]
        b = t[starts[i + 1]:]
        pair = split_phone_pair(a, b)
        if pair:
            (hs, he), (ts, te) = pair
            out += phone_split_cands((starts[i] + hs, starts[i] + he, a[hs:he]), (starts[i + 1] + ts, starts[i + 1] + te, b[ts:te]))
    return out


def phone_split_cands(head: tuple[int, int, str], tail: tuple[int, int, str]) -> list[Cand]:
    """Two PHONE candidates sharing one identity key, so both halves get the same stable token."""
    key = _digits(head[2] + tail[2])
    return [Cand("PHONE", head[0], head[1], 0.93, "regex:phone-split", key=key),
            Cand("PHONE", tail[0], tail[1], 0.93, "regex:phone-split", key=key)]


def detect_phone(t: str) -> list[Cand]:
    out: list[Cand] = []
    t = _unwrap(t)
    out += _split_cands(t)
    for m in _PHONE_INTL.finditer(t):
        s, e = m.start(), m.end()
        txt = t[s:e]
        txt, e = _nanp_trim(txt, s, e)
        # drop a trailing year-like group that belongs to the next cell (e.g. "+44 20 NNNN NNNN 2026")
        while len(_digits(txt)) > 11 and _YEAR_TAIL.search(txt):
            cut = _YEAR_TAIL.search(txt).start()  # type: ignore[union-attr]
            txt, e = txt[:cut], s + cut
        while len(_digits(txt)) > 15 and re.search(r"[ \t.\-]\d+$", txt):
            cut = re.search(r"[ \t.\-]\d+$", txt).start()  # type: ignore[union-attr]
            txt, e = txt[:cut], s + cut
        n = len(_digits(txt))
        if 8 <= n <= 15:
            out.append(Cand("PHONE", s, e, 0.97, "regex:phone-intl"))
    for m in _PHONE_US.finditer(t):
        out.append(Cand("PHONE", m.start(), m.end(), 0.9, "regex:phone-us"))
    for m in _PHONE_CTX.finditer(t):
        n = len(_digits(m.group(1)))
        if 7 <= n <= 15:
            out.append(Cand("PHONE", m.start(1), m.end(1), 0.88, "regex:phone-context"))
    for m in _PHONE_UK.finditer(t):
        out.append(Cand("PHONE", m.start(), m.end(), 0.88, "regex:phone-uk-mobile"))
    for m in _PHONE_IN.finditer(t):
        # a bare 10-digit run starting 6-9 could also be an account or order number: weaker without the prefix
        out.append(Cand("PHONE", m.start(), m.end(), 0.85 if m.group(1) else 0.7, "regex:phone-in-mobile"))
    return out


_PHONE_UK = re.compile(r"(?<!\d)(?:\+44[ \t]?7\d{3}|\(?07\d{3}\)?)[ \t]?\d{3}[ \t]?\d{3}(?!\d)")
_PHONE_IN = re.compile(r"(?<![\d+])(\+91[ \t\-]?|0)?[6-9]\d{4}[ \t\-]?\d{5}(?!\d)")


# ------------------------------------------------------------------------------------------------ EMPLOYEE ID
_EMP = re.compile(r"(?<![A-Za-z0-9])(?:EMP|DIR|EID|STF|WRK)[ \t]?[\-–_][ \t]?[0-9OoIlSB]{4,8}(?![A-Za-z0-9])")
_EMP_CTX = re.compile(
    r"(?i)\b(?:employee|staff|badge|personnel|worker|emp)[ \t]*(?:id|number|no\.?|#)[ \t]*[:#]?[ \t]*([A-Z]{0,4}[\-]?\d{4,10})\b"
)


_WORKER = re.compile(r"(?<![A-Za-z0-9\-])[A-Z]{3}-[A-Z]{2}-\d{4}(?![A-Za-z0-9\-])")  # contingent worker IDs, e.g. MER-IN-4471


def detect_employee_id(t: str) -> list[Cand]:
    out: list[Cand] = [Cand("EMPLOYEE_ID", m.start(), m.end(), 0.6, "regex:worker-id") for m in _WORKER.finditer(t)]
    for m in _EMP.finditer(t):
        digits = sum(ch.isdigit() for ch in m.group(0))
        if digits >= 3:
            out.append(Cand("EMPLOYEE_ID", m.start(), m.end(), 0.97 if digits >= 4 else 0.85, "regex:employee-id"))
    for m in _EMP_CTX.finditer(t):
        out.append(Cand("EMPLOYEE_ID", m.start(1), m.end(1), 0.88, "regex:employee-id-context"))
    return out


# ------------------------------------------------------------------------------------------------ SSN
_SSN = re.compile(r"(?<![\d\-])\d{3}[ \t]?[\-–][ \t]?\d{2}[ \t]?[\-–][ \t]?\d{4}(?![\d\-])")
_SSN_SPACE = re.compile(r"(?<![\d\-])\d{3} \d{2} \d{4}(?![\d\-])")
_SSN_CTX_FULL = re.compile(r"(?i)\b(?:social security(?: number)?|SSN|SS#)\b[^\n]{0,25}?(\d{9})(?!\d)")
_SSN_LAST4_A = re.compile(
    r"(?i)last (?:four|4)(?: digits?)?(?: of)?[ \t]+(?:your |our |the |their |his |her )?(?:social security(?: number)?|SSN)[^()\n]{0,20}?\(?(\d{4})\)?(?!\d)"
)
_SSN_LAST4_B = re.compile(
    r"(?i)\b(?:social security(?: number)?|SSN)\b[ \t]*(?:ending(?: in)?|last (?:four|4)(?: digits)?|\(last (?:four|4)\)|xxx-xx-)[ \t]*[:\-]?[ \t]*(\d{4})(?!\d)"
)
_SSN_MASKED = re.compile(r"(?i)(?:XXX|\*{3})[\-– ](?:XX|\*{2})[\-– ](\d{4})(?!\d)")


def _ssn_ok(s: str) -> bool:
    """SSA never issues area 000/666, group 00 or serial 0000. Area 9xx is kept: ITINs and synthetic test SSNs live there."""
    d = _digits(s)
    return d[:3] not in ("000", "666") and d[3:5] != "00" and d[5:] != "0000"


def detect_ssn(t: str) -> list[Cand]:
    out = [Cand("SSN", m.start(), m.end(), 0.95, "regex:ssn") for m in _SSN.finditer(t) if _ssn_ok(m.group(0))]
    for m in _SSN_SPACE.finditer(t):
        if not _ssn_ok(m.group(0)):
            continue
        ctx = t[max(0, m.start() - 40):m.start()].lower()
        out.append(Cand("SSN", m.start(), m.end(), 0.9 if ("social" in ctx or "ssn" in ctx) else 0.5, "regex:ssn-spaced"))
    for rx, name, conf in ((_SSN_CTX_FULL, "ssn-context-9", 0.9), (_SSN_LAST4_A, "ssn-last4", 0.9),
                           (_SSN_LAST4_B, "ssn-last4", 0.9), (_SSN_MASKED, "ssn-masked-last4", 0.85)):
        for m in rx.finditer(t):
            out.append(Cand("SSN", m.start(1), m.end(1), conf, f"regex:{name}"))
    return out


# ------------------------------------------------------------------------------------------------ TAX ID (PAN-style)
_PAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{5}[0-9]{4}[A-Z](?![A-Za-z0-9])")
_PAN_CTX = re.compile(
    r"(?i)\b(?:PAN|permanent account number|tax (?:id|identifier|identification number|number)|TIN|national tax(?: id(?:entifier)?)?)\b"
    r"[ \t:#\-]{0,6}\(?([A-Z0-9]{10})\)?(?![A-Za-z0-9])"
)


def detect_tax_id(t: str) -> list[Cand]:
    out = [Cand("TAX_ID", m.start(), m.end(), 0.9, "regex:pan-shape") for m in _PAN.finditer(t)]
    for m in _PAN_CTX.finditer(t):
        v = m.group(1)
        if sum(ch.isdigit() for ch in v) >= 3 and sum(ch.isalpha() for ch in v) >= 4:
            out.append(Cand("TAX_ID", m.start(1), m.end(1), 0.92, "regex:pan-context"))
    return out


# ------------------------------------------------------------------------------------------------ PASSPORT
_PASSPORT_CTX = re.compile(
    r"(?i)\bpassport\b(?:[ \t]*(?:no\.?|number|#|n°))?[ \t]*[:#\-]?[ \t]*([A-Z]{1,2}[0-9]{6,9}|[A-Z0-9]{7,9})\b"
)
_PASSPORT_SHAPE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}[0-9]{7}(?![A-Za-z0-9])")


def detect_passport(t: str) -> list[Cand]:
    out: list[Cand] = []
    for m in _PASSPORT_CTX.finditer(t):
        v = m.group(1)
        if sum(ch.isdigit() for ch in v) >= 5:
            out.append(Cand("PASSPORT", m.start(1), m.end(1), 0.92, "regex:passport-context"))
    for m in _PASSPORT_SHAPE.finditer(t):
        out.append(Cand("PASSPORT", m.start(), m.end(), 0.4, "regex:passport-shape", "shape only"))
    return out


# ------------------------------------------------------------------------------------------------ DATE OF BIRTH
_MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_DATE = re.compile(
    rf"(?:\b\d{{1,2}}(?:st|nd|rd|th)?[ \t]+{_MONTH}\.?,?[ \t]+\d{{4}}\b"
    rf"|\b{_MONTH}\.?[ \t]+\d{{1,2}}(?:st|nd|rd|th)?,?[ \t]+\d{{4}}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/.\-]\d{1,2}[/.\-](?:19|20)\d{2}\b)"
)
_DOB_BEFORE = re.compile(r"(?i)(?:\bDOB\b|\bD\.O\.B\.?|date of birth|birth ?date|\bborn(?: on)?\b|birthday)[^\n]{0,20}$")
_DOB_AFTER = re.compile(r"(?i)^[ \t]*[\)\],;:]?[ \t]*\(?(?:DOB|D\.O\.B|born|date of birth)")


def detect_dob(t: str) -> list[Cand]:
    out: list[Cand] = []
    for m in _DATE.finditer(t):
        before = t[max(0, m.start() - 40):m.start()]
        after = t[m.end():m.end() + 25]
        if _DOB_BEFORE.search(before) or _DOB_AFTER.search(after):
            out.append(Cand("DATE_OF_BIRTH", m.start(), m.end(), 0.93, "regex:dob-context"))
    return out


# ------------------------------------------------------------------------------------------------ ADDRESS
_STREET = (r"(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Lane|Ln\.?|Drive|Dr\.?|Crescent|Cres\.?|Boulevard|Blvd\.?|Court|Ct\.?|Way|"
           r"Place|Pl\.?|Terrace|Square|Close|Gardens|Grove|Highway|Hwy\.?|Parkway|Pkwy\.?|Row|Mews)")
_ADDR = re.compile(
    rf"\b\d{{1,5}}[A-Za-z]?[ \t]+(?:[A-Z][\w'’.\-]*[ \t]+){{1,4}}{_STREET}\b\.?"
    r"(?:,?[ \t]*(?:Apartment|Apt\.?|Suite|Ste\.?|Unit|Flat|Floor|Fl\.?|#)[ \t]*[\w\-]+)?"
    r"(?:,[ \t]*[A-Z][A-Za-z.\-]+(?:[ \t][A-Z][A-Za-z.\-]+){0,2})?"
    r"(?:,[ \t]*[A-Z]{2}\b)?"
    r"(?:[ \t]+\d{5}(?:-\d{4})?\b|[ \t]+[A-Z]{1,2}\d[A-Z\d]?[ \t]?\d[A-Z]{2}\b)?"
)
_POBOX = re.compile(r"(?i)\bP\.?[ \t]?O\.?[ \t]?Box[ \t]+\d{1,6}\b")


def detect_address(t: str) -> list[Cand]:
    corp = [a.lower() for a in allowlist().get("corporate_addresses", [])]
    out: list[Cand] = []
    for m in _ADDR.finditer(t):
        txt = m.group(0).lower()
        if any(txt.startswith(c) for c in corp):
            continue  # published corporate address: not personal data (deployment allow-list)
        # a bare "123 Main Street" is weaker than one with locality/unit/postcode
        rich = ("," in m.group(0)) or bool(re.search(r"\d{5}|apartment|apt|suite|unit|flat", txt))
        ctx = t[max(0, m.start() - 45):m.start()].lower()
        home = any(w in ctx for w in ("home", "address", "resid", "lives", "living", "mailing", "reside"))
        out.append(Cand("ADDRESS", m.start(), m.end(), 0.9 if (rich or home) else 0.7, "regex:street-address"))
    for m in _POBOX.finditer(t):
        out.append(Cand("ADDRESS", m.start(), m.end(), 0.8, "regex:po-box"))
    return out


# ------------------------------------------------------------------------------------------------ FINANCIAL ACCOUNT
_CARD_FRAG = re.compile(
    r"(?i)\b(?:card|credit card|debit card|platinum card|visa|mastercard|amex)\b[^.\n]{0,35}?"
    r"\b(?:ending(?: in)?|last (?:four|4)(?: digits)?(?: of)?|xxxx|\*{4})[ \t:]*(\d{4})\b"
)
_ACCT_FRAG = re.compile(
    r"(?i)\b(?:account|acct|a/c)\b[^.\n]{0,45}?\b(?:ending(?: in)?|last (?:four|4)(?: digits)?(?: of)?)[ \t:]*(\d{4})\b"
)
_ACCT_NUM = re.compile(r"(?i)\b(?:account|acct|a/c)[ \t]*(?:no\.?|number|#)[ \t]*[:#]?[ \t]*(\d[\d\- ]{5,22}\d)\b")
_CARD_FULL = re.compile(r"(?<![\d\-])(?:\d[ \-]?){12,18}\d(?![\d\-])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")


def _luhn(num: str) -> bool:
    d = [int(c) for c in num][::-1]
    s = sum(d[0::2]) + sum(sum(divmod(x * 2, 10)) for x in d[1::2])
    return s % 10 == 0


def _iban_ok(s: str) -> bool:
    s = s.replace(" ", "")
    if not (15 <= len(s) <= 34):
        return False
    r = s[4:] + s[:4]
    conv = "".join(str(int(c, 36)) for c in r)
    return int(conv) % 97 == 1


def detect_financial(t: str) -> list[Cand]:
    out: list[Cand] = []
    for rx, name in ((_CARD_FRAG, "card-fragment"), (_ACCT_FRAG, "account-fragment")):
        for m in rx.finditer(t):
            out.append(Cand("FINANCIAL_ACCOUNT", m.start(1), m.end(1), 0.9, f"regex:{name}"))
    for m in _ACCT_NUM.finditer(t):
        out.append(Cand("FINANCIAL_ACCOUNT", m.start(1), m.end(1), 0.9, "regex:account-number"))
    for m in _CARD_FULL.finditer(t):
        digits = _digits(m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            out.append(Cand("FINANCIAL_ACCOUNT", m.start(), m.end(), 0.96, "regex:card-luhn"))
    for m in _IBAN.finditer(t):
        if _iban_ok(m.group(0)):
            out.append(Cand("FINANCIAL_ACCOUNT", m.start(), m.end(), 0.97, "regex:iban-mod97"))
    return out


# ------------------------------------------------------------------------------------------------ IP
# Octets are 1-3 digits checked numerically (zero-padded '203.000.113.045' is valid). (?![\d.]\d): a full stop after the
# address ends the sentence, it does not make it a version number. A letter before it ('2O3.0.113.45') is OCR noise in
# the first octet: the clean rule must not mask only the tail, the OCR rule below takes the whole thing.
_IPV4 = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.]\d|\d)")
# OCR damage: a space next to a dot, a comma for a dot, O/o for 0, l/I/| for 1.
_IPV4_OCR = re.compile(r"(?<![\w.,])[\dOolI|]{1,3}(?:[ \t]?[.,][ \t]?[\dOolI|]{1,3}){3}(?![\w]|[.,]\d)")
_OCR_DIGIT = str.maketrans("OolI|", "00111")
_IP_CTX = re.compile(r"(?i)\b(?:ip|ipv4|address|addr|host|server|source|src|dst|destination|from|login|client|gateway)\b[^\n]{0,25}$")
# IPv6: any hex/colon run with '::' or 7 colons, then the stdlib parser decides (covers every compressed form).
_IPV6 = re.compile(r"(?<![\w:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:])")
_MAC = re.compile(r"(?<![\w:\-])(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}(?![\w:\-])")


def _ipv4_ok(octets: list[str]) -> bool:
    return len(octets) == 4 and all(o.isdigit() and int(o) <= 255 for o in octets) and octets[0] not in ("0", "00", "000", "127") \
        and octets != ["255"] * 4


def detect_ip(t: str) -> list[Cand]:
    import ipaddress

    out = []
    clean: list[tuple[int, int]] = []
    for m in _IPV4.finditer(t):
        if _ipv4_ok(m.group(0).split(".")):
            clean.append((m.start(), m.end()))
            # '4.2.1.3' is far more often a section/version number than an address: short ones need IP context
            if sum(ch.isdigit() for ch in m.group(0)) < 7 and not _IP_CTX.search(t[max(0, m.start() - 30):m.start()]):
                continue
            out.append(Cand("IP_ADDRESS", m.start(), m.end(), 0.6, "regex:ipv4"))
    for m in _IPV4_OCR.finditer(t):
        if any(s <= m.start() < e for s, e in clean):
            continue
        octets = re.split(r"[ \t]?[.,][ \t]?", m.group(0).translate(_OCR_DIGIT))
        if not _ipv4_ok(octets) or sum(len(o) for o in octets) < 7:
            continue  # '1. 2. 3. 4' is a numbered list, not an address
        # damaged text is weaker evidence: masked with IP context, otherwise it sends the document to review
        ctx = bool(_IP_CTX.search(t[max(0, m.start() - 30):m.start()]))
        out.append(Cand("IP_ADDRESS", m.start(), m.end(), 0.7 if ctx else 0.4, "regex:ipv4-ocr"))
    for m in _IPV6.finditer(t):
        v = m.group(0)
        if ("::" not in v and v.count(":") != 7) or not any(ch.isdigit() for ch in v):
            continue  # '10:30:45' is a time
        try:
            ip = ipaddress.IPv6Address(v)
        except ValueError:
            continue
        if not ip.is_loopback and not ip.is_unspecified:
            out.append(Cand("IP_ADDRESS", m.start(), m.end(), 0.8, "regex:ipv6"))
    for m in _MAC.finditer(t):
        out.append(Cand("TECH_ID", m.start(), m.end(), 0.85, "regex:mac-address"))
    return out


# ------------------------------------------------------------------------------------------------ OBFUSCATED E-MAIL (words)
_EMAIL_WORDS = re.compile(r"(?i)\b[\w.+\-]+[ \t]+at[ \t]+[\w\-]+[ \t]+dot[ \t]+[a-z]{2,}\b")


def detect_email_words(t: str) -> list[Cand]:
    """'jane.doe at example dot com' (the bracketed '[at]' form is detect_email's)."""
    return [Cand("EMAIL", m.start(), m.end(), 0.9, "regex:email-obfuscated-words") for m in _EMAIL_WORDS.finditer(t)]


# ------------------------------------------------------------------------------------------------ NATIONAL IDS (GOV_ID)
_VD = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
       [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
       [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VP = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
       [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def _verhoeff(s: str) -> bool:
    d = _digits(s)
    c = 0
    for i, ch in enumerate(reversed(d)):
        c = _VD[c][_VP[i % 8][int(ch)]]
    return len(d) == 12 and c == 0


def _sin_ok(s: str) -> bool:
    d = _digits(s)
    t = 0
    for i, ch in enumerate(d):
        x = int(ch) * (2 if i % 2 else 1)
        t += x - 9 if x > 9 else x
    return len(d) == 9 and t % 10 == 0


_AADHAAR = re.compile(r"(?<![\d\-])[2-9]\d{3}[ \t\-]?\d{4}[ \t\-]?\d{4}(?![\d\-])")
_NINO = re.compile(r"\b(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z] ?\d{2} ?\d{2} ?\d{2} ?[A-D]\b")
_SIN = re.compile(r"(?<![\d\-])\d{3}[ \t\-]\d{3}[ \t\-]\d{3}(?![\d\-])")
_SIN_CTX = re.compile(r"(?i)\b(?:SIN|social insurance(?: number)?|NAS)\b[^\n]{0,20}$")
_GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")


def detect_gov_id(t: str) -> list[Cand]:
    out = [Cand("GOV_ID", m.start(), m.end(), 0.92, "regex:aadhaar-verhoeff") for m in _AADHAAR.finditer(t) if _verhoeff(m.group(0))]
    out += [Cand("GOV_ID", m.start(), m.end(), 0.92, "regex:uk-nino") for m in _NINO.finditer(t)]
    for m in _SIN.finditer(t):
        if _sin_ok(m.group(0)):
            # Luhn passes for 1 in 10 random 9-digit numbers: without 'SIN' context it only sends the document to review
            ctx = bool(_SIN_CTX.search(t[max(0, m.start() - 30):m.start()]))
            out.append(Cand("GOV_ID", m.start(), m.end(), 0.9 if ctx else 0.4, "regex:ca-sin"))
    out += [Cand("TAX_ID", m.start(), m.end(), 0.92, "regex:gstin") for m in _GSTIN.finditer(t)]
    return out


# ------------------------------------------------------------------------------------------------ MORE FINANCIAL
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BTC_B58 = re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")
_BTC_BECH32 = re.compile(r"\bbc1[ac-hj-np-z02-9]{25,59}\b")
_ETH = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
_SWIFT = re.compile(r"\b[A-Z]{4}(?:AU|BE|BR|CA|CH|CN|DE|ES|FR|GB|HK|IE|IN|IT|JP|NL|SG|US)[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")
_SWIFT_CTX = re.compile(r"(?i)\b(?:swift|bic)\b[^\n]{0,15}$")
_ABA = re.compile(r"(?i)\b(?:routing|aba|rtn)\b\W{0,10}(\d{9})\b")
_ACCT_CTX = re.compile(r"(?i)\b(?:a/c|acct?|account)\W{0,6}(?:no\.?|number|#)?\W{0,4}(\d{8,18})\b")


def _base58check(s: str) -> bool:
    import hashlib

    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    raw = b"\x00" * (len(s) - len(s.lstrip("1"))) + raw
    if len(raw) < 5:
        return False
    return hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] == raw[-4:]


def _aba_ok(s: str) -> bool:
    d = _digits(s)
    return len(d) == 9 and sum(int(a) * b for a, b in zip(d, [3, 7, 1] * 3)) % 10 == 0


def detect_financial_extra(t: str) -> list[Cand]:
    out = [Cand("FINANCIAL_ACCOUNT", m.start(), m.end(), 0.85, "regex:btc-base58check") for m in _BTC_B58.finditer(t)
           if _base58check(m.group(0))]
    out += [Cand("FINANCIAL_ACCOUNT", m.start(), m.end(), 0.8, "regex:btc-bech32") for m in _BTC_BECH32.finditer(t)]
    out += [Cand("FINANCIAL_ACCOUNT", m.start(), m.end(), 0.85, "regex:eth-address") for m in _ETH.finditer(t)]
    out += [Cand("FINANCIAL_ACCOUNT", m.start(), m.end(), 0.88, "regex:ifsc") for m in _IFSC.finditer(t)]
    for m in _SWIFT.finditer(t):
        ctx = bool(_SWIFT_CTX.search(t[max(0, m.start() - 20):m.start()]))
        if ctx:
            out.append(Cand("FINANCIAL_ACCOUNT", m.start(), m.end(), 0.88, "regex:swift-bic"))
        elif any(ch.isdigit() for ch in m.group(0)):  # all-letter shapes are mostly SHOUTED headings: ignore them
            out.append(Cand("FINANCIAL_ACCOUNT", m.start(), m.end(), 0.4, "regex:swift-bic-shape"))
    out += [Cand("FINANCIAL_ACCOUNT", m.start(1), m.end(1), 0.9, "regex:aba-routing") for m in _ABA.finditer(t) if _aba_ok(m.group(1))]
    out += [Cand("FINANCIAL_ACCOUNT", m.start(1), m.end(1), 0.88, "regex:account-context") for m in _ACCT_CTX.finditer(t)]
    return out


# ------------------------------------------------------------------------------------------------ POSTAL CODES (ADDRESS)
_UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?[ \t]?\d[A-Z]{2}\b")
_US_STATES = frozenset(re.findall(r"[A-Z]{2}", "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE "
                                              "NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR"))
_US_ZIP = re.compile(r"(,[ \t]*)?\b([A-Z]{2})[ \t](\d{5}(?:-\d{4})?)\b")
_PIN_CTX = re.compile(r"(?i)\b(?:pin(?:code)?|postal code)\W{0,4}([1-9]\d{5})\b")
_ADDR_CTX = re.compile(r"(?i)\b(?:home|address|resid|lives|living|mailing|reside|post ?code)")


def detect_postal(t: str) -> list[Cand]:
    """A postcode alone is weak (offices have them too): masked with address context or after 'City,', else review."""
    out: list[Cand] = []
    for m in _UK_POSTCODE.finditer(t):
        ctx = bool(_ADDR_CTX.search(t[max(0, m.start() - 45):m.start()]))
        out.append(Cand("ADDRESS", m.start(), m.end(), 0.8 if ctx else 0.4, "regex:uk-postcode"))
    for m in _US_ZIP.finditer(t):
        if m.group(2) in _US_STATES:
            ctx = bool(m.group(1)) or bool(_ADDR_CTX.search(t[max(0, m.start() - 45):m.start()]))
            out.append(Cand("ADDRESS", m.start(2), m.end(3), 0.75 if ctx else 0.4, "regex:us-state-zip"))
    out += [Cand("ADDRESS", m.start(1), m.end(1), 0.8, "regex:in-pincode") for m in _PIN_CTX.finditer(t)]
    return out


# ------------------------------------------------------------------------------------------------ PASSPORT / VEHICLE / VIN (gated)
_IN_PASSPORT = re.compile(r"\b[A-PR-WY][1-9]\d{5}[1-9]\b")
_PASSPORT_CTX2 = re.compile(r"(?i)\bpassport\W{0,10}(?:no\.?|number|#)?\W{0,4}([A-Z0-9]{6,9})\b")
_PLATE = re.compile(r"\b[A-Z]{2}[ \-]?\d{1,2}[ \-]?[A-Z]{1,3}[ \-]?\d{4}\b")
_VIN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
_VEHICLE_CTX = re.compile(r"(?i)\b(?:vin|vehicle|car|chassis|registration|reg(?:\.|istration)? no|plate|licen[cs]e plate)\b[^\n]{0,20}$")


def detect_passport_vehicle(t: str) -> list[Cand]:
    out: list[Cand] = []
    for m in _PASSPORT_CTX2.finditer(t):
        if sum(ch.isdigit() for ch in m.group(1)) >= 5:  # 'Passport number process' is a word, not a number
            out.append(Cand("PASSPORT", m.start(1), m.end(1), 0.92, "regex:passport-context"))
    out += [Cand("PASSPORT", m.start(), m.end(), 0.4, "regex:in-passport-shape") for m in _IN_PASSPORT.finditer(t)]
    for rx, name, strong in ((_PLATE, "vehicle-plate", 0.85), (_VIN, "vin", 0.85)):
        for m in rx.finditer(t):
            v = m.group(0)
            if name == "vin" and not (any(ch.isdigit() for ch in v) and any(ch.isalpha() for ch in v)):
                continue
            ctx = bool(_VEHICLE_CTX.search(t[max(0, m.start() - 30):m.start()]))
            if ctx:
                out.append(Cand("TECH_ID", m.start(), m.end(), strong, f"regex:{name}"))
            elif name == "vehicle-plate":
                out.append(Cand("TECH_ID", m.start(), m.end(), 0.4, f"regex:{name}-shape"))
            # a bare 17-character code is far more often a document/hash id than a VIN: no candidate without context
    return out


# ------------------------------------------------------------------------------------------------ SECRETS
_SECRETS = [
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA)[A-Z0-9]{16}\b"), 0.98),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"), 0.98),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}(?![0-9A-Za-z_\-])"), 0.97),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,72}\b"), 0.97),
    ("stripe-key", re.compile(r"\b[sr]k_(?:live|test)_[0-9A-Za-z]{16,99}\b"), 0.97),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), 0.97),
    ("private-key-block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----"), 0.99),
    ("url-credentials", re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@[^\s/]+"), 0.95),
    ("url-token-param", re.compile(r"(?i)[?&](?:token|api[_\-]?key|access[_\-]?token|secret|sig|password)=[^&\s]{6,}"), 0.9),
]
_SECRET_ASSIGN = re.compile(r"(?i)\b(?:password|passwd|pwd|secret|api[_\-]?key|token)[ \t]*[:=][ \t]*['\"]?([^\s'\"]{6,})")


def detect_secret(t: str) -> list[Cand]:
    out = [Cand("SECRET", m.start(), m.end(), conf, f"regex:{name}") for name, rx, conf in _SECRETS for m in rx.finditer(t)]
    for m in _SECRET_ASSIGN.finditer(t):
        v = m.group(1)
        # policy prose ('Password: minimum 12 characters') has plain words; a credential has digits or symbols,
        # and a placeholder ('********', 'xxxxxx') is not one
        if v.isalpha() or not set(v.lower()) - set("*x•."):
            continue
        out.append(Cand("SECRET", m.start(1), m.end(1), 0.85, "regex:secret-assignment"))
    return out


# ------------------------------------------------------------------------------------------------ GENERIC ID (catch-all)
# Any PREFIX[-_/]...[-_/]digits code ('CUST-48213', 'HR/EMP/2291'). Lowest fusion priority, so a specific type claiming the
# same characters wins. Reference prefixes listed as non-PII in the allowlist and standards bodies are skipped.
GENERIC_ID = re.compile(r"\b[A-Z]{2,6}(?:[-_/][A-Z0-9]{1,6}){0,3}[-_/]\d{3,10}\b")
_STANDARD_PREFIXES = frozenset({"ISO", "IEC", "NIST", "SOC", "PCI", "GDPR", "CVE", "RFC"})


def detect_generic_id(t: str) -> list[Cand]:
    skip = _STANDARD_PREFIXES | {p.upper() for p in allowlist().get("non_pii_id_prefixes", [])}
    return [Cand("GENERIC_ID", m.start(), m.end(), 0.6, "regex:generic-id") for m in GENERIC_ID.finditer(t)
            if re.split(r"[-_/]", m.group(0))[0] not in skip]


def run_patterns(t: str) -> list[Cand]:
    out: list[Cand] = []
    for fn in (detect_email, detect_email_words, detect_phone, detect_employee_id, detect_ssn, detect_tax_id, detect_passport,
               detect_dob, detect_address, detect_financial, detect_ip, detect_gov_id, detect_financial_extra, detect_postal,
               detect_passport_vehicle, detect_secret, detect_generic_id):
        out.extend(fn(t))
    return out
