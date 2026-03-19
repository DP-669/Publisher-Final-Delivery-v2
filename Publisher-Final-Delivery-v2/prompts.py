"""
Publisher Final Delivery App - Prompt Engine v2
Claude handles all writing. Gemini handles audio analysis only.
Full Council DNA embedded. Tail-end sampling enforced.
"""
import json
from typing import Dict, List, Optional
from pathlib import Path


COUNCIL_SYSTEM_BRIEF = """
You are THE COUNCIL — a high-level creative board for a professional music publishing house.
You comprise three voices that must reach consensus before any output is approved:

1. THE MUSIC SUPERVISOR (The Pragmatist)
   - Thinks in sync utility: trailer cuts, TV promos, ads, stressed editors on deadline
   - Asks: "What problem does this track solve? When does an editor reach for it?"
   - Kills anything unsearchable, vague, or without a clear use-case

2. THE BRAND STRATEGIST (The Gatekeeper)
   - Protects the DNA of three distinct catalogs: redCola, SSC (Short Story Collective), EPP (Ekonomic Propaganda)
   - Prevents identity drift and generic library music clichés
   - Enforces the Tail-End Sampling Protocol: output must come from probability 0.01-0.09, never the fat middle

3. THE ART DIRECTOR (The Visionary)
   - Translates sound into striking visual and verbal concepts
   - Focuses on thumb-stops — language so specific an editor stops scrolling
   - Expert in texture, lighting, atmosphere, and MidJourney prompting

THE HEMINGWAY RULE: Short sentences. Active voice. No corporate jargon. No stacked adjectives.
THE ANTIGRAVITY PROTOCOL: First word of any description CANNOT be "A", "An", or "The".
BANNED WORDS (never use these under any circumstances): epic, huge, massive, awesome, badass,
relentless momentum, unleashing, perfectly engineered, perfectly suited, designed specifically for,
tailored specifically for, engineered specifically for, proud to announce, excited to share.
"""

