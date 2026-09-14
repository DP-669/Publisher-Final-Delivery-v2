"""
PFD rules, loaded at runtime from PFD_RULES.md and EPP_LANES.md.

PFD_RULES.md is the only place writing rules live. This module parses it once
at import and exposes what the rest of the app needs:

    system_instruction(catalog)   LOCKED section + the active catalog's block.
                                  Sent as the system prompt on every model call.
                                  The other two catalogs' blocks are never sent.
    setting(name)                 A TUNABLE switch, e.g. setting("track_writer").
    tunable(name)                 The text of one TUNABLE subsection, for task
                                  templates ("Track description", "Keywords"...).
    banned_list()                 The LOCKED "Hard banned list", parsed.
    forbidden_placement_words(c)  A catalog's "Forbidden placement words", parsed.
    fits_list(c)                  A catalog's "Placement list for Fits", parsed.
    lanes() / lane_words()        EPP lanes from EPP_LANES.md.

Editing the markdown changes the app on the next deploy. Nothing here restates
a rule; if a rule needs to change, change the markdown.
"""
import re
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
RULES_PATH = BASE_DIR / "PFD_RULES.md"
LANES_PATH = BASE_DIR / "EPP_LANES.md"

CATALOG_CODES = ("rC", "SSC", "EPP")


class RulesError(RuntimeError):
    """PFD_RULES.md is missing a section the app depends on."""


# ── Catalog names ──────────────────────────────────────────────────────────────

def catalog_code(catalog: str) -> str:
    """Map any catalog name variant ('redCola', 'rc', 'Short Story Collective') to rC/SSC/EPP."""
    c = (catalog or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    if c in ("rc", "redcola"):
        return "rC"
    if c in ("ssc", "shortstorycollective"):
        return "SSC"
    if c in ("epp", "ekonomicpropaganda"):
        return "EPP"
    raise RulesError(f"Unknown catalog '{catalog}'. Expected rC, SSC or EPP.")


# ── Markdown parsing ───────────────────────────────────────────────────────────

def _split(text: str, marker: str) -> Dict[str, str]:
    """Split markdown into {heading: body} at headings of exactly `marker` (## or ###)."""
    out: Dict[str, str] = {}
    current = None
    buf: List[str] = []
    pattern = re.compile(rf"^{re.escape(marker)} (?!#)(.+?)\s*$")
    for line in text.splitlines():
        m = pattern.match(line)
        if m:
            if current is not None:
                out[current] = "\n".join(buf).strip()
            current, buf = m.group(1).strip(), []
        elif current is not None:
            # A higher-level heading closes the current section.
            if marker == "###" and re.match(r"^## (?!#)", line):
                out[current] = "\n".join(buf).strip()
                current, buf = None, []
                continue
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf).strip()
    return out


def _strip_rules(text: str) -> str:
    """Drop horizontal rules and trailing separators left between sections."""
    return re.sub(r"\n-{3,}\s*$", "", text.strip()).strip()


def _line_value(block: str, label: str) -> Optional[str]:
    m = re.search(rf"^{re.escape(label)}:\s*(.+)$", block, flags=re.MULTILINE)
    return m.group(1).strip() if m else None


def _comma_list(value: str) -> List[str]:
    return [v.strip().rstrip(".").strip() for v in value.rstrip(".").split(",") if v.strip()]


