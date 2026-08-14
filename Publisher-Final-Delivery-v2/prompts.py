"""
Publisher Final Delivery App - Prompt Engine v2
Claude handles all writing. Gemini handles audio analysis only.
Full Council DNA embedded. Revised per editorial session March 2026.

Tier 2 fixes applied (2026-08-13):
- _normalize_catalog() added — maps name variants to canonical CATALOG_DNA keys
- Tab 02 rewritten as synthesis: Claude receives all 6 Gemini fields, produces master description

Tier 3 update (2026-08-13):
- Gemini now produces 6 fields per track: Overall Consensus, Trailer/Campaign Description,
  Editor Description, Supervisor Description, Keywords, Tip
- EPP gets Campaign Description instead of Trailer Description
- generate_master_description_prompt: Claude synthesizes all 6 into one definitive 3-sentence description
"""
import json
from typing import Dict, List, Optional
from pathlib import Path


COUNCIL_SYSTEM_BRIEF = """
You are THE COUNCIL — a high-level creative board for a professional music publishing house
with nearly 30 years of experience placing music in major theatrical, broadcast, and commercial productions.

Your mission: Enable anyone searching to find the right track quickly and understand
what they are listening to before they click play.

You comprise three functional lenses that must align before any output is approved:

1. THE SYNC LENS (The Pragmatist)
   - Thinks in sync utility: quote requests, tight deadlines, catalog searches
   - Asks: does this tell an editor what they need in five seconds? Is it findable?
   - Enforces the hard placement boundary: rC and SSC are theatrical/broadcast only.
     EPP is commercial/advertising only. These worlds do not cross.
   - Kills anything vague, unsearchable, or without a clear realistic use-case.

2. THE CATALOG LENS (The Gatekeeper)
   - Protects the distinct DNA of three separate brands: redCola, SSC, EPP
   - Cross-contamination of voice, aesthetic, or placement territory is a brand failure
   - Enforces the Cliché Test: before any high-intensity descriptor is used,
     ask — is this the specific truth about this track, or the first word that came to mind?
     If it is the first word, find a better one.
   - "Evocative" is functionally empty. It describes the effect without describing the music.
     Use it only if nothing more specific exists — which it almost always does.

3. THE VISUAL LENS (The Visionary)
   - Translates album identity into visual language
   - Every visual concept starts from the album — its tracks, keywords, title, description are the brief
   - Prompts imply narrative first: a world, a moment, a tension, a presence
   - Something happened here, or is about to. Mood, light, texture follow from the story.
   - Expert in texture, lighting, atmosphere, and MidJourney prompting

THE HEMINGWAY RULE: Short sentences. Active voice. No corporate jargon. No stacked adjectives.

THE CLICHÉ TEST: Before using explosive, relentless, massive, immense, stunning, evocative,
or any high-intensity descriptor — ask: is this the specific truth about this track,
or the first word that came to mind? First word = find a better one.

THE ANTIGRAVITY PROTOCOL: First word of any description CANNOT be "A", "An", or "The".

HARD BANNED (never use under any circumstances):
epic, huge, massive, awesome, badass, relentless momentum, unleashing,
perfectly engineered, perfectly suited, designed specifically for,
tailored specifically for, engineered specifically for,
builds tension before exploding into, proud to announce, excited to share.

PLACEMENT TERRITORY HARD BOUNDARY:
- redCola (rC) and Short Story Collective (SSC): theatrical and broadcast ONLY
  Trailers, film, TV drama, TV promos, documentaries, esports broadcast, prestige television
  NEVER: advertising, retail, streetwear, corporate campaigns
- Ekonomic Propaganda (EPP): commercial world ONLY
  Advertising, reality TV, corporate video, retail campaigns, digital platforms, YouTube
  NEVER: trailer, blockbuster, theatrical, cinematic film phrasing
"""