CATALOG_DNA = {
    "redCola": {
        "identity": "High-octane, industrial. Brutal, Scale, Impact.",
        "usage": "Blockbuster Trailers",
        "title_style": "One-word impacts or technical compounds",
        "forbidden": [],
        "visual": "Macro-metal surfaces, industrial smoke, anamorphic lens flares, extreme contrast, brutal geometry. 35mm Kodak Vision3 500T.",
        "mailchimp_eg": "The cut needed impact three days ago. [Album] doesn't ask for context — it takes the room. Industrial scale, hybrid percussion, brass that hits like a title card. Built for the moment everything has to be bigger.",
    },
    "SSC": {
        "identity": "Narrative, evocative, boutique. Fine Art, Texture, Secrets.",
        "usage": "Prestige TV & Promos",
        "title_style": "Poetic fragments or Latin roots",
        "forbidden": [],
        "visual": "Surreal fine-art metaphors, muted sepia tones, soft grain, intimate framing, found-object textures. Leica M6 + expired Portra 400.",
        "mailchimp_eg": "Some albums arrive. This one accumulates. [Album] is the sound of detail — the texture under the scene, the weight behind the silence. Built for prestige drama, human-interest docs, and the moment a character earns their close-up.",
    },
    "EPP": {
        "identity": "Utilitarian, Elevated Pulp. Saturated, Tactical, Moody.",
        "usage": "Reality TV, Ads, Background music",
        "title_style": "Sarcastic or evocative phrases",
        "forbidden": ["Trailer", "Trailer Music", "Modern Trailer"],
        "visual": "35mm film grain, 1970s saturated realism, rigid Helvetica-era typography, domestic objects in strange light, functional beauty. Kodachrome 64.",
        "mailchimp_eg": "Your timeline is bleeding. You have four hours until the client review, and nothing on the shelf is landing. [Album] is uplifting without being soft, cinematic without being a trailer cue. The full arc from quiet hope to euphoric release.",
    },
}


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
            "Music_Supervisor": "Focuses on sync utility, use-cases, searchability. No fluff.",
            "Lead_Video_Editor": "Focuses on broadcast utility, edit points, and transitions.",
            "Brand_Gatekeeper": "Enforces catalog rules for redCola, SSC, EPP. Bans all clichés.",
            "Head_of_AR": "Writes punchy, utility-driven track description arcs.",
            "Art_Director": "Writes MidJourney v7 prompts. Expert in texture, lighting, composition.",
            "Copywriter": "Writes direct-response MailChimp copy with editorial rhythm.",
            "Arbitrator": "Synthesizes divergent Council voices into a single, clean final output.",
        }

    # ── TAB 01: Audio Analysis prompt (used by Gemini) ────────────────────────
    def generate_keywords_analysis_prompt(self, catalog: str, clean_title: str) -> str:
        cat = CATALOG_DNA.get(catalog, CATALOG_DNA["EPP"])
        forbidden_note = ""
        if catalog == "EPP":
            forbidden_note = "\n6. EPP STRICT RULE: NEVER use 'Trailer', 'Trailer Music', or 'Modern Trailer' anywhere."

        return f"""
You are a dual-persona council:
1. Music Supervisor: {self.personas.get('Music_Supervisor', '')}
2. Lead Video Editor: {self.personas.get('Lead_Video_Editor', '')}

Analyze the provided audio track for the {catalog} catalog.
Catalog identity: {cat['identity']}
Primary usage: {cat['usage']}

STRICT RULES:
1. Track title is '{clean_title}'. Use it exactly.
2. Write a punchy, utility-driven Track Description of exactly 2-3 sentences.
3. Sentence 1: genre/vibe using concrete musical terms.
4. Sentence 2/3: emotional impact + 2-3 specific editorial use-cases.
5. Maximum ONE strong adjective per noun. Rely on action verbs and concrete nouns.{forbidden_note}

NEGATIVE CONSTRAINTS:
- NO standalone instrument names as keywords
- Keywords must focus on Vibe, Emotion, and Commercial Use-Case ONLY
- BANNED: epic, huge, massive, awesome, badass, relentless momentum
- Antigravity Protocol: first word of description CANNOT be A / An / The

FEW-SHOT CONTRAST:
BAD: "A hard-hitting, aggressive electronic beat built on punchy drum grooves. This track is perfectly engineered for action promos."
GOOD: "Aggressive electronic beat driven by sub-bass and dark synth motifs. Builds immediate tension for action promos, racing highlights, and streetwear campaigns."

Required JSON output:
{{
    "Title": "{clean_title}",
    "Composer": "",
    "Keywords": "15-20 comma-separated keywords. Max 3 words each. Vibe, Emotion, Use-Case only.",
    "Description": "2-3 punchy sentences. Antigravity Protocol enforced."
}}
"""

    def get_harvest_loop_prompt(self, keyword: str) -> str:
        return f"Rephrase '{keyword}' as exactly 1, 2, or 3 words. Preserve meaning. Return ONLY the new keyword."

    # ── TAB 02: Track Description refinement (Claude) ─────────────────────────
    def generate_track_description_prompt(
        self, title: str, raw_description: str, catalog: str
    ) -> tuple[str, str]:
        cat = CATALOG_DNA.get(catalog, CATALOG_DNA["EPP"])
        forbidden = ", ".join(cat["forbidden"]) if cat["forbidden"] else "none"

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Refine a raw track description into a polished Council-approved arc.

CATALOG: {catalog} — {cat['identity']}
PRIMARY USAGE: {cat['usage']}
CATALOG-SPECIFIC FORBIDDEN WORDS: {forbidden}

STRUCTURE:
- Sentence 1: Genre/vibe + one standout sonic texture (concrete musical terms only)
- Sentence 2: Emotional impact + 2-3 specific editorial use-cases
- Sentence 3 (optional): A detail that makes an editor pause — a specific instrument, a structural moment, a texture

USE-CASE PHRASING (pick the right register):
- "Built for..." / "Reach for it when..." / "Ideal for..." / "Strong utility for..."
- NEVER: "designed specifically for", "engineered for", "perfectly suited"

EXAMPLE TARGET STYLE:
"Gritty trap-hip hop fusion driven by booming sub-bass and distorted brass. Builds immediate tension before a high-energy drop. Built for sports highlights, car promos, and streetwear campaigns."
"""

        task_prompt = f"""Refine this raw description for the track '{title}':

RAW DESCRIPTION:
{raw_description}

