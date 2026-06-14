import logging
import re
from typing import final

from pymonad.either import Left, Right, Either

from mempalace_backfill.alias import Error
from mempalace_backfill.classify.session_classifier import ClassifiedSegment, SessionClassifier


MARKER_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "decision": [
        # Choice verbs
        re.compile(r"\b(decided|chose|picked|settled on|went with|switched to)\b", re.IGNORECASE),
        re.compile(r"\b(approach|strategy|architecture|design decision)\b", re.IGNORECASE),
        re.compile(r"\b(the reason|because|instead of|rather than)\b", re.IGNORECASE),
        re.compile(r"\b(trade-?off|pros and cons|alternative|option)\b", re.IGNORECASE),
        # Directive / imperative decisions
        re.compile(r"\b(put it in|use that|go with|change it to|switch to|move to|make it)\b", re.IGNORECASE),
        re.compile(r"\b(i want you to|i need you to|you should|you must)\b", re.IGNORECASE),
        # Agreement as decision acceptance
        re.compile(r"\b^ok[,.] |^okay[,.] |^sure[,.] |^fine[,.] |alright\b", re.IGNORECASE),
        # Correction decisions
        re.compile(r"\b(should be|needs to be|has to be|must be|should go in)\b", re.IGNORECASE),
    ],
    "milestone": [
        # Completion delivery
        re.compile(r"\b(finally|shipped|launched|deployed|released|built|created|implemented)\b", re.IGNORECASE),
        re.compile(r"\b(got it working|works now|solved|fixed|breakthrough)\b", re.IGNORECASE),
        re.compile(r"\b(v\d+\.\d+|version \d|prototype|proof of concept|demo)\b", re.IGNORECASE),
        re.compile(r"\b(figured out|nailed it|cracked it|discovered|realized)\b", re.IGNORECASE),
        re.compile(r"\b(final version)\b", re.IGNORECASE),
        # Done / completion markers
        re.compile(r"\b(done|completed|finished|all done|is done|was done)\b", re.IGNORECASE),
        re.compile(r"\b(it works|works now|working now|is working|passes|passing)\b", re.IGNORECASE),
        # Verification as milestone gate
        re.compile(r"\b(test it|verify it|check it|confirm it|ensure it)\b", re.IGNORECASE),
        # Temporal completion
        re.compile(r"\b(all tasks complete|task complete|tasks done|finished with|wrapped up)\b", re.IGNORECASE),
    ],
    "architecture": [
        re.compile(r"\b(architecture|pattern|framework|stack|infrastructure)\b", re.IGNORECASE),
        re.compile(r"\b(module|component|service|layer|interface|schema|middleware)\b", re.IGNORECASE),
        re.compile(r"\b(microservices|monolith|event.driven|CQRS|event sourcing|REST|GraphQL)\b", re.IGNORECASE),
        # System / project organization
        re.compile(r"\b(pipeline|integration|migration|refactor|restructure|redesign)\b", re.IGNORECASE),
        re.compile(r"\b(configuration|setup|structure|layout|topology|deployment)\b", re.IGNORECASE),
        # Specific project references
        re.compile(r"\b(project structure|codebase|repository|workspace|directory layout)\b", re.IGNORECASE),
    ],
    "preference": [
        # Explicit preference
        re.compile(r"\b(i prefer|always use|never use|better to|my rule|i like to)\b", re.IGNORECASE),
        re.compile(r"\b(please always|please never|don'?t .* (use|do))\b", re.IGNORECASE),
        re.compile(r"\b(functional style|imperative|snake.case|camel.case)\b", re.IGNORECASE),
        # Want / don't want
        re.compile(r"\b(i want|i don'?t want|i do not want|i would like|i'?d like)\b", re.IGNORECASE),
        re.compile(r"\b(i will not|i won'?t|we must never|we should never|never use)\b", re.IGNORECASE),
        # Quality / style judgment
        re.compile(r"\b(clean code|clean|messy|ugly|elegant|proper way|right way|wrong way)\b", re.IGNORECASE),
        re.compile(r"\b(functional|monadic|TDD|typed|strict|pattern)\b", re.IGNORECASE),
    ],
    "problem": [
        # Error vocabulary
        re.compile(r"\b(bug|error|crash|fail|broke|broken|issue|problem)\b", re.IGNORECASE),
        re.compile(r"\b(doesn'?t work|not working|root cause|workaround)\b", re.IGNORECASE),
        re.compile(r"\b(the (fix|issue|bug|problem) (is|was))\b", re.IGNORECASE),
        # Negative state / stuck
        re.compile(r"\b(wrong|stuck|blocked|halting|failing|fails|not work)\b", re.IGNORECASE),
        re.compile(r"\b(regression|introduced an error|something wrong|whats wrong|what is wrong)\b", re.IGNORECASE),
        # Debugging / investigation
        re.compile(r"\b(debug|investigate|diagnose|repair|rollback|revert|fix this)\b", re.IGNORECASE),
        # Urgent problem
        re.compile(r"\b(stop|emergency|critical|urgent|immediately|asap|right now)\b", re.IGNORECASE),
    ],
    "emotional": [
        # Standard emotional vocabulary
        re.compile(r"\b(love|scared|afraid|proud|happy|sad|grateful|worried)\b", re.IGNORECASE),
        re.compile(r"\b(i feel|i'?m scared|i'?m sorry|i wish|i need)\b", re.IGNORECASE),
        # Frustration / anger
        re.compile(r"\b(frustrated|frustrating|stupid|ridiculous|annoyed|annoying|wtf|dumb|hell|bullshit|damn|crap)\b", re.IGNORECASE),
        re.compile(r"\b(this is ridiculous|this is stupid|what the fuck|how fucking hard|fucking (this|thing|approach|bullshit|shit))\b", re.IGNORECASE),
        re.compile(r"\b(not acceptable|doesn'?t work man|doesnt work man|this bullshit)\b", re.IGNORECASE),
        # Satisfaction / relief
        re.compile(r"\b(ah .+ works now|ok great|cool|nice)\b", re.IGNORECASE),
        re.compile(r"\b(it worked|that is great|thats great|thats good|yeah thats good)\b", re.IGNORECASE),
        # Impatience / urgency
        re.compile(r"\b(impatient|impatience|im in a hurry|still waiting|still nothing)\b", re.IGNORECASE),
        re.compile(r"\b(in a hurry|hurry up|come on)\b", re.IGNORECASE),
        # French emotional vocabulary
        re.compile(r"\b(putain|merde|bordel|connard|salope)\b", re.IGNORECASE),
        re.compile(r"\b(putain mais|corrige direct|fait chier|c'est absurde|c'est n'importe quoi)\b", re.IGNORECASE),
        # Confusion / concern
        re.compile(r"\b(confused|confusing|weird|unclear|why did u|why is this necessary)\b", re.IGNORECASE),
        # Enthusiasm / excitement
        re.compile(r"\b(excited|exciting|amazing|awesome|fantastic|wonderful)\b", re.IGNORECASE),
    ],
}