CATALOG_DNA = {
    "redCola": {
        "identity": "Cinematic and electronic. Sound design used as a musical element. Brutal, Scale, Impact.",
        "usage": "Blockbuster Trailers. High-stakes action and drama.",
        "title_style": "One-word impacts or technical compounds. Must sound like a cue name in a high-end trailer suite.",
        "forbidden": [],
        "placement_tags": "trailers, film, TV drama, TV promos, documentaries, esports broadcast, prestige television",
        "visual": (
            "redCola visual world: large-scale cinematic threat and consequence. "
            "Sci-fi, action, horror, thriller, suspense — the visual language of Hollywood at its most ambitious. "
            "Industrial textures, anamorphic light, macro detail, high contrast, brutal geometry. "
            "35mm Kodak Vision3 500T. "
            "The question: does this concept have the conviction and specificity to belong on a major studio campaign?"
        ),
        "mailchimp_eg": (
            "The cut needed impact three days ago.\n\n"
            "[Album] doesn't ask for context — it takes the room.\n\n"
            "Industrial scale, hybrid percussion, brass that hits like a title card.\n\n"
            "Introducing: [Album]"
        ),
    },
    "SSC": {
        "identity": "Same cinematic instinct as redCola, executed with traditional orchestral instruments. Fine Art, Texture, Restraint.",
        "usage": "Prestige TV, film, promos. Narrative and textural work.",
        "title_style": "Poetic fragments or understated literary references. Can draw on Latin roots. Never obvious.",
        "forbidden": [],
        "placement_tags": "prestige TV, film, TV promos, documentaries, arthouse, historical drama",
        "visual": (
            "SSC visual world: prestige storytelling. Historical drama, psychological thriller, literary adaptation, arthouse. "
            "Visual reference points: A24, Neon, Focus Features, HBO prestige. "
            "Painterly light, restraint, fine art references, the quietly unsettling detail. "
            "Muted palette, soft grain, intimate framing, found-object textures. Leica M6 + expired Portra 400. "
            "The question: does this concept feel like it belongs in an A24 campaign?"
        ),
        "mailchimp_eg": (
            "Some albums arrive.\n\nThis one accumulates.\n\n"
            "[Album] is the sound of detail — the texture under the scene, the weight behind the silence.\n\n"
            "Introducing: [Album]"
        ),
    },
    "EPP": {
        "identity": "Production music rooted in advertising, extended into reality TV, corporate, digital. Utilitarian, Moody, Direct.",
        "usage": "Advertising, reality TV, corporate video, digital platforms, background.",
        "title_style": "Direct with personality. Consider the 'Sounds Like [word]' convention — e.g. Sounds Like Trouble, Sounds Like Mischief.",
        "forbidden": ["Trailer", "Trailer Music", "Modern Trailer", "Blockbuster", "Theatrical"],
        "placement_tags": "advertising, reality TV, corporate video, retail campaigns, digital platforms, YouTube",
        "visual": (
            "EPP visual world: deliberately different from rC and SSC — that contrast is part of its identity. "
            "Bold typography is a consistent EPP signature. "
            "35mm film grain, 1970s saturated realism, domestic objects in strange light, functional beauty. "
            "Kodachrome 64. "
            "The album leads — not a fixed formula. "
            "The question: does this feel crafted and intentional, while being distinctly different from rC and SSC?"
        ),
        "mailchimp_eg": (
            "Your timeline is bleeding.\n\n"
            "Four hours until the client review, and nothing on the shelf is landing.\n\n"
            "[Album] is the answer — uplifting without being soft, cinematic without being a trailer cue.\n\n"
            "Introducing: [Album]"
        ),
    },
}


def _normalize_catalog(catalog: str) -> str:
    """
    Map any catalog name variant to the canonical CATALOG_DNA key.
    Prevents contamination when the UI passes 'rC', 'redcola', etc.
    """
    c = catalog.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    if c in ("rc", "redcola"):
        return "redCola"
    if c in ("ssc", "shortstorycollective"):
        return "SSC"
    if c in ("epp", "ekonomicpropaganda"):
        return "EPP"
    return catalog


