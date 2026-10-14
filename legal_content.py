"""
MFA DealPick - legal content
Deterministic, state-aware templates for used-car sale agreements (Tamil Nadu, Kerala)
and the six notice types a used-car dealer most often needs.

Documents use a tiny markup that docgen.py lays out:
  # Title            centred, large      ## Heading   centred, bold
  ### Clause head    left, bold          N. text      numbered paragraph (hanging indent)
  (a) text           sub-item            - text       bullet
  |a|b|c             bordered table row  |~a|b        borderless table row
  >> text            right-aligned       ~~           page break
  **bold** inline.   Anything else is a justified paragraph.

These are drafting aids, not legal advice. Notices must be approved by an advocate
(enforced in dealpick_app.py); agreements should be reviewed by one before first use.
"""

import datetime as _dt

_IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))

STATES = {
    "TN": {
        "name": "Tamil Nadu",
        "authority": "Regional Transport Office (RTO) of the Transport Department, Government of Tamil Nadu",
        "authority_short": "jurisdictional Regional Transport Office (RTO) in Tamil Nadu",
        "tax_act": "the Tamil Nadu Motor Vehicles Taxation Act, 1974",
        "stamp_act": "the Indian Stamp Act, 1899 as in force in the State of Tamil Nadu",
        "hc": "the High Court of Judicature at Madras",
        "lang": "Tamil",
        "default_city": "Chennai",
    },
    "KL": {
        "name": "Kerala",
        "authority": "Regional Transport Office (RTO) or Sub Regional Transport Office of the Motor Vehicles Department, Government of Kerala",
        "authority_short": "jurisdictional Regional Transport Office (RTO) or Sub RTO in Kerala",
        "tax_act": "the Kerala Motor Vehicles Taxation Act, 1976",
        "stamp_act": "the Kerala Stamp Act, 1959",
        "hc": "the High Court of Kerala",
        "lang": "Malayalam",
        "default_city": "Kochi",
    },
}
STATE_LABELS = {"TN": "Tamil Nadu", "KL": "Kerala", "OT": "another state"}

# ---------------------------------------------------------------- formatting helpers

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
         "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
         "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n):
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def amount_words(n):
    n = int(round(float(n or 0)))
    if n == 0:
        return "Zero"
    parts = []
    for div, name in ((10 ** 7, "Crore"), (10 ** 5, "Lakh"), (1000, "Thousand"), (100, "Hundred")):
        q, n = divmod(n, div)
        if q:
            parts.append(f"{amount_words(q) if q >= 100 else _two(q)} {name}")
    if n:
        parts.append(_two(n))
    return " ".join(parts)


