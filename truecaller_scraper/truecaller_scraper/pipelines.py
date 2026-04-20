import re, csv, os, phonenumbers
from phonenumbers import PhoneNumberType, number_type, geocoder, carrier
from datetime import datetime
from itemadapter import ItemAdapter

FAKE_PATTERNS = [re.compile(r"^(\d)\1{9}$"), re.compile(r"^(0123456789|9876543210|1234567890|0{10})$")]

def normalize(raw):
    cleaned = re.sub(r"[^\d+]", "", str(raw).strip())
    if not cleaned:
        return None, None

    attempts = []
    if cleaned.startswith("+"):
        attempts.append((cleaned, None))
    else:
        attempts.append((cleaned, "IN"))
        digits = re.sub(r"\D", "", cleaned)
        if digits.startswith("0091"):
            attempts.append(("+" + digits[2:], None))
        elif digits.startswith("91") and len(digits) > 10:
            attempts.append(("+" + digits, None))
        elif len(digits) == 10:
            attempts.append(("+91" + digits, None))

    for value, region in attempts:
        try:
            pn = phonenumbers.parse(value, region)
        except Exception:
            continue
        if pn.country_code == 91:
            return str(pn.national_number), pn
    return None, None

def is_fake(digits):
    return any(p.match(digits) for p in FAKE_PATTERNS)

class PhoneValidationPipeline:
    def process_item(self, item, spider):
        a = ItemAdapter(item)
        raw = a.get("original_number", "")
        digits, pn = normalize(raw)
        current_status = a.get("validation_status")
        a["scraped_at"] = datetime.now().isoformat(timespec="seconds")
        if digits is None or pn is None:
            a["normalized_number"] = ""
            a["is_valid_indian"] = False
            if not current_status:
                a["validation_status"] = "INVALID"
                a["validation_reason"] = "Not a valid Indian phone number"
            return item
        if is_fake(digits):
            a["normalized_number"] = digits
            a["is_valid_indian"] = False
            if not current_status:
                a["validation_status"] = "INVALID"
                a["validation_reason"] = "Obvious fake/test pattern"
            return item

        if not phonenumbers.is_valid_number(pn):
            a["normalized_number"] = digits
            a["is_valid_indian"] = False
            if not current_status:
                a["validation_status"] = "INVALID"
                a["validation_reason"] = "libphonenumber: not a valid Indian number"
            return item

        a["normalized_number"] = digits
        a["is_valid_indian"] = True
        if not current_status:
            a["validation_status"] = "VALID"
            a["validation_reason"] = "Passed local validation"
        if not a.get("carrier"):
            a["carrier"] = carrier.name_for_number(pn, "en") or ""
        if not a.get("location"):
            a["location"] = geocoder.description_for_number(pn, "en") or "India"
        if not a.get("line_type"):
            nt = number_type(pn)
            a["line_type"] = {
                PhoneNumberType.MOBILE: "Mobile",
                PhoneNumberType.FIXED_LINE: "Landline",
                PhoneNumberType.FIXED_LINE_OR_MOBILE: "Fixed/Mobile",
                PhoneNumberType.TOLL_FREE: "Toll-free",
            }.get(nt, "Unknown")
        return item

FIELDNAMES = [
    "source_row","candidate_index","original_cell","original_number","normalized_number",
    "csv_CIN","csv_CompanyName","csv_Emails","csv_Website",
    "name","carrier","line_type","location","spam_score","spam_type","tags",
    "comments_count","validation_status","validation_reason","source_url","scraped_at",
]

class CsvExportPipeline:
    def open_spider(self, spider):
        out_dir = getattr(spider, "output_dir", ".")
        os.makedirs(out_dir, exist_ok=True)
        self.valid_f   = open(os.path.join(out_dir, "scraped_valid.csv"),   "w", newline="", encoding="utf-8")
        self.invalid_f = open(os.path.join(out_dir, "scraped_invalid.csv"), "w", newline="", encoding="utf-8")
        self.blocked_f = open(os.path.join(out_dir, "scraped_blocked.csv"), "w", newline="", encoding="utf-8")
        self.valid_w   = csv.DictWriter(self.valid_f,   fieldnames=FIELDNAMES, extrasaction="ignore")
        self.invalid_w = csv.DictWriter(self.invalid_f, fieldnames=FIELDNAMES, extrasaction="ignore")
        self.blocked_w = csv.DictWriter(self.blocked_f, fieldnames=FIELDNAMES, extrasaction="ignore")
        for w in (self.valid_w, self.invalid_w, self.blocked_w): w.writeheader()
        for f in (self.valid_f, self.invalid_f, self.blocked_f): f.flush()
        self.counts = {"VALID": 0, "INVALID": 0, "BLOCKED": 0, "ERROR": 0}
    def process_item(self, item, spider):
        a = ItemAdapter(item)
        row = {f: a.get(f, "") for f in FIELDNAMES}
        status = a.get("validation_status", "INVALID")
        if status == "VALID":
            self.valid_w.writerow(row)
            self.valid_f.flush()
            self.counts["VALID"] += 1
        elif status in ("BLOCKED", "ERROR"):
            self.blocked_w.writerow(row)
            self.blocked_f.flush()
            self.counts[status] += 1
        else:
            self.invalid_w.writerow(row)
            self.invalid_f.flush()
            self.counts["INVALID"] += 1
        return item
    def close_spider(self, spider):
        for f in (self.valid_f, self.invalid_f, self.blocked_f): f.close()