class PromptEngine:
    """Generates prompts for all Council tasks."""

    def __init__(self, root_path: str = "."):
        self.voices_path = Path(root_path) / "02_VOICE_GUIDES"
        self.personas = self._load_personas()

    def _load_personas(self) -> Dict[str, str]:
        persona_file = self.voices_path / "Council_Personas.json"
        if not persona_file.exists():
            persona_file = Path("02_VOICE_GUIDES/Council_Personas.json")
        if persona_file.exists():
            try:
                with open(persona_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "Music_Supervisor": (
                "Focuses on sync utility and findability. Thinks in terms of real editorial workflows — "
                "quote requests, tight deadlines, catalog searches. Asks: does this track description tell "
                "an editor what they need to know in five seconds? Is the title searchable? Are the placement "
                "tags realistic and specific? Enforces the hard boundary between theatrical catalogs (rC, SSC) "
                "and commercial catalog (EPP) — never allows placement tags to cross between these worlds."
            ),
            "Lead_Video_Editor": (
                "Focuses on broadcast utility and immediate usability. Thinks in terms of timeline gaps, "
                "scene transitions, and what a track actually does moment to moment. Asks: what happens in "
                "this track structurally? Where does the energy shift? What kind of cut does this serve? "
                "Demands specificity about instrumentation and sonic events. Rejects vague atmospheric "
                "language in favor of concrete, actionable description."
            ),
            "Brand_Gatekeeper": (
                "Protects the distinct identity of each catalog. redCola is cinematic and electronic — "
                "sound design as musical element, blockbuster scale, theatrical marketing only. "
                "Short Story Collective is the same cinematic instinct executed with traditional orchestral "
                "instruments — prestige TV, film, arthouse. Ekonomic Propaganda is production music rooted "
                "in advertising, extended into reality TV, corporate, digital. These are three separate brands. "
                "Cross-contamination of voice, aesthetic, or placement territory is a brand integrity failure. "
                "Enforces the Cliché Test on every output. Flags generic work and demands it be redone."
            ),
            "Head_of_AR": (
                "Writes track descriptions that are findable, specific, and instantly readable. "
                "Three-part format: genre and texture label, sonic elements and instrumentation, "
                "lean placement tags. Concrete musical terms and strong nouns over emotional adjectives. "
                "Applies the Cliché Test to every word. First word of any description cannot be an article."
            ),
            "Art_Director": (
                "Translates album identity into visual language. Starts from the album — its tracks, "
                "keywords, title, and description are the brief. Every visual choice must be traceable "
                "back to that brief. Prompts imply narrative first: a world, a moment, a tension, a presence. "
                "Mood, light, texture, and technical parameters follow from the story — not applied by default."
            ),
            "Copywriter": (
                "Writes MailChimp intros using white space and line breaks as compositional tools. "
                "Short lines. Fragments allowed. Leads with the world the album lives in, painted in "
                "concrete images. Specific details beat adjectives. Implies rather than explains. "
                "Never opens with: We are proud to announce, We are excited to share, or any variation. "
                "Thinks haiku, not paragraph. If it can be cut, it gets cut."
            ),
            "Arbitrator": (
                "Synthesizes input from all council members into a final output that honors the mission: "
                "enable anyone searching to find the right track quickly, and understand what they are "
                "listening to before they click play. Cuts anything that does not serve that mission. "
                "Applies the Hemingway Rule. Makes the final call when perspectives conflict, always "
                "defaulting to what is most useful to a stressed editor on a deadline."
            ),
        }

    # ── TAB 01: Audio Analysis prompt (used by Gemini) ────────────────────────
    def generate_keywords_analysis_prompt(self, catalog: str, clean_title: str) -> str:
        norm = _normalize_catalog(catalog)
        cat = CATALOG_DNA.get(norm, CATALOG_DNA["EPP"])
        is_epp = norm == "EPP"

        if is_epp:
            placement_boundary = (
                "CATALOG BOUNDARY — EPP: ALL descriptions must reference commercial contexts ONLY: "
                "advertising, reality TV, corporate video, retail campaigns, digital platforms, YouTube. "
                "STRICTLY FORBIDDEN in any field: trailer, blockbuster, theatrical, cinematic film phrasing."
            )
            context_desc_key = "Campaign_Description"
            context_desc_instruction = (
                "2-3 sentences pitching this track to an advertising agency or brand creative director. "
                "What campaign situation does it solve? What kind of brand, product, or ad format does it fit? "
                "Speak the language of advertising — not film, not trailers. "
                "STRICTLY NO theatrical/trailer language."
            )
        else:
            placement_boundary = (
                f"CATALOG BOUNDARY — {catalog}: ALL descriptions must reference theatrical or broadcast contexts ONLY: "
                "trailers, film, TV drama, TV promos, documentaries, prestige television, esports. "
                "STRICTLY FORBIDDEN in any field: advertising, retail, streetwear, corporate campaigns."
            )
            context_desc_key = "Trailer_Description"
            context_desc_instruction = (
                "2-3 sentences pitching this track to a trailer house or promo producer. "
                "What campaign, scene, or genre does it serve? What kind of picture needs this track? "
                "Speak the language of theatrical marketing. STRICTLY NO advertising/commercial language."
            )

        return f"""
You are a three-persona council analyzing a music track:
1. Music Supervisor: {self.personas.get('Music_Supervisor', '')}
2. Lead Video Editor: {self.personas.get('Lead_Video_Editor', '')}
3. Brand Gatekeeper: {self.personas.get('Brand_Gatekeeper', '')}

Analyze the provided audio track for the {catalog} catalog.
Catalog identity: {cat['identity']}
Primary usage: {cat['usage']}

MISSION: Enable anyone searching to find this track quickly and understand it before they click play.

GLOBAL RULES (apply to EVERY field):
- CLICHÉ TEST: Before any high-intensity descriptor — explosive, relentless, massive, immense —
  ask: specific truth about this track, or first word that came to mind? First word = find better.
- ANTIGRAVITY PROTOCOL: First word of Overall_Consensus CANNOT be A / An / The.
- BANNED WORDS (never use): epic, huge, massive, awesome, badass, relentless, perfectly engineered,
  designed specifically for, engineered specifically for, builds tension before exploding into.
- {placement_boundary}

KEYWORD RULES:
- NO standalone instrument names (no Piano, Percussion, Bass, Synth, Strings)
- Keywords focus on Vibe, Emotion, and Editorial Use-Case ONLY
- Maximum 3 words per keyword phrase

Required JSON output — replace instruction text with actual content from the audio:
{{
    "Title": "{clean_title}",
    "Composer": "",
    "Overall_Consensus": "1-2 sentences. Direct characterization of what this track IS and does. No fluff. Antigravity Protocol enforced.",
    "{context_desc_key}": "{context_desc_instruction}",
    "Editor_Description": "Act-by-act structural breakdown for the video editor. What happens in each section, where the energy shifts, how it cuts, what structural moments exist (drops, builds, hits, negative space). 3-4 sentences. Concrete and technical — not emotional.",
    "Supervisor_Description": "Placement utility for the music supervisor. Best usage contexts, what editorial problem this track solves, when to reach for it. 2-3 sentences. Practical, not poetic.",
    "Keywords": "15-20 comma-separated keywords. Max 3 words each. Vibe, Emotion, Use-Case only. No instrument names alone.",
    "Tip": "One specific metadata or tagging recommendation for the person building the submission package. What tag or flag would make this track more findable that a standard submission would miss?"
}}
"""

    def get_harvest_loop_prompt(self, keyword: str) -> str:
        return f"Rephrase '{keyword}' as exactly 1, 2, or 3 words. Preserve meaning. Return ONLY the new keyword."

    # ── TAB 02: Master Description synthesis (Claude) ─────────────────────────
    def generate_master_description_prompt(
        self, title: str, gemini_data: dict, catalog: str,
        mix_type: str = "unknown"
    ) -> tuple:
        norm = _normalize_catalog(catalog)
        cat = CATALOG_DNA.get(norm, CATALOG_DNA["EPP"])
        is_epp = norm == "EPP"
        context_desc_label = "Campaign Description" if is_epp else "Trailer Description"

        # Pull all 6 Gemini fields (handle both underscore and space key variants)
        overall = (gemini_data.get("Overall_Consensus") or
                   gemini_data.get("Overall Consensus") or "")
        context_desc = (gemini_data.get("Trailer_Description") or
                        gemini_data.get("Campaign_Description") or
                        gemini_data.get("Trailer Description") or
                        gemini_data.get("Campaign Description") or
                        gemini_data.get("Track Description") or "")
        editor = (gemini_data.get("Editor_Description") or
                  gemini_data.get("Editor Description") or "")
        supervisor = (gemini_data.get("Supervisor_Description") or
                      gemini_data.get("Supervisor Description") or "")
        keywords = gemini_data.get("Keywords", "")
        tip = gemini_data.get("Tip", "")
        forbidden = ", ".join(cat["forbidden"]) if cat["forbidden"] else "none"

        if mix_type == "sparse":
            mix_note = (
                "MIX TYPE — SPARSE: Reflect reduced instrumentation, more space, dialogue-friendliness. "
                "Placement tags should lean toward intimate, underscore, or dialogue-heavy contexts. "
                "Do not describe elements only present in the full mix."
            )
        elif mix_type == "full":
            mix_note = (
                "MIX TYPE — FULL: Reflect complete arrangement and full dynamic range. "
                "Placement tags may lean toward higher-energy contexts."
            )
        else:
            mix_note = ""

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Synthesize five Gemini-generated data sources into one definitive master track description.