class Rules:
    def __init__(self, rules_text: str, lanes_text: str = ""):
        self.text = rules_text
        self.lanes_text = lanes_text
        top = _split(rules_text, "##")
        for required in ("LOCKED", "CATALOG DNA", "TUNABLE"):
            if required not in top:
                raise RulesError(f"PFD_RULES.md has no '## {required}' section.")
        self.locked = _strip_rules(top["LOCKED"])
        self.tunable_text = _strip_rules(top["TUNABLE"])
        self.locked_sections = _split(top["LOCKED"], "###")
        self.tunable_sections = _split(top["TUNABLE"], "###")

        self.catalog_blocks: Dict[str, str] = {}
        for heading, body in _split(top["CATALOG DNA"], "###").items():
            code = heading.split()[0]
            if code in CATALOG_CODES:
                self.catalog_blocks[code] = f"### {heading}\n{_strip_rules(body)}"
        missing = [c for c in CATALOG_CODES if c not in self.catalog_blocks]
        if missing:
            raise RulesError(f"PFD_RULES.md has no catalog block for: {', '.join(missing)}")

        m = re.search(r"^version:\s*([0-9][0-9.]*)", rules_text, flags=re.MULTILINE)
        self.version = m.group(1) if m else "unknown"

    # ── Prompts ───────────────────────────────────────────────────────────────
    def system_instruction(self, catalog: str) -> str:
        code = catalog_code(catalog)
        parts = [
            f"PFD RULES v{self.version}. These rules override anything in the task below.",
            "## LOCKED\n" + self.locked,
            "## ACTIVE CATALOG\n" + self.catalog_blocks[code],
        ]
        if code == "EPP" and self.lanes_text:
            names = ", ".join(l["name"] for l in self.lanes())
            parts.append(f"## EPP LANES\nLegal lane names: {names}.")
        return "\n\n".join(parts)

    def tunable(self, name: str) -> str:
        for heading, body in self.tunable_sections.items():
            if heading.lower().startswith(name.lower()):
                return _strip_rules(body)
        raise RulesError(f"PFD_RULES.md TUNABLE has no '### {name}' section.")

    def setting(self, name: str) -> str:
        body = self.tunable(name)
        m = re.search(r"`([^`]+)`", body)
        if not m:
            raise RulesError(f"TUNABLE '{name}' has no backticked value.")
        return m.group(1).strip()

    # ── Parsed lists ──────────────────────────────────────────────────────────
    def banned_list(self) -> List[str]:
        for heading, body in self.locked_sections.items():
            if heading.lower().startswith("hard banned list"):
                return [w.lower() for w in _comma_list(" ".join(body.split()))]
        raise RulesError("PFD_RULES.md LOCKED has no 'Hard banned list'.")

    def _catalog_line(self, catalog: str, label: str) -> str:
        code = catalog_code(catalog)
        value = _line_value(self.catalog_blocks[code], label)
        if value is None:
            raise RulesError(f"Catalog {code} has no '{label}:' line.")
        return value

    def forbidden_placement_words(self, catalog: str) -> List[Dict[str, str]]:
        """
        [{"word": "trailer", "qualifier": "as a lead placement"}, {"word": "promo", "qualifier": ""}]
        A qualifier means the word is only forbidden in that role (see gate.py).
        SSC's "Forbidden jargon" line is included; "cue-sheet language of any kind"
        is not a literal word and is left to the model.
        """
        items = _comma_list(self._catalog_line(catalog, "Forbidden placement words"))
        code = catalog_code(catalog)
        jargon = _line_value(self.catalog_blocks[code], "Forbidden jargon")
        if jargon:
            items += [j for j in _comma_list(jargon) if "language" not in j]
        out = []
        for item in items:
            m = re.match(r"^(.*?)\s*\((.*)\)\s*$", item)
            word, qualifier = (m.group(1), m.group(2)) if m else (item, "")
            out.append({"word": word.strip().lower(), "qualifier": qualifier.strip()})
        return out

    def allowed_placement_words(self, catalog: str) -> List[str]:
        return _comma_list(self._catalog_line(catalog, "Allowed placement words"))

    def fits_list(self, catalog: str) -> List[str]:
        """Legal Fits tags. For EPP the lane is also legal (first tag) — see lanes()."""
        value = self._catalog_line(catalog, "Placement list for Fits")
        if ":" in value:  # EPP: "the album's lane first, then two of: A, B, C"
            value = value.split(":", 1)[1]
        return _comma_list(value)

    # ── EPP lanes ─────────────────────────────────────────────────────────────
    def lanes(self) -> List[Dict[str, str]]:
        """Active lanes first, then dormant, each {'name', 'status', 'brief'}."""
        if not self.lanes_text:
            return []
        sections = _split(self.lanes_text, "##")
        briefs = {}
        for key, body in sections.items():
            if key.lower().startswith("sub-publisher"):
                for line in body.splitlines():
                    m = re.match(r"^(Sounds [^—]+?|Orchestral [^—]+?)\s+—\s+(.+)$", line.strip())
                    if m:
                        briefs[m.group(1).strip()] = m.group(2).strip()
        out = []
        for key, status in (("active lanes", "active"), ("dormant lanes", "dormant")):
            body = next((b for h, b in sections.items() if h.lower().startswith(key)), "")
            for line in body.splitlines():
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 2 or not cells[0] or cells[0] in ("Lane",) or set(cells[0]) <= {"-"}:
                    continue
                out.append({"name": cells[0], "status": status, "brief": briefs.get(cells[0], "")})
        return out

    def lane_words(self) -> List[str]:
        """Every word of every lane name, minus filler. No EPP album name may contain one."""
        filler = {"like", "the"}
        words = set()
        for lane in self.lanes():
            for w in re.findall(r"[A-Za-z]+", lane["name"]):
                if w.lower() not in filler:
                    words.add(w.lower())
        return sorted(words)

    # ── Few-shot examples ─────────────────────────────────────────────────────
    def few_shot(self, catalog: str, kind: str) -> List[str]:
        """
        The active catalog's register examples from TUNABLE "Few-shot examples".
        kind: "Track" or "Album". Other catalogs' examples are never returned.
        """
        code = catalog_code(catalog)
        try:
            body = self.tunable("Few-shot examples")
        except RulesError:
            return []
        block = _split(body, "####").get(code, "")
        prefix = f"{kind}:"
        return [line[len(prefix):].strip() for line in block.splitlines() if line.startswith(prefix)]

    # ── Analysis schema block ─────────────────────────────────────────────────
    def analysis_schema_keys(self) -> List[str]:
        """Top-level keys in the TUNABLE 'Analysis schema' block, in order."""
        body = self.tunable("Analysis schema")
        m = re.search(r"```(.*?)```", body, flags=re.DOTALL)
        block = m.group(1) if m else body
        return [mm.group(1) for mm in re.finditer(r"^([a-z_]+):", block, flags=re.MULTILINE)]