@final
class RegexClassifier(SessionClassifier):
    """Regex-based session classifier.

    Accepts optional *custom_patterns* — a dict mapping marker names to lists
    of raw regex strings.  When provided, the custom patterns are compiled and
    merged into the built-in :data:`MARKER_PATTERNS` so they match alongside
    the default rules.
    """

    def __init__(
        self,
        custom_patterns: dict[str, list[str]] | None = None,
    ) -> None:
        self._custom_compiled: dict[str, list[re.Pattern[str]]] = {}
        if custom_patterns:
            for marker, patterns in custom_patterns.items():
                compiled: list[re.Pattern[str]] = []
                for p in patterns:
                    try:
                        compiled.append(re.compile(p, re.IGNORECASE))
                    except re.error:
                        logging.warning(
                            "RegexClassifier: invalid custom pattern %r for marker %s — skipped",
                            p, marker,
                        )
                if compiled:
                    self._custom_compiled[marker] = compiled

    def _patterns_for(self, marker: str) -> list[re.Pattern[str]]:
        """Return built-in + custom patterns for *marker*."""
        built_in = MARKER_PATTERNS.get(marker, [])
        custom = self._custom_compiled.get(marker, [])
        return built_in + custom if custom else built_in

    def classify(self, session_content: str, markers: list[str]) -> Either[Error, list[ClassifiedSegment]]:
        """
        Classifies session content into segments based on regex patterns.

        Args:
            session_content: The full content of the session.
            markers: The list of markers to search for.

        Returns:
            An Either containing an Error or a list of ClassifiedSegments.
        """
        try:
            # Split content into passages (paragraphs)
            # Passages are separated by two or more newlines
            passages = re.split(r'\n\n+', session_content)
            
            classified_segments: list[ClassifiedSegment] = []
            current_offset = 0
            
            for passage in passages:
                passage_markers: list[str] = []
                
                # Idempotency check: skip if passage already starts with [marker]
                # Any marker in the list of allowed markers
                existing_marker_match = re.match(r'^\s*\[(decision|milestone|architecture|preference|problem|emotional)\]', passage)
                if existing_marker_match:
                    # Skip classification for this passage
                    current_offset += len(passage)
                    # Account for the removed newlines in split if not last passage
                    match = re.search(r'\n\n+', session_content[current_offset:])
                    if match and match.start() == 0:
                        current_offset += match.end()
                    continue

                for marker in markers:
                    for pattern in self._patterns_for(marker):
                        if pattern.search(passage):
                            if marker not in passage_markers:
                                passage_markers.append(marker)
                                break
                
                if passage_markers:
                    start = session_content.find(passage, current_offset)
                    if start != -1:
                        end = start + len(passage)
                        classified_segments.append(
                            ClassifiedSegment(
                                content=passage,
                                markers=passage_markers,
                                start_offset=start,
                                end_offset=end
                            )
                        )
                
                # Update offset for next search
                start_search = session_content.find(passage, current_offset)
                if start_search != -1:
                    current_offset = start_search + len(passage)
                    # Re-include separators for accurate offset tracking
                    match = re.search(r'\n\n+', session_content[current_offset:])
                    if match and match.start() == 0:
                        current_offset += match.end()
            
            return Right(classified_segments)
        except Exception as e:
            from pymonad.maybe import Just
            return Left(Error(f"Failed to classify content with regex: {str(e)}", Just(e)))