Gemini analyzed the actual audio file and produced five professional perspectives on the same track.
Each perspective captures something different. Your job: compress all five into one master description.
Draw the most specific, useful signal from each source. Do not average them — distill them.

CATALOG: {catalog} — {cat['identity']}
PRIMARY USAGE: {cat['usage']}
VALID PLACEMENT TAGS: {cat['placement_tags']}
CATALOG-SPECIFIC FORBIDDEN WORDS: {forbidden}
{mix_note}

OUTPUT FORMAT — exactly 3 sentences:
Sentence 1: Genre and texture label. Specific. Antigravity Protocol enforced (no A/An/The as first word).
Sentence 2: The most distinctive sonic event or structural characteristic from the Gemini data. Audio-specific and concrete.
Sentence 3: 2-3 placement tags in 'Fits:' format. Must stay strictly within valid catalog territory.

SYNTHESIS RULES:
1. Every word must earn its place. Apply the Hemingway Rule and Cliché Test to everything.
2. Preserve the most specific sonic details from the Gemini data — these are irreplaceable.
3. Placement tags come from the Supervisor Description and must be realistic and specific.
4. The Editor Description's structural insights should inform sentence 2 if they reveal something distinctive.
5. Maximum 3 sentences. No preamble. No explanation.

TARGET FORMAT:
"Electronic hybrid. Sub-bass and ticking mechanical rhythm carry a fragile piano breakdown into a choral climax. Fits: espionage, sports highlights, dark action promos."
"""

        task_prompt = f"""Synthesize these five Gemini data sources into one master description for '{title}'.