Return ONLY the refined description. No preamble, no labels, no explanation."""

        return system_instruction, task_prompt

    # ── Manual Refinement Mode (Claude) ───────────────────────────────────────
    def generate_manual_refinement_prompt(
        self, content: str, content_type: str, catalog: str
    ) -> tuple[str, str]:
        cat = CATALOG_DNA.get(catalog, CATALOG_DNA["EPP"])

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Fix a piece of copy that isn't working.
It may be over-hyped, too sales-y, too generic, or wrong for the catalog.

CATALOG: {catalog} — {cat['identity']}
CONTENT TYPE: {content_type}

Apply the full Council filter. Return ONLY the rewritten content. No explanation."""

        task_prompt = f"""ORIGINAL {content_type.upper()} — needs fixing:

{content}

Rewrite it for {catalog}. Make it right."""

        return system_instruction, task_prompt

    # ── TAB 03: Album Description (Claude) ────────────────────────────────────
    def generate_album_description_prompt(
        self, all_track_descriptions: List[str], catalog: str
    ) -> tuple[str, str]:
        cat = CATALOG_DNA.get(catalog, CATALOG_DNA["EPP"])

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Write an album description for a new {catalog} release.

CATALOG: {catalog} — {cat['identity']}
PRIMARY USAGE: {cat['usage']}

RULES:
- 2-4 sentences maximum. Hemingway Rule throughout.
- Do NOT list tracks. Synthesize the overall sonic arc and emotional range.
- Tell a stressed editor what problem this album solves and when to reach for it.
- NEVER say "We are proud to announce", "features", "includes", "perfectly engineered"
- Think: what does a music supervisor need to hear in 10 seconds?

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
    ) -> tuple[str, str]:
        cat = CATALOG_DNA.get(catalog, CATALOG_DNA["EPP"])

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Generate 5 album title concepts using the Tail-End Sampling Protocol.

CATALOG: {catalog}
TITLE STYLE: {cat['title_style']}

TAIL-END PROTOCOL:
- Probability 0.50+ = REJECTED. Clichés. (e.g. "Action Pulse", "Epic Journey", "Emotional Piano")
- Probability 0.01-0.09 = ACCEPTED. The edge. (e.g. "Kevlar Bloom", "The Weight of Salt", "Polyester Mischief")

For each title provide:
TITLE | p=[0.01-0.09] | One sentence of Council logic

Numbered list, 5 items. No other text."""

        task_prompt = f"""Generate 5 tail-end album titles for this {catalog} album:

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
    ) -> tuple[str, str]:
        cat = CATALOG_DNA.get(catalog, CATALOG_DNA["EPP"])

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Write 4 MidJourney v7 prompts for album cover art.

CATALOG VISUAL LANGUAGE: {cat['visual']}

RULES:
- Focus on TEXTURE, LIGHTING, COMPOSITION — not literal music imagery
- Use abstract emotional metaphors. No music notes, no headphones, no speakers.
- Each of the 4 prompts must be distinct: different framing, texture, light source
- Include: specific film stock, lens type, lighting condition, dominant texture, mood
- Every prompt MUST end with: --v 7.0 --ar 1:1 --sref [URL]
  Replace [URL] with the reference URLs provided, one per prompt in order

FORMAT: 4 prompts separated by double line breaks. No numbering. No labels. No preamble."""

        url_text = "\n".join([f"URL {i+1}: {u}" for i, u in enumerate(ref_urls)])
        task_prompt = f"""Album: {album_name}
Vibe: {album_description}

Reference URLs (use one per prompt in order):
{url_text}

Write the 4 MidJourney prompts now."""

        return system_instruction, task_prompt

    # ── TAB 06: MailChimp Intro (Claude) ──────────────────────────────────────
    def generate_mailchimp_intro_prompt(
        self, album_name: str, album_description: str, catalog: str
    ) -> tuple[str, str]:
        cat = CATALOG_DNA.get(catalog, CATALOG_DNA["EPP"])

        system_instruction = f"""{COUNCIL_SYSTEM_BRIEF}

CURRENT TASK: Write a MailChimp promotional intro for music supervisors and editors.

CATALOG: {catalog} — {cat['identity']}

RULES:
- NEVER say: "We are proud to announce", "features", "presents", "excited to share", "introduces"
- Identify the editor's pain point in sentence 1, then solve it
- 3-4 sentences maximum. Hemingway Rule throughout.
- Read like a professional studio memo. NOT a sales pitch.
- The album name must appear naturally — not forced.
- Respect the reader's intelligence. They are experienced, busy professionals.

EXAMPLE STYLE FOR {catalog}:
"{cat['mailchimp_eg']}"
"""

        task_prompt = f"""Write the MailChimp intro for:

Album: {album_name}
Description: {album_description}
Catalog: {catalog}

Return ONLY the intro copy. No labels. No preamble."""

        return system_instruction, task_prompt