def load(rules_path: Path = RULES_PATH, lanes_path: Path = LANES_PATH) -> Rules:
    rules_text = Path(rules_path).read_text(encoding="utf-8")
    lanes_text = Path(lanes_path).read_text(encoding="utf-8") if Path(lanes_path).exists() else ""
    return Rules(rules_text, lanes_text)


RULES = load()


# Module-level shortcuts — the API the rest of the app uses.
def version() -> str:
    return RULES.version


def system_instruction(catalog: str) -> str:
    return RULES.system_instruction(catalog)


def setting(name: str) -> str:
    return RULES.setting(name)


def tunable(name: str) -> str:
    return RULES.tunable(name)


def banned_list() -> List[str]:
    return RULES.banned_list()


def forbidden_placement_words(catalog: str) -> List[Dict[str, str]]:
    return RULES.forbidden_placement_words(catalog)


def allowed_placement_words(catalog: str) -> List[str]:
    return RULES.allowed_placement_words(catalog)


def fits_list(catalog: str) -> List[str]:
    return RULES.fits_list(catalog)


def few_shot(catalog: str, kind: str) -> List[str]:
    return RULES.few_shot(catalog, kind)


def lanes() -> List[Dict[str, str]]:
    return RULES.lanes()


def lane_names() -> List[str]:
    return [l["name"] for l in RULES.lanes()]


def lane_words() -> List[str]:
    return RULES.lane_words()