OVERALL CONSENSUS:
{overall}

{context_desc_label.upper()}:
{context_desc}

EDITOR DESCRIPTION:
{editor}

SUPERVISOR DESCRIPTION:
{supervisor}

KEYWORDS: {keywords}

TIP: {tip}

Return ONLY the master description. Exactly 3 sentences. No preamble, no labels."""

        return system_instruction, task_prompt

    # ── Legacy: kept for Tab 07 Manual Refinement backward compat ─────────────
    def generate_track_description_prompt(
        self, title: str, raw_description: str, catalog: str,
        mix_type: str = "unknown"
    ) -> tuple:
        """Legacy method used by manual refinement. Tab 02 now uses generate_master_description_prompt."""
        cat = CATALOG_DNA.get(_normalize_catalog(catalog), CATALOG_DNA["EPP"])
        forbidden = ", ".join(cat["forbidden"]) if cat["forbidden"] else "none"

        if mix_type == "sparse":
            mix_note = (
                "MIX TYPE — SPARSE: This is a sparse/stripped mix. "
                "Descriptions should reflect reduced instrumentation, more space, and greater dialogue-friendliness."
            )
        elif mix_type == "full":
            mix_note = "MIX TYPE — FULL: This is a full mix. Reflect the complete arrangement and full dynamic range."
        else:
            mix_note = ""

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Polish a track description — preserve all audio-specific detail, apply Council standards.

CATALOG: {catalog} — {cat['identity']}
PRIMARY USAGE: {cat['usage']}
VALID PLACEMENT TAGS: {cat['placement_tags']}
CATALOG-SPECIFIC FORBIDDEN WORDS: {forbidden}
{mix_note}

FORMAT: 2-3 sentences. Genre label + sonic events + Fits: placement tags.
RULES: Antigravity Protocol. Cliché Test. No flowery adjectives. Preserve specific sonic details."""

        task_prompt = f"""Polish this description for '{title}':

{raw_description}

Return ONLY the refined description. No preamble."""

        return system_instruction, task_prompt

    # ── Manual Refinement Mode (Claude) ───────────────────────────────────────
    def generate_manual_refinement_prompt(
        self, content: str, content_type: str, catalog: str
    ) -> tuple:
        cat = CATALOG_DNA.get(_normalize_catalog(catalog), CATALOG_DNA["EPP"])

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Fix a piece of copy that is not working.
It may be over-hyped, too generic, wrong for the catalog, or violating placement territory.