def num(v, default=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def inr(n):
    n = int(round(num(n)))
    s = str(abs(n))
    if len(s) > 3:
        head, tail, groups = s[:-3], s[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return ("-" if n < 0 else "") + "Rs. " + s + "/-"


def inr_words(n):
    return f"{inr(n)} (Rupees {amount_words(n)} only)"


def today_ist():
    """Today's date in India. Servers run on UTC, which is a day behind India for the first 5.5 hours of each day."""
    return _dt.datetime.now(_IST).date()


def ist_date(ts):
    """'2026-10-13T20:00:00Z' (UTC timestamp) -> '2026-10-14' (the date in India)."""
    try:
        t = _dt.datetime.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_dt.timezone.utc)
        return t.astimezone(_IST).date().isoformat()
    except (TypeError, ValueError):
        return ""


def dmy_utc(ts):
    return dmy(ist_date(ts))


def dmy(iso):
    try:
        return _dt.date.fromisoformat(str(iso)[:10]).strftime("%d %B %Y").lstrip("0")
    except (TypeError, ValueError):
        return ""


def parse_date(iso):
    try:
        return _dt.date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return None


def _one_line(v, sep=" "):
    """Collapse line breaks and runs of spaces, so typed text cannot start a new paragraph, table row or page break."""
    parts = [" ".join(x.split()) for x in str(v or "").splitlines()]
    if sep.startswith(","):
        parts = [x.rstrip(",") for x in parts]
    return sep.join(x for x in parts if x)


_MULTILINE = {"extra_clauses"}                       # one term per line: these keep their line breaks
_ADDRESS = {"buyer_address", "address"}


def _s(d, k, default=""):
    v = str(d.get(k) or default).strip()
    if k in _MULTILINE:
        return v
    return _one_line(v, ", " if k in _ADDRESS else ("; " if k == "known_defects" else " "))


def _cell(v):
    """Table cells are split on '|', so a typed '|' would add a column."""
    return str(v).replace("|", "/")


def vehicle_label(d):
    return " ".join(x for x in (_s(d, "year"), _s(d, "make"), _s(d, "model"), _s(d, "variant")) if x)


def vehicle_long(d):
    bits = [vehicle_label(d), f"registration no. {_s(d, 'reg_no')}"]
    if _s(d, "chassis"):
        bits.append(f"chassis no. {_s(d, 'chassis')}")
    if _s(d, "engine_no"):
        bits.append(f"engine no. {_s(d, 'engine_no')}")
    return ", ".join(b for b in bits if b.strip())


def deal_state(profile, d):
    st = _s(d, "deal_state") or profile.get("state") or "TN"
    return st if st in STATES else "TN"


def balance_due(d):
    return max(0.0, num(d.get("price")) - num(d.get("advance")))


def buyer_block(d, short=False):
    rel = f"{_s(d, 'buyer_rel', 'S/o')} {_s(d, 'buyer_rel_name')}".strip()
    age = f", aged {_s(d, 'buyer_age')} years" if _s(d, "buyer_age") else ""
    addr = ", ".join(x for x in (_s(d, "buyer_address"), _s(d, "buyer_city")) if x)
    if short:
        return f"{_s(d, 'buyer_name')}, {rel}{age}, residing at {addr}"
    idn = f", holding {_s(d, 'buyer_id_type')} {_s(d, 'buyer_id_no')}" if _s(d, "buyer_id_no") else ""
    ph = f", mobile {_s(d, 'buyer_phone')}" if _s(d, "buyer_phone") else ""
    return f"{_s(d, 'buyer_name')}, {rel}{age}, residing at {addr}{idn}{ph}"


def seller_block(p, st):
    S = STATES[st]
    bits = [f"**{p['dealership_name']}**, a dealer in pre-owned motor vehicles with its place of business at "
            f"{_s(p, 'address')}, {p['city']}, {S['name']}"]
    if p.get("gstin"):
        bits.append(f"GSTIN {p['gstin']}")
    if p.get("trade_cert"):
        bits.append(f"trade certificate no. {p['trade_cert']}")
    who = p.get("signatory") or "its authorised signatory"
    return ", ".join(bits) + f", represented by {who}"


# ---------------------------------------------------------------- compliance checks

def compliance(p, d, today=None):
    """Return [{level, text}] where level is info | warn | alert."""
    today = today or today_ist()
    st = deal_state(p, d)
    S = STATES[st]
    out = []

    def add(level, text):
        out.append({"level": level, "text": text})

    add("info", f"Hand over Form 29 (signed by the registered owner) and Form 30 (signed by the buyer), "
                f"two sets each. The buyer must report the transfer to the {S['authority_short']} within "
                f"30 days; you report it within 14 days (Section 50, Motor Vehicles Act, 1988).")
    add("info", f"Print the agreement on stamp paper or an e-stamp bought in {S['name']}. Your advocate "
                f"confirms the value under {S['stamp_act']}; type it into the deal so it appears in the agreement.")
    add("info", f"Read the agreement out to the buyer in {S['lang']} before signing. The agreement records that you did.")

    reg, bst = _s(d, "reg_state"), _s(d, "buyer_state")
    if (reg and bst and reg != bst) or (reg and reg not in ("TN", "KL") and reg != st):
        add("warn", "The vehicle is registered in a different state from the buyer's home. You need an NOC "
                    "(Form 28) from the registering authority, and the buyer must re-register the vehicle in "
                    "their own state within 12 months of moving it (Section 47).")
    if _s(d, "hypothecated") == "yes":
        fin = _s(d, "financier") or "the financier"
        add("alert", f"The RC shows a loan with {fin}. Close the loan and get Form 35 and the financier's NOC "
                     f"before handover. The agreement makes this your responsibility.")
    if _s(d, "finance_by_buyer") == "yes":
        add("info", "The buyer is financing the purchase. Confirm the lender's disbursal date matches the balance "
                    "due date, and cooperate on the hypothecation entry (Form 34).")
    yr = int(num(d.get("year"))) if num(d.get("year")) else 0
    if yr and today.year - yr >= 13:
        add("warn", "This car is 13 or more years old. Registration lasts 15 years from first registration, then "
                    "needs renewal (Section 41(7)). Check the validity date on the RC before you promise delivery.")
    cash_hit = ((_s(d, "advance_mode") == "Cash" and num(d.get("advance")) >= 200000) or
                (_s(d, "balance_mode") == "Cash" and balance_due(d) >= 200000))
    if cash_hit:
        add("alert", "Income-tax law restricts taking Rs. 2,00,000 or more in cash. Take a bank transfer, "
                     "cheque or demand draft instead.")
    if num(d.get("price")) > 1000000:
        add("info", "A sale above Rs. 10,00,000 may attract tax collected at source. Confirm with your accountant "
                    "before you issue the invoice.")
    ins, dlv = parse_date(d.get("insurance_valid")), parse_date(d.get("delivery_date"))
    if ins and dlv and ins < dlv:
        add("warn", "The insurance policy expires before the delivery date. Renew it or tell the buyer in writing.")
    age = int(num(d.get("buyer_age"))) if num(d.get("buyer_age")) else 0
    if 0 < age < 18:
        add("alert", "The buyer is under 18. A minor cannot make a binding contract. Put the parent or guardian in as the buyer "
                     "and have them sign.")
    if _s(d, "accident_history") == "major":
        add("info", "A major repair is on record. Describe it under known defects so the agreement shows it was disclosed.")
    return out


# ---------------------------------------------------------------- sale agreement

def build_agreement(p, d, today=None):
    today = today or today_ist()
    st = deal_state(p, d)
    S = STATES[st]
    price, adv, bal = num(d.get("price")), num(d.get("advance")), balance_due(d)
    place = _s(d, "place") or p.get("city") or S["default_city"]
    jur = _s(d, "jurisdiction_city") or place
    agr_date = dmy(d.get("agreement_date")) or dmy(today.isoformat())
    rate = _s(d, "interest_rate", "12")
    pct = _s(d, "forfeit_pct", "10")
    reg_st = _s(d, "reg_state")
    cross = bool(reg_st and _s(d, "buyer_state") and reg_st != _s(d, "buyer_state"))
    hypo = _s(d, "hypothecated") == "yes"
    rc_holder = _s(d, "rc_holder") or p["dealership_name"]

    L = []
    n = [0]

    def clause(title):
        n[0] += 1
        L.append(f"### {n[0]}. {title}")

    def sub(items):
        for i, t in enumerate(items):
            L.append(f"({chr(97 + i)}) {t}")

    L += ["# AGREEMENT FOR SALE OF A PRE-OWNED MOTOR VEHICLE", ""]
    L.append(f"This Agreement is made at {place}, {S['name']}, on {agr_date}, between:")
    L.append(f"{seller_block(p, st)} (the \"**Seller**\", which includes its successors and assigns); and")
    L.append(f"{buyer_block(d)} (the \"**Buyer**\", which includes the Buyer's heirs, legal representatives and assigns).")
    L.append("**Whereas:**")
    L.append(f"(A) The Seller deals in pre-owned motor vehicles and is in lawful possession of the vehicle described in "
             f"Clause 1 (the \"**Vehicle**\"), whose registration certificate stands in the name of {rc_holder}.")
    L.append("(B) The Buyer has inspected the Vehicle, taken a test drive, and wishes to buy it. The Seller wishes to "
             "sell it. Both agree on the following terms.")
    L.append("**The parties agree as follows:**")

    # 1 vehicle
    clause("The Vehicle")
    rows = [("Make and model", " ".join(x for x in (_s(d, "make"), _s(d, "model"), _s(d, "variant")) if x)),
            ("Year of manufacture", _s(d, "year")),
            ("Registration no.", _s(d, "reg_no")),
            ("Chassis no.", _s(d, "chassis")),
            ("Engine no.", _s(d, "engine_no")),
            ("Colour and fuel", ", ".join(x for x in (_s(d, "colour"), _s(d, "fuel")) if x)),
            ("Odometer reading at sale", f"{_s(d, 'odometer')} km" if _s(d, "odometer") else ""),
            ("Owner serial", _s(d, "owners")),
            ("RC in the name of", rc_holder),
            ("Insurance", ", ".join(x for x in (_s(d, "insurance_policy"),
                                               f"valid to {dmy(d.get('insurance_valid'))}" if dmy(d.get("insurance_valid")) else "") if x)),
            ("Hypothecation", f"Subsisting loan with {_s(d, 'financier') or 'a financier'}" if hypo else "No loan or hypothecation")]
    for k, v in rows:
        if v:
            L.append(f"|**{k}**|{_cell(v)}")
    L.append("")

    # 2 price
    clause("Sale price and payment")
    L.append(f"The Seller sells and the Buyer buys the Vehicle for **{inr_words(price)}** (the \"Sale Price\"), payable as follows:")
    if adv > 0:
        sub([f"Advance of {inr_words(adv)} paid on {dmy(d.get('advance_date')) or 'the date of this Agreement'} by "
             f"{_s(d, 'advance_mode', 'bank transfer')}, receipt of which the Seller acknowledges.",
             f"Balance of {inr_words(bal)} payable on or before {dmy(d.get('balance_due_date')) or 'the delivery date'} by "
             f"{_s(d, 'balance_mode', 'bank transfer')}, against delivery of the Vehicle."])
    else:                                              # no advance was taken: the whole price is the balance
        sub([f"The full Sale Price of {inr_words(price)} is payable on or before {dmy(d.get('balance_due_date')) or 'the delivery date'} by "
             f"{_s(d, 'balance_mode', 'bank transfer')}, against delivery of the Vehicle."])
    if _s(d, "finance_by_buyer") == "yes":
        L.append(f"The Buyer is financing the Balance through {_s(d, 'buyer_financier') or 'a financier'}. The Buyer shall "
                 f"ensure the financier pays the Seller on or before the due date. A delay by the financier is a delay by the Buyer.")
    L.append("The Sale Price includes GST, if any, payable by the Seller on its margin under the Central Goods and Services "
             "Tax Act, 2017. The Seller shall issue a bill of sale or tax invoice. Any tax that must be collected at source "
             "under the income-tax law shall be collected and accounted for as that law requires. Payments of Rs. 2,00,000 "
             "or more shall be made through banking channels and not in cash.")

    # 3 delivery
    clause("Delivery, documents, risk and title")
    L.append(f"The Seller shall deliver the Vehicle with its keys at {place} on {dmy(d.get('delivery_date')) or 'the date on which the Balance is received'}, "
             f"on receipt of the full Sale Price, together with:")
    docs = ["the original registration certificate" + (" (if the financier still holds it, a copy with the financier's written undertaking to release the original)" if hypo else ""),
            "Form 29 signed by the registered owner, two sets, and Form 30 signed by the Buyer",
            "the valid insurance policy and pollution-under-control certificate",
            f"proof of payment of tax under {S['tax_act']}",
            "the service history and all keys in the Seller's possession"]
    if hypo:
        docs.append("Form 35 and the financier's no-objection certificate")
    if cross:
        docs.append("a no-objection certificate in Form 28 from the registering authority")
    sub(docs)
    L.append("Risk in the Vehicle passes to the Buyer on delivery. Property in the Vehicle passes to the Buyer on delivery "
             "against full payment of the Sale Price.")

    # 4 condition
    clause("Condition of the Vehicle")
    L.append("The Buyer has inspected the Vehicle and its documents and accepts its mechanical, electrical and cosmetic "
             "condition as it stands (\"as is where is\"), subject to Clauses 5 and 12.")
    L.append(f"The Seller has disclosed the following known defects: {_s(d, 'known_defects') or 'none, other than normal wear and tear for its age and use'}.")
    acc = _s(d, "accident_history")
    L.append({"major": "The Seller has also disclosed that the Vehicle has had a major repair after an accident, as described above.",
              "minor": "The Seller has disclosed that the Vehicle has had minor cosmetic or bodywork repairs.",
              }.get(acc, "To the Seller's knowledge, the Vehicle has not been in a major accident."))

    # 5 seller assurances
    clause("Seller's assurances")
    L.append("The Seller assures the Buyer that:")
    sub(["it has the right to sell the Vehicle, or the written authority of the registered owner to do so;",
         "the Vehicle is free from any lien, attachment, hypothecation or other encumbrance, other than any loan "
         "disclosed in Clause 1 that the Seller will close under Clause 9;",
         "the Vehicle is not stolen and is not under seizure by any police authority or court;",
         f"all tax due under {S['tax_act']}, and all fines and challans (including electronic challans) relating to the period "
         f"up to delivery, are paid or will be paid by the Seller;",
         "to the Seller's knowledge, the odometer reading is genuine and the Vehicle has not been submerged in a flood "
         "or written off as a total loss, except as disclosed."])
    L.append("If an assurance in (a), (b) or (c) proves untrue, the Seller shall remove the defect at its cost within 15 days of "
             "written notice. If it cannot, the Seller shall take the Vehicle back and refund everything it has received.")

    # 6 buyer assurances
    clause("Buyer's assurances")
    L.append("The Buyer assures the Seller that the Buyer holds a valid driving licence, has paid the Sale Price from lawful funds, "
             "will use the Vehicle lawfully, and will tell the Seller in writing within 7 days if the Buyer's address changes.")

    # 7 transfer
    clause("Transfer of ownership")
    items = [f"The Seller shall report the transfer to the {S['authority']}, within 14 days of delivery, and send the Buyer a copy of the report (Section 50, Motor Vehicles Act, 1988).",
             f"The Buyer shall apply to the {S['authority_short']} within 30 days of delivery, with Form 29, Form 30, the registration certificate, identity and address proof, insurance, and the fees. The Buyer shall give the Seller the acknowledgment within 7 days of applying, and a copy of the updated registration certificate when issued."]
    if cross:
        items.append(f"The Vehicle is registered in {STATE_LABELS.get(reg_st, reg_st)} and the Buyer lives in {STATE_LABELS.get(_s(d, 'buyer_state'), 'another state')}. "
                     "The Seller shall give a no-objection certificate in Form 28 or help obtain it. The Buyer shall apply for a new registration mark "
                     "in the Buyer's state within 12 months of taking the Vehicle there (Section 47).")
    bearer = _s(d, "transfer_cost_bearer", "Buyer")
    items.append(f"Fees, taxes and endorsement charges for the transfer shall be borne by the {bearer}.")
    items.append("Until the transfer is recorded, the Buyer alone is responsible for the Vehicle's use and shall indemnify the Seller "
                 "against claims, challans and penalties arising from its use after delivery.")
    items.append("If the Buyer does not apply within 30 days, the Buyer authorises the Seller to report the transfer to the registering "
                 "authority. This does not reduce the Buyer's duties under this Clause.")
    sub(items)

    # 8 tax and challans
    clause("Tax, challans and dues")
    L.append(f"Tax under {S['tax_act']}, challans, fines and other dues for the period up to delivery are the Seller's. "
             "Those for the period after delivery are the Buyer's, whether or not the Vehicle has yet been transferred in the Buyer's name.")

    # 9 hypothecation
    clause("Hypothecation and finance")
    if hypo:
        L.append(f"The Vehicle is hypothecated to {_s(d, 'financier') or 'a financier'}. The Seller shall, at its cost, close the loan, "
                 "obtain Form 35 and the no-objection certificate, and have the hypothecation entry removed from the registration "
                 "certificate before delivery. If the Seller cannot do so before delivery, the Buyer may withhold from the Balance "
                 "the amount outstanding on the loan and pay it directly to the financier.")
    else:
        L.append("The Seller states that no hypothecation subsists on the Vehicle.")
    if _s(d, "finance_by_buyer") == "yes":
        L.append("The hypothecation in favour of the Buyer's financier shall be recorded in the manner the Motor Vehicles Act, 1988 requires, and the Seller shall cooperate.")

    # 10 insurance
    clause("Insurance")
    L.append("The Buyer shall apply to the insurer within 14 days of delivery to record the transfer of the policy (Section 157, Motor Vehicles Act, 1988), "
             "or buy a new policy, and shall not drive the Vehicle without valid insurance.")

    # 11 default
    clause("Default and termination")
    sub([f"If the Buyer does not pay the Balance by the due date, the Buyer shall pay interest on it at {rate}% a year from the due date until payment.",
         f"If the delay passes 15 days, the Seller may end this Agreement by written notice, keep from the advance, as reasonable compensation (Section 74, Indian Contract Act, 1872), "
         f"the lower of {pct}% of the Sale Price and the advance actually paid, and refund the rest. The Seller may then resell the Vehicle and claim any further loss "
         "(Section 54, Sale of Goods Act, 1930). If the Vehicle has been delivered, the Seller may instead sue for the price (Section 55 of that Act).",
         "If the Seller does not deliver within 15 days of the delivery date, for a reason not caused by the Buyer, the Buyer may end this Agreement by written notice and "
         "the Seller shall refund everything it has received within 7 days of that notice."])

    # 12 warranty
    clause("Limited warranty")
    wd, wk = int(num(d.get("warranty_days"))), int(num(d.get("warranty_km")))
    if wd > 0 or wk > 0:
        span = " or ".join(x for x in (f"{wd} days" if wd else "", f"{wk:,} km" if wk else "") if x)
        L.append(f"The Seller warrants the {_s(d, 'warranty_scope') or 'engine and gearbox'} for {span} from delivery, whichever ends first. "
                 "The Buyer shall report a defect in writing and bring the Vehicle to the Seller's workshop. The Seller shall repair or replace the faulty part at its cost. "
                 "The warranty does not cover accident damage, misuse, tyres, batteries, or parts that wear in normal use.")
    else:
        L.append("The Seller gives no warranty beyond the assurances in Clause 5, to the extent the law allows.")

    # 13 indemnity, 14 notices
    clause("Indemnity")
    L.append("Each party shall compensate the other for loss caused by a breach of its assurances or duties under this Agreement.")
    clause("Notices")
    L.append("Formal notices shall be in writing and sent by registered post or speed post to the addresses in this Agreement. "
             "Messages by email or chat apps are for convenience and are not formal notice.")

    # 15 law
    clause("Governing law and disputes")
    L.append("This Agreement is governed by the laws of India. Nothing in it limits any right the Seller has under the Negotiable Instruments Act, 1881 for a dishonoured cheque.")
    if str(d.get("arbitration")) in ("1", "true", "True", "yes"):
        L.append(f"Disputes shall be referred to a sole arbitrator chosen by agreement of both parties. If they cannot agree within 30 days of a written request, "
                 f"the arbitrator shall be appointed by {S['hc']} under Section 11 of the Arbitration and Conciliation Act, 1996. The seat and venue are {jur}, "
                 f"the language is English, and the courts at {jur} have jurisdiction over interim relief and enforcement.")
    else:
        L.append(f"The courts at {jur}, {S['name']} have exclusive jurisdiction over any dispute arising from this Agreement.")

    # 16 stamp, 17 language, 18 general
    clause("Stamp duty")
    sv = _s(d, "stamp_value")
    L.append(f"This Agreement is executed on stamp paper or e-stamp of value {inr(sv) if sv else 'Rs. ______'} bought in {S['name']}, "
             f"as required under {S['stamp_act']}. The duty is borne equally by both parties.")
    clause("Language")
    L.append(f"This Agreement is written in English. Its contents were read out and explained in {S['lang']} to the Buyer, "
             "who confirms that the Buyer understood them and signs of the Buyer's own free will.")
    clause("General")
    L.append("This Agreement is the whole agreement between the parties. A change is valid only if written and signed by both. "
             "If any part is held invalid, the rest continues. Time is of the essence for payment and for transfer of ownership.")
    extra = [x.strip() for x in _s(d, "extra_clauses").splitlines() if x.strip()]
    if extra:
        clause("Additional terms")
        sub(extra)

    L += ["", f"Signed at {place} on {agr_date}.", ""]
    seller_sign = p.get("signatory") or "Authorised signatory"
    L += [f"|~**For {_cell(p['dealership_name'])} (Seller)**|~**Buyer**",
          "|~|~", "|~|~",
          f"|~{_cell(seller_sign)}|~{_cell(_s(d, 'buyer_name'))}", "|~|~",
          f"|~**Witness 1:** {_cell(_s(d, 'witness1')) or '____________________'}|~**Witness 2:** {_cell(_s(d, 'witness2')) or '____________________'}",
          "|~Address and signature:|~Address and signature:"]

    # annexure
    L += ["~~", "## ANNEXURE A", "## DELIVERY AND DOCUMENT HANDOVER RECEIPT", "",
          f"Vehicle: {vehicle_long(d)}", "",
          "|**Item**|**Handed over (Yes / No)**|**Remarks**"]
    items = ["Original registration certificate", "Form 29 (two sets) and Form 30", "Insurance policy",
             "Pollution-under-control certificate", "Tax payment proof", "Service history", "Keys (number: ____)",
             "Spare wheel and tool kit"]
    if hypo:
        items.insert(2, "Form 35 and financier's no-objection certificate")
    if cross:
        items.insert(2, "Form 28 no-objection certificate")
    for it in items:
        L.append(f"|{it}||")
    L += ["", "Odometer at delivery: ________ km        Fuel level: ________", "",
          "The Buyer confirms receiving the Vehicle and the items ticked above on ________________ at ____________, in the condition inspected.", "",
          f"|~**Buyer:** {_cell(_s(d, 'buyer_name'))}|~**For {_cell(p['dealership_name'])}:** {_cell(seller_sign)}",
          "|~Signature:|~Signature:"]
    return "\n".join(L)


# ---------------------------------------------------------------- notices

def _f(extra, k, default=""):
    v = extra.get(k)
    if v in (None, ""):
        return default
    return _one_line(v, "; " if k == "challan_details" else " ")


def _field(key, label, kind="text", default="", req=False, hint=""):
    return {"key": key, "label": label, "type": kind, "default": default, "required": req, "hint": hint}


NOTICE_TYPES = {
    "payment_default": {
        "label": "Balance payment not made",
        "blurb": "The buyer has not paid the balance by the due date.",
        "fields": [_field("due_amount", "Amount still due (Rs.)", "number", req=True),
                   _field("due_date", "It was due on", "date", req=True),
                   _field("demand_days", "Days to pay after receiving the notice", "number", "15", True),
                   _field("interest_rate", "Interest (% a year)", "number", "12"),
                   _field("notice_cost", "Notice cost to claim (Rs., optional)", "number", "0"),
                   _field("extra_facts", "Anything else the advocate should know", "textarea")],
    },
    "cheque_dishonour": {
        "label": "Cheque bounced (Section 138)",
        "blurb": "The buyer's cheque came back unpaid. Strict deadlines apply.",
        "fields": [_field("cheque_no", "Cheque number", req=True),
                   _field("cheque_date", "Cheque date", "date", req=True),
                   _field("cheque_amount", "Cheque amount (Rs.)", "number", req=True),
                   _field("drawee_bank", "Buyer's bank and branch", req=True),
                   _field("dealer_bank", "Your bank where you deposited it", req=True),
                   _field("return_memo_date", "Date on the bank's return memo", "date", req=True),
                   _field("return_reason", "Reason on the return memo", "text", "Funds insufficient", True),
                   _field("intimation_date", "Date the bank told you it bounced", "date", "",
                          True, "The 30-day limit to send the notice runs from this date."),
                   _field("extra_facts", "Anything else the advocate should know", "textarea")],
    },
    "transfer_default": {
        "label": "RC not transferred",
        "blurb": "The buyer has not moved the registration into their name.",
        "fields": [_field("delivered_on", "Car was delivered on", "date", req=True),
                   _field("demand_days", "Days to complete transfer", "number", "15", True),
                   _field("challans", "Challans or notices already received (optional)", "textarea"),
                   _field("extra_facts", "Anything else the advocate should know", "textarea")],
    },
    "cancellation_forfeiture": {
        "label": "Buyer backed out",
        "blurb": "Final chance to complete the purchase, then cancel and keep part of the advance.",
        "fields": [_field("backed_out_on", "Date the buyer said they would not proceed", "date"),
                   _field("demand_days", "Days to pay the balance and take delivery", "number", "7", True),
                   _field("forfeit_amount", "Amount of advance you will keep (Rs.)", "number", req=True,
                          hint="Keep it to a reasonable share of the price. Courts do not enforce excessive forfeiture."),
                   _field("refund_days", "Days to refund the rest", "number", "15", True),
                   _field("extra_facts", "Anything else the advocate should know", "textarea")],
    },
    "challan_liability": {
        "label": "Challans after delivery",
        "blurb": "Traffic fines on the car after it left your lot, still showing against you.",
        "fields": [_field("delivered_on", "Car was delivered on", "date", req=True),
                   _field("challan_details", "Challan numbers, dates and amounts", "textarea", req=True),
                   _field("challan_total", "Total (Rs.)", "number", req=True),
                   _field("demand_days", "Days to pay and send proof", "number", "10", True),
                   _field("extra_facts", "Anything else the advocate should know", "textarea")],
    },
    "reply_to_complaint": {
        "label": "Reply to a buyer's complaint",
        "blurb": "The buyer says the car is defective. Respond on record.",
        "fields": [_field("complaint_date", "Date of the buyer's complaint or notice", "date", req=True),
                   _field("complaint_summary", "What the buyer alleges", "textarea", req=True),
                   _field("delivered_on", "Car was delivered on", "date"),
                   _field("km_run", "Kilometres run since delivery (if known)", "number"),
                   _field("extra_facts", "Anything else the advocate should know", "textarea")],
    },
}


def _header(p, d, st, mode_line):
    S = STATES[st]
    return ["# LEGAL NOTICE", "", f">> Date: {dmy(today_ist().isoformat())}", f">> {mode_line}", "",
            "To,", f"**{_s(d, 'buyer_name')}**",
            f"{_s(d, 'buyer_rel', 'S/o')} {_s(d, 'buyer_rel_name')}".strip(),
            ", ".join(x for x in (_s(d, "buyer_address"), _s(d, "buyer_city")) if x),
            (f"Mobile: {_s(d, 'buyer_phone')}" if _s(d, "buyer_phone") else ""),
            (f"Email: {_s(d, 'buyer_email')}" if _s(d, "buyer_email") else ""), ""]


def _opening(p, st):
    S = STATES[st]
    return ("Sir/Madam,", "",
            f"Under instructions from and on behalf of my client, **{p['dealership_name']}**, a dealer in pre-owned motor vehicles "
            f"with its place of business at {_s(p, 'address')}, {p['city']}, {S['name']} (\"my client\"), I give you this notice:")


def build_notice(ntype, p, d, extra, agreement_date=""):
    st = deal_state(p, d)
    S = STATES[st]
    jur = _s(d, "jurisdiction_city") or _s(d, "place") or p.get("city") or S["default_city"]
    veh = vehicle_long(d)
    price, adv = num(d.get("price")), num(d.get("advance"))
    agr = dmy(d.get("agreement_date")) or dmy(agreement_date) or "the date recorded in the agreement"
    days = int(num(_f(extra, "demand_days"), 15)) or 15
    cost = int(num(_f(extra, "notice_cost"), 0))
    L = []
    n = [0]

    def para(t):
        n[0] += 1
        L.append(f"{n[0]}. {t}")

    mode = "BY REGISTERED POST A.D. AND SPEED POST" + (" AND EMAIL" if _s(d, "buyer_email") else "")
    if ntype == "cheque_dishonour":
        title = "Notice under Section 138 of the Negotiable Instruments Act, 1881"
    else:
        title = {"payment_default": "Demand for payment of the balance sale price",
                 "transfer_default": "Demand to complete transfer of ownership of the vehicle",
                 "cancellation_forfeiture": "Final notice before cancellation of the sale",
                 "challan_liability": "Demand to pay traffic challans incurred after delivery",
                 "reply_to_complaint": "Reply to your complaint about the vehicle"}[ntype]
    L += _header(p, d, st, mode)
    L += [f"### Subject: {title}", "", *_opening(p, st)]
    L.append("")

    sale = (f"By an agreement dated {agr}, my client agreed to sell, and you agreed to buy, the vehicle {veh} (the \"vehicle\") "
            f"for {inr_words(price)}.")

    if ntype == "payment_default":
        due = num(_f(extra, "due_amount"), 0) or max(0, price - adv)
        rate = _f(extra, "interest_rate", "12")
        delivered = d.get("_stage", 0) >= 2
        para(sale)
        para((f"You paid an advance of {inr(adv)}. The balance of " if adv > 0 else "The sale price of ")
             + f"{inr_words(due)} was payable by {dmy(_f(extra, 'due_date')) or 'the agreed date'}.")
        para("Despite repeated requests, you have not paid the balance.")
        para("The vehicle was delivered to you and has been in your use since." if delivered else
             "My client continues to hold the vehicle ready for delivery against payment of the balance.")
        if _f(extra, "extra_facts"):
            para(_f(extra, "extra_facts"))
        para(f"I call upon you to pay my client {inr(due)} with interest at {rate}% a year from the due date until payment, within {days} days of receiving this notice."
             + (f" You shall also pay {inr(cost)} as the cost of this notice." if cost else ""))
        if delivered:
            para("If you do not, my client will file a civil suit against you for the price under Section 55 of the Sale of Goods Act, 1930, with interest and costs, at your risk as to cost and consequences.")
        else:
            para("If you do not, my client will treat this as notice of its intention to resell the vehicle under Section 54 of the Sale of Goods Act, 1930, "
                 "and will recover from you any loss on resale, with interest and costs.")

    elif ntype == "cheque_dishonour":
        amt = num(_f(extra, "cheque_amount"))
        para(sale)
        para(f"In part payment of that price and to discharge a legally enforceable debt, you issued to my client cheque no. {_f(extra, 'cheque_no')} dated "
             f"{dmy(_f(extra, 'cheque_date'))} for {inr_words(amt)} drawn on {_f(extra, 'drawee_bank')}.")
        para(f"My client presented the cheque through its bank, {_f(extra, 'dealer_bank')}. It was returned unpaid on {dmy(_f(extra, 'return_memo_date'))} "
             f"with the remark \"{_f(extra, 'return_reason')}\". My client received the bank's intimation on {dmy(_f(extra, 'intimation_date'))}.")
        para("The dishonour of the cheque is an offence under Section 138 of the Negotiable Instruments Act, 1881.")
        if _f(extra, "extra_facts"):
            para(_f(extra, "extra_facts"))
        para(f"I call upon you to pay my client {inr_words(amt)} within 15 days of receiving this notice. If you do not, my client will file a complaint against you "
             f"under Sections 138 and 142 of the Act, which carries imprisonment up to two years, a fine up to twice the cheque amount, or both, and will also recover the amount "
             f"in a civil suit with interest and costs.")

    elif ntype == "transfer_default":
        para(sale)
        para(f"The vehicle was delivered to you on {dmy(_f(extra, 'delivered_on'))}. The agreement required you to apply to the {S['authority_short']} within 30 days "
             f"of delivery for transfer of ownership into your name, as Section 50 of the Motor Vehicles Act, 1988 also requires. Forms 29 and 30 were signed and handed over for this purpose.")
        para("You have not completed the transfer. The vehicle therefore still stands in the name of its previous registered owner, which exposes my client to claims, challans and penalties for a vehicle it no longer holds.")
        if _f(extra, "challans"):
            para(f"The following have already been recorded against the vehicle: {_f(extra, 'challans')}")
        if _f(extra, "extra_facts"):
            para(_f(extra, "extra_facts"))
        para(f"I call upon you to apply for the transfer within {days} days of receiving this notice and to send my client the RTO acknowledgment, and to pay any challan that arose after delivery.")
        para("If you do not, my client will report the transfer to the registering authority, call on you to indemnify it under the agreement, and take legal action for the loss, with costs.")

    elif ntype == "cancellation_forfeiture":
        forfeit = num(_f(extra, "forfeit_amount"))
        refund = max(0.0, adv - forfeit)
        rdays = int(num(_f(extra, "refund_days"), 15)) or 15
        para(sale)
        para((f"You paid an advance of {inr(adv)}. You have not paid the balance of {inr(max(0, price - adv))}" if adv > 0
              else f"You have not paid the sale price of {inr(price)}") + " or taken delivery"
             + (f", and told my client on {dmy(_f(extra, 'backed_out_on'))} that you will not proceed." if _f(extra, "backed_out_on") else "."))
        if _f(extra, "extra_facts"):
            para(_f(extra, "extra_facts"))
        para(f"This is my client's last opportunity to complete the purchase. Pay the balance and take delivery within {days} days of receiving this notice. "
             f"This is also notice of my client's intention to resell the vehicle under Section 54 of the Sale of Goods Act, 1930 if you do not.")
        if adv > 0 and forfeit > 0:
            para(f"If you do not, the agreement will stand cancelled. My client will keep {inr(forfeit)} of the advance as reasonable compensation for its loss "
                 f"(Section 74, Indian Contract Act, 1872), refund {inr(refund)} within {rdays} days of receiving your bank details, and claim any further loss on resale.")
        else:
            para("If you do not, the agreement will stand cancelled. My client will claim reasonable compensation for its loss "
                 "(Section 74, Indian Contract Act, 1872), including any loss on resale of the vehicle.")

    elif ntype == "challan_liability":
        para(sale)
        para(f"The vehicle was delivered to you on {dmy(_f(extra, 'delivered_on'))} and has been in your possession and control since. "
             "The agreement makes you responsible for all challans, fines and dues arising after delivery.")
        para(f"The following challans have been recorded against the vehicle for the period after delivery: {_f(extra, 'challan_details')}. "
             f"The total is {inr(_f(extra, 'challan_total'))}.")
        if _f(extra, "extra_facts"):
            para(_f(extra, "extra_facts"))
        para(f"I call upon you to pay these challans and send my client the receipts within {days} days of receiving this notice, and to complete the transfer of the vehicle into your name.")
        para("If you do not, my client will pay them to protect its record, recover the amount from you with interest, and claim damages and costs.")

    elif ntype == "reply_to_complaint":
        para(f"I refer to your complaint dated {dmy(_f(extra, 'complaint_date'))} about the vehicle {veh}, which you bought from my client for {inr_words(price)} under an agreement dated {agr}. "
             f"You allege: {_f(extra, 'complaint_summary')}")
        para("My client denies your allegations. You inspected and test-drove the vehicle before buying. It was sold in the condition you inspected, "
             f"with its known defects disclosed ({_s(d, 'known_defects') or 'none other than normal wear and tear'}), and its odometer reading of {_s(d, 'odometer') or 'the recorded figure'} km was recorded.")
        km = _f(extra, "km_run")
        if _f(extra, "delivered_on") or km:
            para("The vehicle was delivered to you" + (f" on {dmy(_f(extra, 'delivered_on'))}" if _f(extra, "delivered_on") else "")
                 + (f" and has been driven about {km} km since." if km else "."))
        wd, wk = int(num(d.get("warranty_days"))), int(num(d.get("warranty_km")))
        if wd or wk:
            para("The agreement gives a limited warranty. If the fault you describe falls within it, my client will repair it at its workshop at no cost to you.")
        if _f(extra, "extra_facts"):
            para(_f(extra, "extra_facts"))
        para("I call upon you to bring the vehicle for a joint inspection on a date within 10 days of receiving this notice, and to send an independent workshop report and invoices for any repair you say you have paid for.")
        para(f"My client reserves all its rights and will defend any claim before any forum, including the District Consumer Disputes Redressal Commission at {jur}. "
             "A claim that proves false will be met with a claim for costs.")

    L += ["", f"Please treat this as notice under the agreement and the law. My client reserves all its other rights. A copy of this notice is kept in my office for record."]
    return title, "\n".join(x for x in L if x is not None)


def s138_deadline(extra):
    """Days left in the 30-day window to send a Section 138 notice, or None."""
    t = parse_date((extra or {}).get("intimation_date"))
    if not t:
        return None
    return 30 - (today_ist() - t).days


POLISH_SYSTEM = (
    "You assist an Indian advocate who will review the notice you improve. Improve the clarity, grammar and formal tone "
    "of the legal notice you are given. Keep every name, number, date, amount, deadline, section reference and the demand exactly as written. "
    "Do not add facts, allegations, threats or legal claims. Do not remove any paragraph. Keep the markup characters at the start "
    "of lines (#, ###, >>, numbers like 1., (a), -, |). Do not add a signature or advocate details. Output only the revised notice."
)