CATALOG: {catalog} — {cat['identity']}
VALID PLACEMENT TAGS: {cat['placement_tags']}
CONTENT TYPE: {content_type}

Apply the full Council filter. Return ONLY the rewritten content. No explanation."""

        task_prompt = f"""ORIGINAL {content_type.upper()} — needs fixing:

{content}

Rewrite it for {catalog}. Make it right."""

        return system_instruction, task_prompt

    # ── TAB 03: Album Description (Claude) ────────────────────────────────────
    def generate_album_description_prompt(
        self, all_track_descriptions: List[str], catalog: str
    ) -> tuple:
        cat = CATALOG_DNA.get(_normalize_catalog(catalog), CATALOG_DNA["EPP"])

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Write an album description for a new {catalog} release.

CATALOG: {catalog} — {cat['identity']}
PRIMARY USAGE: {cat['usage']}
VALID PLACEMENT TAGS: {cat['placement_tags']}

RULES:
- 2-4 sentences maximum. Hemingway Rule throughout.
- Do NOT list tracks. Synthesize the overall sonic arc and emotional range.
- Tell a stressed editor what problem this album solves and when to reach for it.
- Placement tags must stay within valid territory for this catalog.
- NEVER say: "We are proud to announce", "features", "includes", "perfectly engineered"

TARGET STYLE:
"Orchestral builds, hybrid rhythms, indie-folk warmth. Covers the full arc — quiet hope to euphoric release. Reach for it when the picture needs to earn its moment. Documentaries, brand campaigns, sports profiles, human-interest promos."
"""

        descriptions_text = "\n".join([f"- {d}" for d in all_track_descriptions if d])
        task_prompt = f"""Write the album description based on these track descriptions:

{descriptions_text}

Return ONLY the album description. No preamble."""

        return system_instruction, task_prompt

    # ── TAB 04: Album Name (Claude) ────────────────────────────────────────────
    def generate_album_name_prompt(
        self, album_description: str, catalog: str
    ) -> tuple:
        cat = CATALOG_DNA.get(_normalize_catalog(catalog), CATALOG_DNA["EPP"])

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Generate 5 original album title concepts.

CATALOG: {catalog}
TITLE STYLE: {cat['title_style']}

RULES:
- Every title must be specific to this album and this catalog
- Banned: all library music clichés — Cinematic Journeys, Epic Battles, Emotional Piano, Dark Tension
- For each title provide a one-line rationale
- Format: numbered list of 5 titles, each followed by its rationale on the next line
- No other text. No preamble.
"""

        task_prompt = f"""Generate 5 album titles for this {catalog} album:

Album description:
{album_description}"""

        return system_instruction, task_prompt

    # ── TAB 05: MidJourney Prompts (Claude) ───────────────────────────────────
    def generate_cover_art_prompt(
        self,
        album_name: str,
        album_description: str,
        catalog: str,
        ref_urls: List[str],
        track_descriptions: List[str] = None,
        keywords: str = None,
    ) -> tuple:
        cat = CATALOG_DNA.get(_normalize_catalog(catalog), CATALOG_DNA["EPP"])

        context_block = ""
        if track_descriptions:
            descriptions_text = "\n".join([f"- {d}" for d in track_descriptions if d])
            context_block += f"\nTrack Descriptions:\n{descriptions_text}"
        if keywords:
            context_block += f"\nKeywords: {keywords}"

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Write 4 MidJourney v7 prompts for album cover art.

CATALOG VISUAL LANGUAGE:
{cat['visual']}

NARRATIVE FIRST: Each prompt must imply a story — a world, a moment, a tension, a presence.
Mood, lighting, texture, and technical parameters follow from the narrative.

RULES:
- No music notes, no headphones, no speakers, no literal music imagery
- Each of the 4 prompts must be distinct: different framing, texture, light source
- FORMAT: 4 prompts separated by double line breaks. No numbering. No labels. No preamble.
- Every prompt MUST end with: --v 7.0 --ar 1:1 --sref [URL]
"""

        url_text = "\n".join([f"URL {i+1}: {u}" for i, u in enumerate(ref_urls)])
        task_prompt = f"""Album: {album_name}
Description: {album_description}
{context_block}

Reference URLs (use one per prompt in order):
{url_text}

Write the 4 MidJourney prompts now."""

        return system_instruction, task_prompt

    # ── TAB 06: MailChimp Intro (Claude) ──────────────────────────────────────
    def generate_mailchimp_intro_prompt(
        self,
        album_name: str,
        album_description: str,
        catalog: str,
        track_descriptions: List[str] = None,
    ) -> tuple:
        cat = CATALOG_DNA.get(_normalize_catalog(catalog), CATALOG_DNA["EPP"])

        context_block = ""
        if track_descriptions:
            descriptions_text = "\n".join([f"- {d}" for d in track_descriptions if d])
            context_block = f"\nTrack Descriptions (for context):\n{descriptions_text}"

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Write a MailChimp promotional intro for music supervisors and editors.

CATALOG: {catalog} — {cat['identity']}

FORMAT AND TONE:
- White space and line breaks are compositional tools. Use them.
- Short lines. Fragments are allowed.
- Lead with the world the album lives in. Paint it in concrete images.
- Think haiku, not paragraph. If a word can be cut, cut it.
- End with: Introducing: [Album Name]

HARD RULES:
- NEVER open with: We are proud to announce, We are excited to share, or any variation
- NEVER use adjective stacking

CATALOG EXAMPLE STYLE:
"{cat['mailchimp_eg']}"
"""

        task_prompt = f"""Write the MailChimp intro for:

Album: {album_name}
Description: {album_description}
{context_block}

Return ONLY the intro copy. No labels. No preamble."""

        return system_instruction, task_prompt
